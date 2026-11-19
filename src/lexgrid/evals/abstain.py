"""No-answer threshold sweep on the top reranked score of an eval run.

For a threshold t the system abstains when top_score < t. We report, per t:
- no_answer_abstain: share of no-answer queries correctly abstained (want 1.0)
- answerable_answered: share of answerable queries still answered (want high)
- answered_hit1: among answered answerable queries, share whose rank-1 article is relevant
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SweepRow:
    threshold: float
    no_answer_abstain: float
    answerable_answered: float
    answered_hit1: float


def sweep(
    top_scores: Mapping[str, float],
    no_answer_ids: set[str],
    hit1: Mapping[str, float],
    thresholds: Sequence[float],
) -> list[SweepRow]:
    na = [q for q in top_scores if q in no_answer_ids]
    ans = [q for q in top_scores if q not in no_answer_ids]
    rows = []
    for t in thresholds:
        abstain_na = sum(1 for q in na if top_scores[q] < t) / (len(na) or 1)
        answered = [q for q in ans if top_scores[q] >= t]
        rows.append(
            SweepRow(
                threshold=t,
                no_answer_abstain=abstain_na,
                answerable_answered=len(answered) / (len(ans) or 1),
                answered_hit1=(sum(hit1[q] for q in answered) / len(answered)) if answered else 0.0,
            )
        )
    return rows


def choose(rows: Sequence[SweepRow], min_no_answer_abstain: float = 1.0) -> SweepRow:
    """Lowest threshold that abstains on all no-answer queries (keeps the most answers)."""
    ok = [r for r in rows if r.no_answer_abstain >= min_no_answer_abstain]
    if not ok:
        return max(rows, key=lambda r: (r.no_answer_abstain, r.answerable_answered))
    return min(ok, key=lambda r: r.threshold)
