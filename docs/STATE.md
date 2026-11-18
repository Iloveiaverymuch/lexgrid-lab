# STATE

Status: ACTIVE · Last updated: 2026-11-18 · Next action: Day 2 retrieval (needs Docker + AWS on the Mac)

**Current:** Day 1 DONE (data plane). Day 2 next. See [LAB_PLAN.md](LAB_PLAN.md).

## Next 3 actions
1. Embedder interface: fake (offline), local multilingual-e5, Bedrock Titan V2.
2. Versioned OpenSearch index per jurisdiction + alias swap + rollback; offline BM25 for verify.
3. Retriever (4 modes) + golden set (30 q, graded qrels) + eval runner with CIs.

## Blockers
- Agent environments cannot reach Hugging Face or AWS: model downloads and Bedrock calls run on the Mac.
- Bedrock Rerank blocked by Free-plan SCP (backlog #7): rerank = local cross-encoder only.
- No Docker in the agent shell: OpenSearch/Postgres integration runs on the Mac only.

## Last 3 decisions
- AWS: Free plan, profile `lexgrid` (IAM user `lexgrid-lab`, eu-central-1); Titan V2 embeddings verified; no upgrade for now.
- 3-day scope: Go, Kafka, Airflow, Redis, K8S, PDF/email moved to roadmap (LAB_PLAN §Cut).
- Germany (BGB XML) as 3rd jurisdiction; consumer-contract law as the common topic.

## Verified numbers
- Corpus: 3,253 chunks, 8 doc versions, 4 sources; re-run no-op ([FINDINGS](../evals/FINDINGS.md) D1-INGEST-03/04).
