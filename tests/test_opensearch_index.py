"""Index lifecycle against an in-memory fake OpenSearch client (live behaviour is checked on the Mac)."""

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from lexgrid.retrieval.base import Filters
from lexgrid.retrieval.opensearch import IndexManager, OpenSearchBackend, alias_name, index_body
from lexgrid.store import LineageStore


class FakeIndices:
    def __init__(self) -> None:
        self.indices: dict[str, dict[str, Any]] = {}
        self.aliases: dict[str, set[str]] = {}
        self.alias_calls: list[list[dict[str, Any]]] = []

    def create(self, index: str, body: dict[str, Any]) -> None:
        assert index not in self.indices
        self.indices[index] = {"body": body, "docs": {}}

    def refresh(self, index: str) -> None:
        assert index in self.indices

    def exists_alias(self, name: str) -> bool:
        return bool(self.aliases.get(name))

    def get_alias(self, name: str) -> dict[str, Any]:
        return {i: {"aliases": {name: {}}} for i in sorted(self.aliases.get(name, set()))}

    def update_aliases(self, body: dict[str, Any]) -> None:
        self.alias_calls.append(body["actions"])  # one call == atomic in OpenSearch
        for a in body["actions"]:
            ((op, spec),) = a.items()
            s = self.aliases.setdefault(spec["alias"], set())
            (s.discard if op == "remove" else s.add)(spec["index"])


class FakeClient:
    def __init__(self) -> None:
        self.indices = FakeIndices()
        self.last_search: dict[str, Any] = {}

    def bulk(self, body: list[dict[str, Any]]) -> dict[str, Any]:
        for meta, doc in zip(body[::2], body[1::2], strict=True):
            spec = meta["index"]
            self.indices.indices[spec["_index"]]["docs"][spec["_id"]] = doc
        return {"errors": False}

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.last_search = {"index": index, "body": body}
        return {"hits": {"hits": []}}


def _chunks(n: int, jur: str = "FR") -> list[dict[str, Any]]:
    return [
        {
            "id": f"c{i}",
            "article_key": f"{jur}:X:{i}",
            "article_number": str(i),
            "citation_id": f"[{jur}:X art. {i}]",
            "jurisdiction": jur,
            "language": "fr",
            "doc_type": "code",
            "license": "lic",
            "chunk_path": f"Art {i}",
            "text": f"texte {i}",
            "valid_from": date(2016, 7, 1),
            "valid_to": None,
            "doc_version_id": "v1",
            "chunker_version": "article-v1",
        }
        for i in range(n)
    ]


@pytest.fixture
def mgr(tmp_path: Path) -> IndexManager:
    return IndexManager(FakeClient(), LineageStore.from_url(f"sqlite:///{tmp_path / 'db.sqlite'}"))


def test_build_promote_rollback(mgr: IndexManager) -> None:
    chunks = _chunks(3)
    vec = {"e5": np.ones((3, 4), dtype=np.float32)}
    first = mgr.build("FR", chunks, vec, {"e5": "m"})
    assert first.startswith("legal-fr-") and mgr.current("FR") is None  # built != live
    assert mgr.promote("FR", first) is None
    assert mgr.current("FR") == first

    import time

    time.sleep(1.1)  # index names carry a second-resolution timestamp
    second = mgr.build("FR", _chunks(4), {"e5": np.ones((4, 4), dtype=np.float32)}, {"e5": "m"})
    assert mgr.promote("FR", second) == first
    assert mgr.current("FR") == second
    swap = mgr.client.indices.alias_calls[-1]
    assert {next(iter(a)) for a in swap} == {"remove", "add"}  # one atomic call, never an empty alias

    assert mgr.rollback("FR") == first
    assert mgr.current("FR") == first
    status = {r["run_id"]: r["status"] for r in mgr.store.index_runs("FR")}
    assert status == {first: "promoted", second: "rolled_back"}


def test_rollback_without_history_fails(mgr: IndexManager) -> None:
    idx = mgr.build("FR", _chunks(1), {"e5": np.ones((1, 4), dtype=np.float32)}, {"e5": "m"})
    mgr.promote("FR", idx)
    with pytest.raises(RuntimeError):
        mgr.rollback("FR")


def test_build_rejects_misaligned_vectors(mgr: IndexManager) -> None:
    with pytest.raises(ValueError):
        mgr.build("FR", _chunks(2), {"e5": np.ones((3, 4), dtype=np.float32)}, {"e5": "m"})


def test_mapping_has_language_analyzers_and_vectors() -> None:
    body = index_body({"e5": 768, "titan": 1024})
    props = body["mappings"]["properties"]
    assert set(props["text"]["fields"]) == {"fr", "en", "de"}
    assert props["vec_e5"]["dimension"] == 768 and props["vec_titan"]["dimension"] == 1024
    assert body["mappings"]["dynamic"] == "strict"


def test_backend_targets_only_entitled_aliases_and_filters() -> None:
    client = FakeClient()
    be = OpenSearchBackend(client)
    be.bm25("délai", Filters(("EU", "FR"), as_of=date(2025, 1, 1)), 10, {"L221-18"})
    assert client.last_search["index"] == f"{alias_name('EU')},{alias_name('FR')}"
    q = client.last_search["body"]["query"]["bool"]
    assert {"terms": {"jurisdiction": ["EU", "FR"]}} in q["filter"]
    assert q["should"][0]["terms"]["article_number"] == ["L221-18"]
    be.dense([0.1, 0.2], "vec_e5", Filters(("DE",)), 5)
    knn = client.last_search["body"]["query"]["knn"]["vec_e5"]
    assert knn["k"] == 5 and client.last_search["index"] == alias_name("DE")
    assert knn["filter"]["bool"]["filter"][0] == {"terms": {"jurisdiction": ["DE"]}}
