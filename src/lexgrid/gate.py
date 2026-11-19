"""Index release with an evaluation gate.

release = build a candidate index for every jurisdiction → run the golden set against the candidates AND
against the live aliases (same code, same queries, paired) → promote all candidates atomically per alias,
or mark them `rejected` and leave the live aliases untouched.

Rule: promote if there is no live baseline, or mean nDCG@10(candidate) ≥ mean nDCG@10(live) − tolerance.
"""

from __future__ import annotations

import random
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from lexgrid.embed import Embedder
from lexgrid.evals.runner import GoldenQuery, run_mode
from lexgrid.evals.stats import bootstrap_ci, paired_bootstrap
from lexgrid.retrieval.base import Mode
from lexgrid.retrieval.opensearch import IndexManager, OpenSearchBackend
from lexgrid.retrieval.rerank import Reranker
from lexgrid.retrieval.service import RetrievalService
from lexgrid.store import LineageStore

GATE_METRIC = "ndcg@10"


@dataclass(frozen=True)
class GateDecision:
    promote: bool
    candidate: float
    baseline: float | None
    diff: float | None
    ci_low: float | None
    ci_high: float | None
    tolerance: float
    reason: str


def decide(candidate: Sequence[float], baseline: Sequence[float] | None, tolerance: float) -> GateDecision:
    cand = float(np.mean(candidate)) if len(candidate) else 0.0
    if baseline is None:
        return GateDecision(True, cand, None, None, None, None, tolerance, "no live baseline: first release")
    pb = paired_bootstrap(baseline, candidate)
    base = float(np.mean(baseline))
    ok = cand >= base - tolerance
    verdict = "within tolerance" if ok else "regression beyond tolerance"
    reason = f"{GATE_METRIC} {cand:.3f} vs live {base:.3f} (diff {pb['diff']:+.3f}, tolerance {tolerance}): {verdict}"
    return GateDecision(ok, cand, base, pb["diff"], pb["ci_low"], pb["ci_high"], tolerance, reason)


def release(
    *,
    client: Any,
    store: LineageStore,
    jurisdictions: Sequence[str],
    embedders: Sequence[Embedder],
    gate_embedder: Embedder,
    golden: Sequence[GoldenQuery],
    mode: Mode = "hybrid_rrf",
    reranker: Reranker | None = None,
    tolerance: float = 0.02,
    drop_fraction: float = 0.0,
    seed: int = 7,
) -> tuple[GateDecision, dict[str, str]]:
    """`drop_fraction` is fault injection for demos/tests: build candidates from a seeded random subset."""
    mgr = IndexManager(client, store)
    built: dict[str, str] = {}
    rng = random.Random(seed)
    for j in jurisdictions:
        chunks = store.live_chunks(j)
        if drop_fraction > 0:
            chunks = [c for c in chunks if rng.random() >= drop_fraction]
        texts = [c["text"] for c in chunks]
        vectors = {e.name: e.embed(texts, "passage") for e in embedders}
        built[j] = mgr.build(j, chunks, vectors, {e.name: e.model_id for e in embedders})

    answerable = [q for q in golden if q.type != "no_answer"]
    cand_svc = RetrievalService(OpenSearchBackend(client, overrides=built), gate_embedder, reranker)
    cand = run_mode(cand_svc, answerable, mode)
    live = all(mgr.current(j) for j in jurisdictions)
    base = (
        run_mode(RetrievalService(OpenSearchBackend(client), gate_embedder, reranker), answerable, mode)
        if live
        else None
    )

    ids = [q.id for q in answerable]
    cand_scores = [cand.per_query[i][GATE_METRIC] for i in ids]
    base_scores = [base.per_query[i][GATE_METRIC] for i in ids] if base else None
    decision = decide(cand_scores, base_scores, tolerance)

    eval_run_id = f"GATE-{time.strftime('%Y%m%d-%H%M%S')}"
    mean, lo, hi = bootstrap_ci(cand_scores)
    now = datetime.now(tz=UTC)
    store.add_eval_rows(
        [
            {
                "run_id": eval_run_id,
                "index_run_id": idx,
                "mode": f"{mode}:{gate_embedder.name}",
                "metric": GATE_METRIC,
                "k": 10,
                "value": mean,
                "ci_low": lo,
                "ci_high": hi,
                "n_queries": len(ids),
                "created_at": now,
            }
            for idx in built.values()
        ]
    )
    for j, idx in built.items():
        store.set_index_run_eval(idx, eval_run_id)
        if decision.promote:
            mgr.promote(j, idx)
        else:
            store.set_index_run_status(idx, "rejected")
    return decision, built
