"""Golden-set loader and eval runner. Results go to evals/results/<run_id>.json; FINDINGS rows on request."""

from __future__ import annotations

import json
import platform
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

from lexgrid.evals.metrics import per_query
from lexgrid.evals.stats import bootstrap_ci, mcnemar_exact, paired_bootstrap
from lexgrid.retrieval.base import Filters, Mode
from lexgrid.retrieval.service import RetrievalService

QueryType = Literal["exact_ref", "paraphrase", "cross_lingual", "multi_jurisdiction", "as_of", "no_answer"]


class GoldenQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    query: str
    language: Literal["fr", "en", "de"]
    scope: list[Literal["EU", "FR", "DE"]] = Field(min_length=1)
    type: QueryType
    as_of: date | None = None
    qrels: dict[str, int] = Field(default_factory=dict)
    note: str | None = None


def load_golden(path: Path) -> list[GoldenQuery]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    qs = [GoldenQuery.model_validate(x) for x in data["queries"]]
    ids = [q.id for q in qs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate golden query ids")
    for q in qs:
        if q.type == "no_answer" and q.qrels:
            raise ValueError(f"{q.id}: no_answer queries must have empty qrels")
        if q.type != "no_answer" and not any(g == 2 for g in q.qrels.values()):
            raise ValueError(f"{q.id}: needs at least one grade-2 article")
        bad = [k for k in q.qrels if k.split(":", 1)[0] not in q.scope]
        if bad:
            raise ValueError(f"{q.id}: qrels outside the query scope: {bad}")
    return qs


@dataclass
class ModeResult:
    mode: Mode
    per_query: dict[str, dict[str, float]]
    ranked: dict[str, list[str]]
    top_scores: dict[str, float]
    latency_ms: list[float]


def _git_sha() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout
        return f"{sha}-dirty" if dirty.strip() else sha  # results from uncommitted code are flagged
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run_mode(
    service: RetrievalService, queries: Sequence[GoldenQuery], mode: Mode, k: int = 10
) -> ModeResult:
    pq: dict[str, dict[str, float]] = {}
    ranked: dict[str, list[str]] = {}
    top: dict[str, float] = {}
    lat: list[float] = []
    for q in queries:
        res = service.search(q.query, Filters(jurisdictions=tuple(q.scope), as_of=q.as_of), k=k, mode=mode)
        keys = [h.article_key for h in res.hits]
        ranked[q.id] = keys
        top[q.id] = res.hits[0].score if res.hits else float("-inf")
        lat.append(res.timings_ms.get("total", 0.0))
        if q.type != "no_answer":
            pq[q.id] = per_query(keys, q.qrels)
    return ModeResult(mode, pq, ranked, top, lat)


def summarize(
    results: Sequence[ModeResult], queries: Sequence[GoldenQuery], baseline: Mode | None = None
) -> dict[str, Any]:
    answerable = [q for q in queries if q.type != "no_answer"]
    summary: dict[str, Any] = {
        "n_queries": len(answerable),
        "n_no_answer": len(queries) - len(answerable),
        "modes": {},
    }
    for r in results:
        metrics = sorted(next(iter(r.per_query.values())).keys()) if r.per_query else []
        m: dict[str, Any] = {}
        for name in metrics:
            vals = [r.per_query[q.id][name] for q in answerable]
            mean, lo, hi = bootstrap_ci(vals)
            m[name] = {"mean": mean, "ci_low": lo, "ci_high": hi}
        by_type: dict[str, dict[str, float]] = {}
        for t in sorted({q.type for q in answerable}):
            ids = [q.id for q in answerable if q.type == t]
            by_type[t] = {
                "n": len(ids),
                "ndcg@10": float(np.mean([r.per_query[i]["ndcg@10"] for i in ids])),
                "hit@5": float(np.mean([r.per_query[i]["hit@5"] for i in ids])),
            }
        lat = np.asarray(r.latency_ms)
        summary["modes"][r.mode] = {
            "metrics": m,
            "by_type": by_type,
            "latency_ms": {"p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95))},
        }
    if baseline and any(r.mode == baseline for r in results):
        base = next(r for r in results if r.mode == baseline)
        comps: dict[str, Any] = {}
        for r in results:
            if r.mode == baseline:
                continue
            ids = [q.id for q in answerable]
            comps[f"{r.mode}_vs_{baseline}"] = {
                "ndcg@10_paired_bootstrap": paired_bootstrap(
                    [base.per_query[i]["ndcg@10"] for i in ids], [r.per_query[i]["ndcg@10"] for i in ids]
                ),
                "hit@5_mcnemar": mcnemar_exact(
                    [base.per_query[i]["hit@5"] for i in ids], [r.per_query[i]["hit@5"] for i in ids]
                ),
            }
        summary["comparisons"] = comps
    return summary


def write_results(
    out_dir: Path,
    run_id: str,
    config: dict[str, Any],
    results: Sequence[ModeResult],
    summary: dict[str, Any],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "created_at": datetime.now(tz=UTC).isoformat(),
        "git_sha": _git_sha(),
        "host": platform.platform(),
        "config": config,
        "summary": summary,
        "per_query": {
            r.mode: {"metrics": r.per_query, "ranked": r.ranked, "top_score": r.top_scores} for r in results
        },
    }
    path = out_dir / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return path


def markdown_table(summary: dict[str, Any]) -> str:
    cols = ["ndcg@10", "mrr@10", "recall@10", "precision@5", "hit@5"]
    lines = ["| mode | " + " | ".join(cols) + " | p50 ms | p95 ms |", "|---" * (len(cols) + 3) + "|"]
    for mode, d in summary["modes"].items():
        cells = []
        for c in cols:
            v = d["metrics"][c]
            cells.append(f"{v['mean']:.3f} [{v['ci_low']:.2f}, {v['ci_high']:.2f}]")
        lat = d["latency_ms"]
        lines.append(f"| {mode} | " + " | ".join(cells) + f" | {lat['p50']:.0f} | {lat['p95']:.0f} |")
    return "\n".join(lines)


def findings_row(run_id: str, config_text: str, summary: dict[str, Any], conclusion: str) -> str:
    parts = []
    for mode, d in summary["modes"].items():
        n = d["metrics"]["ndcg@10"]
        parts.append(f"{mode}: nDCG@10 {n['mean']:.3f} [{n['ci_low']:.2f}, {n['ci_high']:.2f}]")
    n_q = summary["n_queries"]
    today = datetime.now(tz=UTC).date().isoformat()
    return f"| {today} | {run_id} | {config_text} | {'; '.join(parts)} | {n_q} q | {conclusion} |\n"
