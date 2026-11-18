"""Ranking metrics over article keys (after collapsing chunks to articles).

Definitions (fixed so numbers are comparable across runs):
- qrels grades: 2 = answers the question, 1 = related/useful, 0 = not relevant (absent == 0).
- "relevant" = grade >= 1 for recall, precision, hit, MRR.
- nDCG uses graded gain 2^g - 1 and log2 discount; ideal ranking from the qrels.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def _rel(qrels: Mapping[str, int], key: str) -> int:
    return int(qrels.get(key, 0))


def recall_at(ranked: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    relevant = {a for a, g in qrels.items() if g >= 1}
    if not relevant:
        return 0.0
    return len(relevant & set(ranked[:k])) / len(relevant)


def precision_at(ranked: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    return sum(1 for a in ranked[:k] if _rel(qrels, a) >= 1) / k


def hit_at(ranked: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    return 1.0 if any(_rel(qrels, a) >= 1 for a in ranked[:k]) else 0.0


def mrr(ranked: Sequence[str], qrels: Mapping[str, int], k: int = 10) -> float:
    for i, a in enumerate(ranked[:k], start=1):
        if _rel(qrels, a) >= 1:
            return 1.0 / i
    return 0.0


def ndcg_at(ranked: Sequence[str], qrels: Mapping[str, int], k: int = 10) -> float:
    def dcg(grades: Sequence[int]) -> float:
        return float(sum((2 ** int(g) - 1) / math.log2(i + 2) for i, g in enumerate(grades[:k])))

    ideal = dcg(sorted(qrels.values(), reverse=True))
    if ideal == 0:
        return 0.0
    return dcg([_rel(qrels, a) for a in ranked]) / ideal


def per_query(ranked: Sequence[str], qrels: Mapping[str, int]) -> dict[str, float]:
    return {
        "recall@5": recall_at(ranked, qrels, 5),
        "recall@10": recall_at(ranked, qrels, 10),
        "precision@5": precision_at(ranked, qrels, 5),
        "hit@1": hit_at(ranked, qrels, 1),
        "hit@5": hit_at(ranked, qrels, 5),
        "mrr@10": mrr(ranked, qrels, 10),
        "ndcg@10": ndcg_at(ranked, qrels, 10),
    }
