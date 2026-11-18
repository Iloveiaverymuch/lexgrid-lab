# Reliability backlog

Status: ACTIVE · Last updated: 2026-11-18 · Next action: review at end of Day 3

| # | Gap | Impact | Remediation | Lab vs prod |
|---|---|---|---|---|
| 1 | Validity dates are per source (default), not per article, for EU and DE | "As of date" queries are coarse | Use EUR-Lex consolidated versions and gii `standangabe`; LEGI bulk dump has per-article `date_debut/date_fin` | Prod must have per-article dates |
| 2 | Légifrance input is a page capture, parsed from text lines | Breaks if markup or labels change | Switch to the DILA LEGI bulk XML | Prod: bulk XML only |
| 3 | Recitals and annexes are not ingested | Questions answered by recitals/annexes miss | Separate chunk types with their own `doc_type` | |
| 4 | Token counts are estimates (words × 1.3) | Chunk budget approximate per model | Use the embedding model's tokenizer | |
| 5 | Near-duplicate detection (MinHash) not implemented; only exact hashes | Consolidated versions can produce near-identical chunks | MinHash at ingest + collapse at retrieval | |
| 6 | Licenses copied from public notices, not legally reviewed | Redistribution risk | Legal review before publishing fixtures | |
| 7 | Bedrock Rerank (Amazon + Cohere) denied by the Free-plan service control policy (`bedrock:Rerank` explicit deny); Cohere InvokeModel also refused | No managed-reranker comparison | Upgrade the account to the Paid plan (one-way; credits carry over), then rerun the rerank benchmark | Lab constraint only |
| 8 | Bedrock InvokeModel (Titan V2) refused with `Operation not allowed` after one successful call on 2026-11-18 (same identity, region, body); account-level restriction (Free plan / new-account verification) | No managed-embedding benchmark | Check the Bedrock console banner and Service Quotas; upgrade to Paid or open a support case; then `embed --model titan` and rebuild indexes as a new version | Lab constraint only |
