"""In-memory backend: BM25 (Okapi, k1=1.2, b=0.75) + exact cosine. Used by the offline gate and tests.

It has no stemming or language analyzers, so it is a weaker lexical baseline than OpenSearch:
never compare its numbers with OpenSearch numbers as if they were the same system.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

import numpy as np

from lexgrid.embed import Matrix, tokens
from lexgrid.retrieval.base import Filters, Hit, in_force

EXACT_REF_BOOST = 5.0


def _hit(c: Mapping[str, Any], score: float) -> Hit:
    return Hit(
        chunk_id=c["id"],
        article_key=c["article_key"],
        article_number=c["article_number"],
        citation_id=c["citation_id"],
        jurisdiction=c["jurisdiction"],
        language=c["language"],
        chunk_path=c["chunk_path"],
        text=c["text"],
        score=score,
        valid_from=c.get("valid_from"),
        valid_to=c.get("valid_to"),
    )


class MemoryBackend:
    def __init__(
        self,
        chunks: Iterable[Mapping[str, Any]],
        vectors: Mapping[str, Matrix] | None = None,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        self.chunks = list(chunks)
        self.vectors = dict(vectors or {})  # field name -> (n_chunks, dim), rows aligned with self.chunks
        self.k1, self.b = k1, b
        self._tf = [Counter(tokens(c["text"])) for c in self.chunks]
        self._len = np.array([sum(tf.values()) for tf in self._tf], dtype=np.float64)
        self._avg = float(self._len.mean()) if len(self._len) else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self.chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def _allowed(self, i: int, f: Filters) -> bool:
        c = self.chunks[i]
        if c["jurisdiction"] not in f.jurisdictions:
            return False
        if f.languages and c["language"] not in f.languages:
            return False
        if f.doc_types and c.get("doc_type") not in f.doc_types:
            return False
        if f.as_of is not None:
            vf: date | None = c.get("valid_from")
            vt: date | None = c.get("valid_to")
            if not in_force(vf, vt, f.as_of):
                return False
        return True

    def bm25(self, query: str, filters: Filters, k: int, refs: set[str]) -> list[Hit]:
        q = tokens(query)
        scored: list[tuple[float, int]] = []
        for i, tf in enumerate(self._tf):
            if not self._allowed(i, filters):
                continue
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * self._len[i] / (self._avg or 1.0))
            for t in q:
                f = tf.get(t)
                if f:
                    s += self._idf[t] * f * (self.k1 + 1) / (f + norm)
            if refs and self.chunks[i]["article_number"] in refs:
                s += EXACT_REF_BOOST
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda x: (-x[0], self.chunks[x[1]]["id"]))
        return [_hit(self.chunks[i], s) for s, i in scored[:k]]

    def dense(self, vector: list[float], field_name: str, filters: Filters, k: int) -> list[Hit]:
        mat = self.vectors.get(field_name)
        if mat is None:
            raise KeyError(f"no vectors for field {field_name!r}")
        sims = mat @ np.asarray(vector, dtype=np.float32)
        order = np.argsort(-sims)
        out: list[Hit] = []
        for i in order:
            if self._allowed(int(i), filters):
                out.append(_hit(self.chunks[int(i)], float(sims[i])))
                if len(out) == k:
                    break
        return out
