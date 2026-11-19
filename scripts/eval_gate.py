"""Offline retrieval regression gate (CI).

Compares an offline eval run (in-memory BM25 + hash embedder + overlap reranker, real corpus, golden set) with a
committed baseline. This is a deterministic proxy for ranking *logic* (tokenisation, BM25, reference pinning,
fusion, collapse, diversification, filters), not for semantic quality, which needs the real models (Tier 2).

  python scripts/eval_gate.py --results /tmp/ci/CI-OFFLINE.json            # gate
  python scripts/eval_gate.py --results /tmp/ci/CI-OFFLINE.json --update   # accept new numbers (review the diff)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "evals" / "baselines" / "offline-memory-hash.json"
EXACT_REF = ["q01", "q02", "q03", "q04", "q05", "q06"]


def extract(run: dict) -> dict:
    out = {"modes": {}, "exact_ref_hit1": {}}
    for mode, d in run["summary"]["modes"].items():
        out["modes"][mode] = round(d["metrics"]["ndcg@10"]["mean"], 4)
        if mode != "dense":
            m = run["per_query"][mode]["metrics"]
            out["exact_ref_hit1"][mode] = sum(m[q]["hit@1"] for q in EXACT_REF) / len(EXACT_REF)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--baseline", default=str(BASELINE))
    ap.add_argument("--tolerance", type=float, default=0.01)
    ap.add_argument("--update", action="store_true")
    args = ap.parse_args()

    current = extract(json.loads(Path(args.results).read_text(encoding="utf-8")))
    if args.update:
        Path(args.baseline).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(f"baseline updated: {args.baseline}")
        return 0
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))

    failures: list[str] = []
    header = "| mode | baseline nDCG@10 | now | diff | status |"
    lines = ["### Offline retrieval gate", "", header, "|---|---|---|---|---|"]
    for mode, b in base["modes"].items():
        now = current["modes"].get(mode)
        if now is None:
            failures.append(f"{mode}: missing")
            continue
        diff = now - b
        ok = diff >= -args.tolerance
        lines.append(f"| {mode} | {b:.4f} | {now:.4f} | {diff:+.4f} | {'ok' if ok else 'REGRESSION'} |")
        if not ok:
            failures.append(f"{mode}: nDCG@10 {now:.4f} < baseline {b:.4f} - {args.tolerance}")
    for mode, hit in current["exact_ref_hit1"].items():
        if hit < 1.0:
            failures.append(f"{mode}: exact references not all at rank 1 ({hit:.2f})")
    lines += ["", f"Exact article references at rank 1: {current['exact_ref_hit1']}", ""]
    verdict = "**FAILED:** " + "; ".join(failures) if failures else f"**PASSED** (tolerance {args.tolerance})"
    lines.append(verdict)
    report = "\n".join(lines)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
