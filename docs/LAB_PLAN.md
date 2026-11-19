# LAB_PLAN — 3-day build

Status: ACTIVE · Last updated: 2026-11-18 · Next action: demo rehearsal, label review

Goal: measured evidence for an Expert Data & Retrieval role: ingestion → versioned hybrid index →
retrieval evaluation → thin cited Q&A. Everything else is a written roadmap.

| Day | Deliverable | Acceptance (test or results file) | Status |
|---|---|---|---|
| 1 | Scaffold, verify, CI, Compose; registry + fixtures; 3 parsers; normalization; article chunking; lineage store | Re-run is a no-op; dry-run has no side effects; parser contract tests on real captures; chunk stats in FINDINGS | DONE |
| 2 | Embedders (local multilingual + Bedrock Titan V2), versioned OpenSearch index per jurisdiction, alias swap + rollback; 4 retrieval modes; golden set (30 q, graded qrels) | Metrics table with CIs per mode in FINDINGS; rollback test | DONE |
| 3 | Promotion gate; `/search`, `/ask`, `/lineage` (FastAPI); read-only MCP; leak + poisoned-chunk tests; README, 2 ADRs, demo script | Leak rate = 0; citation check; docs check green | DONE |

## Cut (roadmap, explained in README, not built)
Go fetcher · Kafka/Redpanda · Airflow · Redis cache · K8S · PDF + HITL email · Guardrails · OTel dashboards ·
scale test · Bedrock Knowledge Bases baseline · pgvector baseline · judge calibration (kappa).

## Budget
AWS < $10 planned, $20 Budgets alarm. Only Day 2 embedding/rerank runs and Day 3 `/ask` eval call Bedrock.
