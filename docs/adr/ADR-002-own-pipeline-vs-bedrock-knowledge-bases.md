# ADR-002 — Own ingestion/indexing pipeline instead of Amazon Bedrock Knowledge Bases

Status: ACCEPTED · Date: 2026-11-19 · Last updated: 2026-11-19 · Next action: benchmark a KB on a subset if the account moves to a paid plan

## Context
Bedrock Knowledge Bases (KB) offer managed ingestion, chunking, embedding and sync into a vector store.
The target role owns the "raw material" of the AI: parsing, chunking, index versioning, lineage, freshness,
per-country partitioning and continuous evaluation. The question is which of those a managed KB covers well enough.

## Decision
Own the pipeline (lexgrid), keep KB as the managed alternative to benchmark later. KB was not benchmarked:
Bedrock calls are blocked on this account's Free plan (ADR-001, backlog #7–#8).

## Why (requirements a legal corpus imposes)
| Requirement | lexgrid (measured or tested) | What KB would need |
|---|---|---|
| Article-aware chunks with the article number in the indexed text | R1, exact-ref hit@1 6/6 offline | Custom chunking via a transformation function; to verify |
| Index versioning, gated promotion, instant rollback | `index release` gate + alias swap, tested | Re-sync of a data source; no built-in A/B gate in our design |
| Lineage chunk → raw bytes → parser version | `GET /lineage/{id}`, tested | Source metadata per document; parser version is ours anyway |
| Per-country isolation enforced by index and filter | Leak rate 0 (D3-LEAK-01) | Metadata filters or one KB per country |
| Temporal validity (as-of) | `valid_from/valid_to` filter, tested | Metadata filtering; validity extraction is still ours |
| Quarantine of instruction-like text before indexing | D3-SCREEN-01 | Our screening step before upload |

## Consequences
- We operate OpenSearch, Postgres and model versions ourselves (more ops, full control).
- Every behaviour above has a test or a FINDINGS row; a KB benchmark would reuse the same golden set and gate.
