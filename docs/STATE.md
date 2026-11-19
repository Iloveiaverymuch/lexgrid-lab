# STATE

Status: ACTIVE · Last updated: 2026-11-19 · Next action: push, enable branch protection on the 3 CI checks, send to recruiter

**Current:** 3-day lab DONE + promptfoo (contract 10/10 in CI, quality suite generated from golden set), ADR-003, ROADMAP. Best: bge-m3 hybrid+rerank nDCG@10 0.860 [0.79, 0.93] (D4-EVAL-DIVERSIFY-01).

## Next 3 actions
1. Push; require checks `verify`, `retrieval-gate`, `api-contract` on main.
2. Run the promptfoo quality suite on the Mac (real models) and record it in FINDINGS.
3. ROADMAP phase 1: Riadh reviews golden labels (q23, q24 first), language-aware fusion, credibility floor.

## Blockers
- Agent environments cannot reach Hugging Face or AWS: model downloads and Bedrock calls run on the Mac.
- Bedrock blocked: Rerank by SCP (#7), Titan InvokeModel since 2026-11-18 (#8). Phase 4 needs a paid plan.
- No Docker in the agent shell: OpenSearch/Postgres integration runs on the Mac only.

## Last 3 decisions
- ADR-003: Python runner for metrics/gate, promptfoo for behaviour tests over HTTP (contract in CI, quality on Mac).
- Per-jurisdiction retrieval + diversification is the default (R11); side effect kept visible (backlog #9).
- AWS tracing deferred to ROADMAP phase 3 (OTel → Jaeger / X-Ray).

## Verified numbers
- Corpus: 3,224 live chunks, 4 sources, parser 1.1.0; re-run no-op ([FINDINGS](../evals/FINDINGS.md) D2-INGEST-05).
- Retrieval (30 q): BM25 0.571 → bge-m3 hybrid+rerank 0.860 nDCG@10 (D4-EVAL-DIVERSIFY-01).
- Gate: same corpus promoted (diff +0.000), 30% chunk loss rejected (−0.159) (D3-GATE-01/02).
- Isolation: leak rate 0 over 4,516 hits (D3-LEAK-01); API contract 10/10 (D4-PF-CONTRACT-01).
