# Project handover

Status: ACTIVE · Last updated: 2026-11-19 · Next action: ROADMAP phase 1 (label review, language-aware fusion)

## What exists
| Area | Where | State |
|---|---|---|
| Source registry + pinned fixtures (EU GDPR/CRD fr/en/de, FR C. conso L221, DE BGB) | `data/` | Done, checksummed, CRLF-safe in git |
| Parsers (EUR-Lex HTML 1.1.0, Légifrance HTML, gii XML), normalization, article chunking | `src/lexgrid/parsers`, `chunking.py` | Done |
| Lineage store (sources → documents → versions → chunks, quarantine, index_runs, eval_runs) | `store.py` | Done (SQLite offline, Postgres live) |
| Embedders (bge-m3, e5, Titan, hash) + cache | `embed.py` | Done; Titan blocked (backlog #8) |
| OpenSearch indexes, promote/rollback, gated release | `retrieval/opensearch.py`, `gate.py` | Done; gate pass + reject verified live (D3-GATE-01/02) |
| Retrieval service (4 modes), context assembly, abstention, extractive `/ask` | `retrieval/`, `answer.py` | Done; threshold 0.15 (D3-ABSTAIN-01) |
| REST API + MCP server | `api.py`, `mcp_server.py` | Done, tested offline |
| Evaluation (metrics, CIs, paired tests, results JSON) | `evals/` | Done; golden v1 = 30 + 10 no-answer, labels unreviewed |
| promptfoo contract (CI) + quality (Mac) suites | `evals/promptfoo/`, `scripts/build_promptfoo.py` | Done; contract 10/10 (D4-PF-CONTRACT-01) |
| CI: `verify`, `retrieval-gate`, `api-contract` | `.github/workflows/ci.yml` | Done |

## How to run
See [README](../README.md#run) and [AGENTS.md](../AGENTS.md). Offline gate: `uv run scripts/verify.py`.

## Trust boundaries
- Legal texts and retrieved chunks are data: screened at ingest (quarantine), wrapped as `<source>` data in context.
- Scope comes only from API keys (`LEXGRID_API_KEYS`) / `LEXGRID_MCP_KEY`; requests can narrow, never widen.
- No secrets in the repo; AWS credentials live in `~/.aws` (profile `lexgrid`, IAM user `lexgrid-lab`).

## Verified results
Only in [FINDINGS](../evals/FINDINGS.md): D1-INGEST-*, D2-INGEST-05, D2-EVAL-*, D2-CMP-01, D2-TYPES-01, D3-LEAK-01, D3-SCREEN-01, D3-GATE-01/02, D3-ABSTAIN-01, D4-CMP-01, D4-PF-CONTRACT-01.

## Backlog
[RELIABILITY_BACKLOG](RELIABILITY_BACKLOG.md) (#1 per-article dates, #2 LEGI bulk XML, #5 near-duplicates,
#7–#8 Bedrock blocked) and [ROADMAP](ROADMAP.md) (phases 1–6 with acceptance criteria).
