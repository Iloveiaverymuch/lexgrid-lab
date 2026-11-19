"""Rerankers: a local cross-encoder (open source) and a deterministic fake for offline tests."""

from __future__ import annotations

from typing import Protocol

from lexgrid.embed import tokens
from lexgrid.retrieval.base import Hit


class Reranker(Protocol):
    name: str

    def score(self, query: str, texts: list[str]) -> list[float]: ...


class OverlapReranker:
    """Offline fake: fraction of query tokens present in the passage. Not a quality baseline."""

    name = "overlap"

    def score(self, query: str, texts: list[str]) -> list[float]:
        q = set(tokens(query))
        return [len(q & set(tokens(t))) / (len(q) or 1) for t in texts]


class CrossEncoderReranker:
    """Default BAAI/bge-reranker-v2-m3 (multilingual, Apache-2.0). Runs on Apple GPU (mps) when available."""

    def __init__(self, model_id: str = "BAAI/bge-reranker-v2-m3", name: str = "bge-m3", max_length: int = 512) -> None:
        import torch  # lazy
        from sentence_transformers import CrossEncoder

        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
        self.name = name
        self.model_id = model_id
        self._model = CrossEncoder(model_id, max_length=max_length, device=device)

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        out = self._model.predict([(query, t) for t in texts], batch_size=16, show_progress_bar=False)
        return [float(x) for x in out]


def rerank(reranker: Reranker, query: str, hits: list[Hit]) -> list[Hit]:
    scores = reranker.score(query, [h.text for h in hits])
    rescored = [h.with_score(s, rerank=s) for h, s in zip(hits, scores, strict=True)]
    return sorted(rescored, key=lambda h: (-h.score, h.chunk_id))


def build_reranker(name: str) -> Reranker:
    if name == "overlap":
        return OverlapReranker()
    if name == "bge-m3":
        return CrossEncoderReranker()
    if name == "mminilm":
        return CrossEncoderReranker("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", name="mminilm")
    raise ValueError(f"unknown reranker {name!r} (overlap | bge-m3 | mminilm)")
