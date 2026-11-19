"""RetrievalService: one entry point, four modes. REST, MCP and the eval runner all call this."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

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
    pinned = [h for h in ranked if h.article_number.lower() in {r.lower() for r in refs}]
    return pinned + [h for h in ranked if h not in pinned]


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
    ) -> None:
        self.backend = backend
        self.embedder = embedder
        self.reranker = reranker
        self.candidates = candidates
        self.rerank_top = rerank_top
        self.rrf_k = rrf_k

    @property
    def vector_field(self) -> str:
        return f"vec_{self.embedder.name}"

    def search(self, query: str, filters: Filters, *, k: int = 10, mode: Mode = "hybrid_rrf") -> SearchResult:
        t: dict[str, float] = {}
        refs = article_refs(query)
        lexical: list[Hit] = []
        semantic: list[Hit] = []

        if mode in ("bm25", "hybrid_rrf", "hybrid_rrf_rerank"):
            s = time.perf_counter()
            # Canonical forms ('L221-18') are what the index contains; users type 'L. 221-18'.
            lexical_query = f"{query} {' '.join(sorted(refs))}" if refs else query
            lexical = self.backend.bm25(lexical_query, filters, self.candidates, refs)
            t["bm25"] = (time.perf_counter() - s) * 1000
        if mode in ("dense", "hybrid_rrf", "hybrid_rrf_rerank"):
            s = time.perf_counter()
            vec = self.embedder.embed([query], "query")[0]
            t["embed_query"] = (time.perf_counter() - s) * 1000
            s = time.perf_counter()
            semantic = self.backend.dense([float(x) for x in vec], self.vector_field, filters, self.candidates)
            t["dense"] = (time.perf_counter() - s) * 1000

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
                head = rerank(self.reranker, query, ranked[: self.rerank_top])
                ranked = head + ranked[self.rerank_top :]
                t["rerank"] = (time.perf_counter() - s) * 1000

        if refs and mode != "dense":
            ranked = pin_refs(ranked, refs)
        hits = collapse_by_article(ranked)[:k]
        t["total"] = sum(t.values())
        return SearchResult(hits=hits, mode=mode, timings_ms=t)
