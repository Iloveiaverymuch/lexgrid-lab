"""RetrievalService: one entry point, four modes. REST, MCP and the eval runner all call this."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from lexgrid.embed import Embedder
from lexgrid.retrieval.base import Backend, Filters, Hit, Mode, article_refs, collapse_by_article, rrf
from lexgrid.retrieval.rerank import Reranker, rerank


@dataclass
class SearchResult:
    hits: list[Hit]
    mode: Mode
    timings_ms: dict[str, float] = field(default_factory=dict)


def pin_refs(ranked: list[Hit], refs: set[str]) -> list[Hit]:
    """Explicitly referenced articles first (stable: keeps their relative order), then the rest."""
    wanted = {r.lower() for r in refs}
    pinned = [h.with_score(h.score, pinned=1.0) for h in ranked if h.article_number.lower() in wanted]
    return pinned + [h for h in ranked if h.article_number.lower() not in wanted]


def diversify(per_jurisdiction: list[list[Hit]]) -> list[Hit]:
    """Merge per-jurisdiction rankings so every jurisdiction with a result is represented at the top.

    Order: articles the user named (pinned) → the best article of each jurisdiction, by score → everything
    else by score. Each input list is already ranked and collapsed per article. Scores are comparable across
    lists because every list was scored by the same method (same reranker, same RRF constant, same embedder).
    """
    pinned = sorted((h for lst in per_jurisdiction for h in lst if h.debug.get("pinned")), key=lambda h: -h.score)
    taken = {h.chunk_id for h in pinned}
    heads = []
    for lst in per_jurisdiction:
        best = next((h for h in lst if h.chunk_id not in taken), None)
        if best is not None and not any(p.jurisdiction == best.jurisdiction for p in pinned):
            heads.append(best)
    heads.sort(key=lambda h: (-h.score, h.chunk_id))
    taken |= {h.chunk_id for h in heads}
    rest = sorted(
        (h for lst in per_jurisdiction for h in lst if h.chunk_id not in taken), key=lambda h: (-h.score, h.chunk_id)
    )
    return pinned + heads + rest


class RetrievalService:
    def __init__(
        self,
        backend: Backend,
        embedder: Embedder,
        reranker: Reranker | None = None,
        *,
        candidates: int = 50,
        rerank_top: int = 30,
        rrf_k: int = 60,
        diversify_jurisdictions: bool = True,
    ) -> None:
        self.backend = backend
        self.embedder = embedder
        self.reranker = reranker
        self.candidates = candidates
        self.rerank_top = rerank_top
        self.rrf_k = rrf_k
        self.diversify_jurisdictions = diversify_jurisdictions

    @property
    def vector_field(self) -> str:
        return f"vec_{self.embedder.name}"

    def search(self, query: str, filters: Filters, *, k: int = 10, mode: Mode = "hybrid_rrf") -> SearchResult:
        t: dict[str, float] = {}
        refs = article_refs(query)
        vec: list[float] | None = None
        if mode != "bm25":
            s = time.perf_counter()
            vec = [float(x) for x in self.embedder.embed([query], "query")[0]]  # once, reused per jurisdiction
            t["embed_query"] = (time.perf_counter() - s) * 1000

        if self.diversify_jurisdictions and len(filters.jurisdictions) > 1:
            # One ranking per jurisdiction: a country whose texts score lower overall (e.g. an English query
            # against French and German law) still gets candidates, a rerank budget and a top slot.
            budget = max(10, self.rerank_top // len(filters.jurisdictions))
            per = [
                collapse_by_article(
                    self._rank(query, replace(filters, jurisdictions=(j,)), mode, refs, vec, t, rerank_top=budget)
                )
                for j in filters.jurisdictions
            ]
            hits = diversify(per)[:k]
        else:
            hits = collapse_by_article(self._rank(query, filters, mode, refs, vec, t, rerank_top=self.rerank_top))[:k]
        t["total"] = sum(v for key, v in t.items() if key != "total")
        return SearchResult(hits=hits, mode=mode, timings_ms=t)

    def _rank(
        self,
        query: str,
        filters: Filters,
        mode: Mode,
        refs: set[str],
        vec: list[float] | None,
        t: dict[str, float],
        *,
        rerank_top: int,
    ) -> list[Hit]:
        def clock(name: str, started: float) -> None:
            t[name] = t.get(name, 0.0) + (time.perf_counter() - started) * 1000

        lexical: list[Hit] = []
        semantic: list[Hit] = []
        if mode in ("bm25", "hybrid_rrf", "hybrid_rrf_rerank"):
            s = time.perf_counter()
            # Canonical forms ('L221-18') are what the index contains; users type 'L. 221-18'.
            lexical_query = f"{query} {' '.join(sorted(refs))}" if refs else query
            lexical = self.backend.bm25(lexical_query, filters, self.candidates, refs)
            clock("bm25", s)
        if mode in ("dense", "hybrid_rrf", "hybrid_rrf_rerank"):
            assert vec is not None
            s = time.perf_counter()
            semantic = self.backend.dense(vec, self.vector_field, filters, self.candidates)
            clock("dense", s)

        if mode == "bm25":
            ranked = lexical
        elif mode == "dense":
            ranked = semantic
        else:
            ranked = rrf([lexical, semantic], k=self.rrf_k)
            if mode == "hybrid_rrf_rerank":
                if self.reranker is None:
                    raise ValueError("mode hybrid_rrf_rerank needs a reranker")
                s = time.perf_counter()
                head = rerank(self.reranker, query, ranked[:rerank_top])
                ranked = head + ranked[rerank_top:]
                clock("rerank", s)

        if refs and mode != "dense":
            ranked = pin_refs(ranked, refs)
        return ranked
