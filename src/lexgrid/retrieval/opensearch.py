"""OpenSearch: versioned index per jurisdiction, alias promotion/rollback, and the live search backend.

Naming: physical index  legal-<cc>-<yyyymmddhhmmss>-<snapshot8>, alias legal-<cc>-current.
Promotion and rollback are one atomic `_aliases` call, so readers never see a half-built index.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from lexgrid.chunking import CHUNKER_VERSION
from lexgrid.embed import Matrix
from lexgrid.retrieval.base import Filters, Hit
from lexgrid.store import LineageStore

SOURCE_FIELDS = [
    "chunk_id",
    "article_key",
    "article_number",
    "citation_id",
    "jurisdiction",
    "language",
    "chunk_path",
    "text",
    "valid_from",
    "valid_to",
]
EXACT_REF_BOOST = 5.0


def alias_name(jurisdiction: str) -> str:
    return f"legal-{jurisdiction.lower()}-current"


def snapshot_sha(chunk_ids: Sequence[str], embedding_models: Sequence[str]) -> str:
    h = hashlib.sha256()
    for part in [CHUNKER_VERSION, *sorted(embedding_models), *sorted(chunk_ids)]:
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()


def index_body(dims: Mapping[str, int]) -> dict[str, Any]:
    vec_props = {
        f"vec_{name}": {
            "type": "knn_vector",
            "dimension": dim,
            "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"},
        }
        for name, dim in dims.items()
    }
    return {
        "settings": {
            "index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0},
            "analysis": {
                "analyzer": {
                    "folded": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding"],
                    }
                },
                "normalizer": {"lower": {"type": "custom", "filter": ["lowercase"]}},
            },
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "chunk_id": {"type": "keyword"},
                "article_key": {"type": "keyword"},
                "article_number": {"type": "keyword", "normalizer": "lower"},
                "citation_id": {"type": "keyword"},
                "jurisdiction": {"type": "keyword"},
                "language": {"type": "keyword"},
                "doc_type": {"type": "keyword"},
                "license": {"type": "keyword", "index": False},
                "chunk_path": {"type": "text", "analyzer": "folded"},
                "text": {
                    "type": "text",
                    "analyzer": "folded",
                    "fields": {
                        "fr": {"type": "text", "analyzer": "french"},
                        "en": {"type": "text", "analyzer": "english"},
                        "de": {"type": "text", "analyzer": "german"},
                    },
                },
                "valid_from": {"type": "date"},
                "valid_to": {"type": "date"},
                "doc_version_id": {"type": "keyword"},
                "chunker_version": {"type": "keyword"},
                **vec_props,
            },
        },
    }


class IndexManager:
    def __init__(self, client: Any, store: LineageStore) -> None:
        self.client = client
        self.store = store

    def build(
        self,
        jurisdiction: str,
        chunks: Sequence[Mapping[str, Any]],
        vectors: Mapping[str, Matrix],
        model_ids: Mapping[str, str],
    ) -> str:
        """Create a new physical index, load it, record an index_run (status=built). Returns index name."""
        if not chunks:
            raise ValueError(f"no live chunks for {jurisdiction}")
        for name, mat in vectors.items():
            if mat.shape[0] != len(chunks):
                raise ValueError(f"vectors {name}: {mat.shape[0]} rows for {len(chunks)} chunks")
        snap = snapshot_sha([c["id"] for c in chunks], list(model_ids.values()))
        stamp = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")
        index = f"legal-{jurisdiction.lower()}-{stamp}-{snap[:8]}"
        start = time.perf_counter()
        self.client.indices.create(index=index, body=index_body({n: m.shape[1] for n, m in vectors.items()}))
        ops: list[dict[str, Any]] = []
        for i, c in enumerate(chunks):
            doc = {
                "chunk_id": c["id"],
                "article_key": c["article_key"],
                "article_number": c["article_number"],
                "citation_id": c["citation_id"],
                "jurisdiction": c["jurisdiction"],
                "language": c["language"],
                "doc_type": c.get("doc_type"),
                "license": c["license"],
                "chunk_path": c["chunk_path"],
                "text": c["text"],
                "valid_from": c["valid_from"].isoformat() if c.get("valid_from") else None,
                "valid_to": c["valid_to"].isoformat() if c.get("valid_to") else None,
                "doc_version_id": c["doc_version_id"],
                "chunker_version": c["chunker_version"],
                **{f"vec_{n}": [float(x) for x in m[i]] for n, m in vectors.items()},
            }
            ops.extend([{"index": {"_index": index, "_id": c["id"]}}, doc])
        for i in range(0, len(ops), 400):
            resp = self.client.bulk(body=ops[i : i + 400])
            if resp.get("errors"):
                raise RuntimeError(f"bulk indexing errors in {index}: {str(resp)[:500]}")
        self.client.indices.refresh(index=index)
        self.store.add_index_run(
            {
                "run_id": index,
                "jurisdiction": jurisdiction,
                "index_name": index,
                "corpus_snapshot_sha": snap,
                "embedding_model": ",".join(f"{k}={v}" for k, v in sorted(model_ids.items())),
                "chunker_version": CHUNKER_VERSION,
                "n_docs": len({c["doc_version_id"] for c in chunks}),
                "n_chunks": len(chunks),
                "duration_s": round(time.perf_counter() - start, 3),
                "eval_run_id": None,
                "status": "built",
                "created_at": datetime.now(tz=UTC),
                "promoted_at": None,
            }
        )
        return index

    def current(self, jurisdiction: str) -> str | None:
        alias = alias_name(jurisdiction)
        if not self.client.indices.exists_alias(name=alias):
            return None
        targets = list(self.client.indices.get_alias(name=alias).keys())
        return targets[0] if targets else None

    def _swap(self, jurisdiction: str, new_index: str) -> str | None:
        alias = alias_name(jurisdiction)
        old = self.current(jurisdiction)
        actions: list[dict[str, Any]] = []
        if old:
            actions.append({"remove": {"index": old, "alias": alias}})
        actions.append({"add": {"index": new_index, "alias": alias}})
        self.client.indices.update_aliases(body={"actions": actions})
        return old

    def promote(self, jurisdiction: str, index: str) -> str | None:
        runs = {r["run_id"]: r for r in self.store.index_runs(jurisdiction)}
        if index not in runs:
            raise ValueError(f"{index} is not a recorded index run for {jurisdiction}")
        old = self._swap(jurisdiction, index)
        if old and old != index:
            self.store.set_index_run_status(old, "retired")
        self.store.set_index_run_status(index, "promoted", promoted=True)
        return old

    def rollback(self, jurisdiction: str) -> str:
        """Point the alias back to the most recently promoted index before the current one."""
        current = self.current(jurisdiction)
        previous = [
            r
            for r in self.store.index_runs(jurisdiction)
            if r["status"] == "retired" and r["promoted_at"] is not None and r["run_id"] != current
        ]
        if not previous:
            raise RuntimeError(f"no previous promoted index to roll back to for {jurisdiction}")
        target = max(previous, key=lambda r: r["promoted_at"])["run_id"]
        self._swap(jurisdiction, target)
        if current:
            self.store.set_index_run_status(current, "rolled_back")
        self.store.set_index_run_status(target, "promoted", promoted=True)
        return str(target)


def _date(v: str | None) -> date | None:
    return date.fromisoformat(v[:10]) if v else None


class OpenSearchBackend:
    """Searches only entitled aliases: scope is enforced by index, and again by filter."""

    def __init__(self, client: Any) -> None:
        self.client = client

    @staticmethod
    def _filter(f: Filters) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"terms": {"jurisdiction": list(f.jurisdictions)}}]
        if f.languages:
            out.append({"terms": {"language": list(f.languages)}})
        if f.doc_types:
            out.append({"terms": {"doc_type": list(f.doc_types)}})
        if f.as_of:
            d = f.as_of.isoformat()
            out.append(
                {
                    "bool": {
                        "must": [
                            {
                                "bool": {
                                    "should": [
                                        {"range": {"valid_from": {"lte": d}}},
                                        {"bool": {"must_not": {"exists": {"field": "valid_from"}}}},
                                    ]
                                }
                            },
                            {
                                "bool": {
                                    "should": [
                                        {"range": {"valid_to": {"gt": d}}},
                                        {"bool": {"must_not": {"exists": {"field": "valid_to"}}}},
                                    ]
                                }
                            },
                        ]
                    }
                }
            )
        return out

    @staticmethod
    def _targets(f: Filters) -> str:
        return ",".join(alias_name(j) for j in f.jurisdictions)

    @staticmethod
    def _hits(resp: Mapping[str, Any]) -> list[Hit]:
        out: list[Hit] = []
        for h in resp["hits"]["hits"]:
            s = h["_source"]
            out.append(
                Hit(
                    chunk_id=s["chunk_id"],
                    article_key=s["article_key"],
                    article_number=s["article_number"],
                    citation_id=s["citation_id"],
                    jurisdiction=s["jurisdiction"],
                    language=s["language"],
                    chunk_path=s["chunk_path"],
                    text=s["text"],
                    score=float(h["_score"]),
                    valid_from=_date(s.get("valid_from")),
                    valid_to=_date(s.get("valid_to")),
                )
            )
        return out

    def bm25(self, query: str, filters: Filters, k: int, refs: set[str]) -> list[Hit]:
        should: list[dict[str, Any]] = []
        if refs:
            should.append({"terms": {"article_number": sorted(refs), "boost": EXACT_REF_BOOST}})
        body = {
            "size": k,
            "_source": SOURCE_FIELDS,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["text", "text.fr", "text.en", "text.de", "chunk_path^0.5"],
                                "type": "best_fields",
                            }
                        }
                    ],
                    "should": should,
                    "filter": self._filter(filters),
                }
            },
        }
        return self._hits(self.client.search(index=self._targets(filters), body=body))

    def dense(self, vector: list[float], field_name: str, filters: Filters, k: int) -> list[Hit]:
        body = {
            "size": k,
            "_source": SOURCE_FIELDS,
            "query": {
                "knn": {
                    field_name: {
                        "vector": vector,
                        "k": k,
                        "filter": {"bool": {"filter": self._filter(filters)}},
                    }
                }
            },
        }
        return self._hits(self.client.search(index=self._targets(filters), body=body))


def make_client(url: str = "http://localhost:9200") -> Any:
    from opensearchpy import OpenSearch  # lazy

    return OpenSearch(hosts=[url], timeout=60, http_compress=True)
