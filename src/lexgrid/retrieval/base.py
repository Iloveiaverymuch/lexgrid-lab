"""Retrieval contracts shared by every backend and by the REST/MCP layer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal, Protocol

from lexgrid.normalize import canonical_article_number

Mode = Literal["bm25", "dense", "hybrid_rrf", "hybrid_rrf_rerank"]
MODES: tuple[Mode, ...] = ("bm25", "dense", "hybrid_rrf", "hybrid_rrf_rerank")


@dataclass(frozen=True)
class Filters:
    """`jurisdictions` comes from the caller's entitlements (server-side), never from a model."""

    jurisdictions: tuple[str, ...]
    languages: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    as_of: date | None = None

    def __post_init__(self) -> None:
        if not self.jurisdictions:
            raise ValueError("at least one entitled jurisdiction is required")


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    article_key: str
    article_number: str
    citation_id: str
    jurisdiction: str
    language: str
    chunk_path: str
    text: str
    score: float
    valid_from: date | None = None
    valid_to: date | None = None
    debug: dict[str, float] = field(default_factory=dict, compare=False)

    def with_score(self, score: float, **debug: float) -> Hit:
        return replace(self, score=score, debug={**self.debug, **debug})


def in_force(valid_from: date | None, valid_to: date | None, as_of: date) -> bool:
    return (valid_from is None or valid_from <= as_of) and (valid_to is None or valid_to > as_of)


def rrf(rankings: list[list[Hit]], k: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion on chunk ids. Scores are only comparable within one fused list."""
    scores: dict[str, float] = {}
    first: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            first.setdefault(hit.chunk_id, hit)
    fused = [first[cid].with_score(s, rrf=s) for cid, s in scores.items()]
    return sorted(fused, key=lambda h: (-h.score, h.chunk_id))


def collapse_by_article(hits: list[Hit]) -> list[Hit]:
    """Keep the best hit per article (parts of a long article, same EU article in another language)."""
    seen: set[str] = set()
    out: list[Hit] = []
    for h in hits:
        if h.article_key not in seen:
            seen.add(h.article_key)
            out.append(h)
    return out


_REF = re.compile(
    r"(?:\b(?:articles?|art\.?|artikel)\s*([LRD]\.?\s?\d+(?:-\d+)*|\d+\s?[a-z]?\b|premier\b)|§+\s*(\d+\s?[a-z]?\b))",
    re.IGNORECASE,
)


def article_refs(query: str) -> set[str]:
    """Explicit references in a query ('article L. 221-18', 'Art. 17', '§ 355') as canonical numbers."""
    refs: set[str] = set()
    for m in _REF.finditer(query):
        raw = m.group(1) or m.group(2)
        try:
            refs.add(canonical_article_number(raw))
        except ValueError:
            continue
    return refs


class Backend(Protocol):
    """A physical index. Implementations: MemoryBackend (offline/CI), OpenSearchBackend (live)."""

    def bm25(self, query: str, filters: Filters, k: int, refs: set[str]) -> list[Hit]: ...

    def dense(self, vector: list[float], field_name: str, filters: Filters, k: int) -> list[Hit]: ...
