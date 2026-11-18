# STATE

Status: ACTIVE · Last updated: 2026-11-18 · Next action: commit Day 2; Day 3 = promotion gate + API/MCP + safety tests

**Current:** Day 2 DONE. Best: bge-m3 hybrid+rerank nDCG@10 0.843 [0.76, 0.92] (FINDINGS D2-EVAL-BGEM3-01). See [LAB_PLAN.md](LAB_PLAN.md).

## Next 3 actions
1. Riadh reviews golden labels (q23, q24 first); rerun eval if labels change.
2. Day 3: promotion gate (refuse regressions) + FastAPI /search /ask /lineage + read-only MCP.
3. Day 3: leak + poisoned-chunk tests, README with results, demo script.

## Blockers
- Agent environments cannot reach Hugging Face or AWS: model downloads and Bedrock calls run on the Mac.
- Bedrock blocked: Rerank by SCP (#7), Titan InvokeModel since 2026-11-18 (#8). Embedding benchmark = e5 vs bge-m3 (local).
- No Docker in the agent shell: OpenSearch/Postgres integration runs on the Mac only.

## Last 3 decisions
- ADR-001: open-source models (bge-m3 + bge-reranker-v2-m3) because the Free plan blocks Bedrock and a paid plan is not justified.
- Golden v1 metrics are on agent-drafted labels until Riadh's review; rerun after any label change.
- 3-day scope: Go, Kafka, Airflow, Redis, K8S, PDF/email moved to roadmap (LAB_PLAN §Cut).

## Verified numbers
- Corpus: 3,224 live chunks, 4 sources, parser 1.1.0; re-run no-op ([FINDINGS](../evals/FINDINGS.md) D2-INGEST-05).
- Retrieval (30 q): BM25 0.557 → bge-m3 hybrid+rerank 0.843 nDCG@10 (D2-EVAL-BGEM3-01, D2-CMP-01).
