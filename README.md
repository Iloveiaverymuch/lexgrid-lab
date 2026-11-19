# lexgrid-lab

A 3-day **lab** on multi-jurisdiction legal retrieval: ingestion with lineage, versioned hybrid indexes with a
promotion gate, measured retrieval quality, and a cited-answer API/MCP with per-country isolation.
**Not legal advice, not a product.** Everything below links to code, a test or a results file.

## What it demonstrates

| Capability | Evidence |
|---|---|
| Heterogeneous ingestion: 3 formats, 3 languages, 3 jurisdictions | [`src/lexgrid/parsers/`](src/lexgrid/parsers), contract tests on real captures ([`tests/test_real_fixtures.py`](tests/test_real_fixtures.py)) |
| Article-aware chunking, normalization, idempotent re-runs, versions + tombstones | [SPEC-001](docs/specs/SPEC-001-data-plane.md), [`tests/test_pipeline.py`](tests/test_pipeline.py) |
| Lineage from any hit to raw bytes (sha256, URL, parser version) | `GET /lineage/{chunk_id}`, `lexgrid lineage` |
| Versioned OpenSearch indexes, atomic alias swap, rollback, **eval-gated promotion** | [`src/lexgrid/gate.py`](src/lexgrid/gate.py), [SPEC-003](docs/specs/SPEC-003-serving-and-safety.md) |
| BM25 + dense + RRF + cross-encoder rerank, metadata and as-of filters | [SPEC-002](docs/specs/SPEC-002-retrieval-and-eval.md), [RETRIEVAL_DECISIONS](docs/RETRIEVAL_DECISIONS.md) |
| Evaluation: nDCG, MRR, recall, precision, hit with bootstrap CIs and paired tests | [`src/lexgrid/evals/`](src/lexgrid/evals), [FINDINGS](evals/FINDINGS.md) |
| Embedding choice (bge-m3 vs multilingual-e5; Bedrock Titan blocked) | [ADR-001](docs/adr/ADR-001-open-source-embeddings-and-reranker.md) |
| Own pipeline vs Bedrock Knowledge Bases | [ADR-002](docs/adr/ADR-002-own-pipeline-vs-bedrock-knowledge-bases.md) |
| Per-country isolation (leak rate 0), prompt-injection quarantine | [`tests/test_api_mcp.py`](tests/test_api_mcp.py), [`tests/test_screen.py`](tests/test_screen.py) |
| Retrieval as a product: same contract over REST and MCP | [`src/lexgrid/api.py`](src/lexgrid/api.py), [`src/lexgrid/mcp_server.py`](src/lexgrid/mcp_server.py) |

## Results (golden set v1: 30 answerable + 10 no-answer queries, labels drafted by the agent, human review pending)

| Config (OpenSearch 2.19, local models) | nDCG@10 [95% CI] | hit@5 | p50 latency | Run |
|---|---|---|---|---|
| BM25 | 0.557 [0.41, 0.71] | 0.700 | 74–106 ms | D2-EVAL-E5-01 |
| bge-m3 dense | 0.759 [0.66, 0.86] | 0.933 | 91 ms | D2-EVAL-BGEM3-01 |
| bge-m3 hybrid (RRF) | 0.733 [0.63, 0.84] | 0.933 | 65 ms | D2-EVAL-BGEM3-01 |
| **bge-m3 hybrid + bge-reranker-v2-m3** | **0.843 [0.76, 0.92]** | 0.933 | 3.0 s | D2-EVAL-BGEM3-01 |

- BM25 owns identifiers (exact references nDCG 0.99) and fails cross-lingual queries (0.16); dense is the reverse
  (~0.5 / 0.76). Hybrid is the only mode robust to both (n = 6 per type, indicative) — D2-TYPES-01.
- bge-m3 beats multilingual-e5 by +0.131 nDCG@10 in dense mode (paired CI [+0.065, +0.203]) — D2-CMP-01.
- Jurisdiction leak rate 0 over 4,516 hits; 120/120 scope-widening requests refused — D3-LEAK-01.
- Promotion gate: a rebuild from the same corpus is promoted (diff +0.000); a build missing 30% of chunks is
  rejected (nDCG@10 −0.159, paired CI [−0.271, −0.063]) and the live aliases stay unchanged — D3-GATE-01/02.
- `/ask` abstains below a reranker score of 0.15: 10/10 no-answer queries abstained, 27/30 answerable answered
  (hit@1 93% when answering); only 10 no-answer queries — D3-ABSTAIN-01.
- 30 queries give wide intervals; numbers are a lab measurement, not a production claim. All rows: [FINDINGS](evals/FINDINGS.md).

## Architecture

```
sources.yaml + pinned fixtures (sha256)
   └─ ingest: parse → normalize → chunk per article → screen (quarantine) → Postgres lineage
        └─ embed (bge-m3, e5; cached) → index release: build legal-<cc>-<ts>-<sha> → golden-set gate → alias swap
             └─ RetrievalService: BM25 | kNN | RRF | rerank, scope from entitlements, collapse per article
                  ├─ REST: /search /ask /lineage        ├─ MCP (stdio): search_legal, get_article, …
                  └─ eval: metrics + CIs → evals/results/<run>.json → FINDINGS
```

## Run

```bash
uv sync --extra ml                                          # local models (torch) on the Mac
uv run scripts/verify.py                                    # offline gate: lint, mypy --strict, tests, docs (< 60 s)
docker compose -f infra/docker-compose.yml up -d --wait     # OpenSearch + Postgres
export LEXGRID_DB=postgresql+psycopg://lexgrid:lexgrid@localhost:5432/lexgrid
uv run lexgrid ingest
uv run lexgrid embed --model bge-m3 && uv run lexgrid embed --model e5
uv run lexgrid index release --models bge-m3,e5            # build → gate → promote (or reject)
uv run lexgrid eval --embedder bge-m3 --warmup --run-id MY-RUN
LEXGRID_API_KEYS="dev-fr:FR;dev-all:EU,FR,DE" uv run lexgrid serve
```
All commands: [AGENTS.md](AGENTS.md). Demo script: [docs/DEMO_15MIN.md](docs/DEMO_15MIN.md).

## Scope and limits
- **Lab scope:** ~3,200 chunks; no scale test. Go fetcher, Kafka, Airflow, Redis, K8S, PDF/e-mail delivery are
  roadmap items ([LAB_PLAN](docs/LAB_PLAN.md)).
- **Bedrock:** blocked on the lab account's Free plan (Rerank by policy, Titan after one call). Models are open
  source and local (ADR-001); `/ask` is extractive (quotes with citations), not LLM-generated.
- **Labels:** drafted by the agent; human review pending. Known gaps: [RELIABILITY_BACKLOG](docs/RELIABILITY_BACKLOG.md).
- **What production would add:** reviewed and larger golden set, per-article validity dates (LEGI bulk XML),
  near-duplicate detection, latency budget for reranking, auth beyond static API keys, observability.

## Data and licenses
EUR-Lex (© European Union, reuse authorised), Légifrance page capture (Licence Ouverte 2.0, to verify before
redistribution), gesetze-im-internet.de (official works, § 5 UrhG). Per source in [data/sources.yaml](data/sources.yaml).
