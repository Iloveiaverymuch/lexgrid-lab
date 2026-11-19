# STATE

Status: ACTIVE · Last updated: 2026-11-18 · Next action: generate real screenshots, push, send to recruiter; then AWS tracing (approval needed)

**Current:** Day 3+ DONE: demo console, jurisdiction diversification (D4-CMP-01), CI retrieval gate. Best: bge-m3 hybrid+rerank nDCG@10 0.860 [0.79, 0.93] (D4-EVAL-DIVERSIFY-01).

## Next 3 actions
1. Rehearse docs/DEMO_15MIN.md with `lexgrid serve` live; commit Day 3.
2. Riadh reviews golden labels (q23, q24 first); rerun evals + sweep if labels change.
3. Next experiments: weighted RRF; rerank fewer candidates / smaller cross-encoder for latency.

## Blockers
- Agent environments cannot reach Hugging Face or AWS: model downloads and Bedrock calls run on the Mac.
- Bedrock blocked: Rerank by SCP (#7), Titan InvokeModel since 2026-11-18 (#8). Embedding benchmark = e5 vs bge-m3 (local).
- No Docker in the agent shell: OpenSearch/Postgres integration runs on the Mac only.

## Last 3 decisions
- Per-jurisdiction retrieval + diversification is the default (R11); side effect kept visible (backlog #9).
- ADR-001: open-source models (bge-m3 + bge-reranker-v2-m3) because the Free plan blocks Bedrock and a paid plan is not justified.
- Golden v1 metrics are on agent-drafted labels until Riadh's review; rerun after any label change.

## Verified numbers
- Corpus: 3,224 live chunks, 4 sources, parser 1.1.0; re-run no-op ([FINDINGS](../evals/FINDINGS.md) D2-INGEST-05).
- Retrieval (30 q): BM25 0.557 → bge-m3 hybrid+rerank 0.843 nDCG@10 (D2-EVAL-BGEM3-01, D2-CMP-01).
- Gate: same corpus promoted (diff +0.000), 30% chunk loss rejected (−0.159) (D3-GATE-01/02).
- Isolation: leak rate 0 over 4,516 hits (D3-LEAK-01); screen: 0 false positives on 3,224 chunks (D3-SCREEN-01).
