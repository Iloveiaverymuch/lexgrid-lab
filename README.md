# lexgrid — multi-jurisdiction legal retrieval lab

[![verify](https://github.com/Iloveiaverymuch/lexgrid-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/Iloveiaverymuch/lexgrid-lab/actions/workflows/ci.yml)

Search engine for EU, French and German consumer and data-protection law: ingestion with full lineage,
versioned hybrid indexes promoted only through an evaluation gate, per-country isolation, and a cited-answer
API exposed over REST and MCP. Built as a 3-day **lab**; every number below comes from a results file.
**Not legal advice.**

![Four rankings of the same question side by side](docs/screenshots/03-compare-four-rankings.png)

## Results at a glance

Golden set v1: 30 answerable + 10 no-answer questions in FR / EN / DE (labels drafted for the lab, human review pending).

| Ranking (OpenSearch 2.19, bge-m3, local reranker; run D4-EVAL-DIVERSIFY-01) | nDCG@10 [95% CI] | Hit@5 | p50 |
|---|---|---|---|
| Keywords (BM25) | 0.571 [0.42, 0.72] | 0.700 | 67 ms |
| Meaning (dense, bge-m3) | 0.761 [0.66, 0.86] | 0.933 | 39 ms |
| Hybrid (RRF) | 0.744 [0.64, 0.85] | 0.900 | 65 ms |
| **Hybrid + reranker (bge-reranker-v2-m3)** | **0.860 [0.79, 0.93]** | 0.933 | 3.2 s |

- **Why hybrid:** keywords own article numbers (0.99 vs 0.56 for dense), dense owns cross-language questions (0.76 vs 0.16) — D2-TYPES-01.
- **Found, fixed, measured:** comparative questions across countries returned only EU texts; per-jurisdiction
  retrieval and diversification raised them from 0.696 to 0.783 nDCG@10 (n = 6, CI [−0.00, +0.18]) — D4-CMP-01.
- **Isolation:** 0 cross-jurisdiction leaks over 4,516 results; 120/120 scope-widening requests refused — D3-LEAK-01.
- **Release gate:** an index built from 30% fewer chunks was rejected (−0.159 nDCG@10) and never served — D3-GATE-02.
- **Abstention:** 10/10 out-of-corpus questions refused; 27/30 answerable questions answered — D3-ABSTAIN-01.
- **API contract:** 10/10 promptfoo behaviour tests over HTTP on every push (auth, scope, pinning, citations) — D4-PF-CONTRACT-01.

Run ids and sample sizes: [evals/FINDINGS.md](evals/FINDINGS.md).

## What it does

| Area | Capability |
|---|---|
| **Ingestion** | Source registry with licences; checksummed captures; 3 parsers (EUR-Lex HTML, Légifrance HTML, gesetze-im-internet XML); normalisation of legal numbering (`Art. L. 221-18` ≡ `L221-18`); one chunk per article with its hierarchy; idempotent re-runs; versions and tombstones |
| **Lineage** | Every result traces to its chunk, document version, parser version, raw file SHA-256 and official URL |
| **Indexing** | One OpenSearch index per jurisdiction and version (BM25 with FR/EN/DE analysers + HNSW vectors per embedder); atomic alias promotion and rollback |
| **Retrieval** | BM25, dense, RRF hybrid, cross-encoder reranking; filters by jurisdiction, language, document type and date in force; exact article references pinned first; per-jurisdiction diversification |
| **Answers** | Token-budgeted context with per-country quota; quoted, cited extractive answers; abstention below a calibrated reranker score |
| **Evaluation** | nDCG, MRR, recall, precision, hit with bootstrap intervals; paired comparisons between runs and by question type; promptfoo behaviour suites (API contract in CI, quality from the golden set) |
| **Release gate** | Candidate indexes evaluated against live ones on the golden set; promoted only within tolerance |
| **Security** | Scope from API keys only (narrow, never widen); lineage hidden outside scope; prompt-injection screening (EN/FR/DE) quarantines poisoned text before indexing |
| **Interfaces** | REST API, demo console (this page's screenshots), MCP server for agents |

## Architecture

```mermaid
flowchart LR
  subgraph Data["Data plane"]
    R[sources.yaml<br/>licences] --> F[Pinned captures<br/>SHA-256]
    F --> P[Parsers<br/>EUR-Lex / Légifrance / gii XML]
    P --> C[Article chunker<br/>+ normalisation]
    C --> S{Injection<br/>screen}
    S -->|clean| L[(Postgres<br/>lineage)]
    S -->|flagged| Q[(Quarantine)]
  end
  subgraph Index["Index plane"]
    L --> E[Embedders<br/>bge-m3 · e5<br/>cached]
    E --> B[Build index<br/>legal-cc-ts-sha]
    B --> G{Eval gate<br/>vs live}
    G -->|pass| A[Alias<br/>legal-cc-current]
    G -->|regression| X[Rejected]
  end
  subgraph Serve["Serving"]
    A --> RS[Retrieval service<br/>BM25 · kNN · RRF · rerank<br/>scope · diversify]
    RS --> API[REST API<br/>/search /ask /lineage]
    RS --> MCP[MCP server<br/>stdio tools]
    API --> UI[Demo console]
  end
  subgraph Eval["Evaluation"]
    GS[Golden set<br/>40 questions] --> EV[Eval runner<br/>metrics + CIs]
    EV --> FD[FINDINGS<br/>results JSON]
  end
  RS --> EV
  EV --> G
```

| Layer | Code | Key decisions |
|---|---|---|
| Data plane | [`src/lexgrid/parsers/`](src/lexgrid/parsers), [`chunking.py`](src/lexgrid/chunking.py), [`pipeline.py`](src/lexgrid/pipeline.py), [`store.py`](src/lexgrid/store.py), [`screen.py`](src/lexgrid/screen.py) | [SPEC-001](docs/specs/SPEC-001-data-plane.md) |
| Index plane | [`embed.py`](src/lexgrid/embed.py), [`retrieval/opensearch.py`](src/lexgrid/retrieval/opensearch.py), [`gate.py`](src/lexgrid/gate.py) | [ADR-001](docs/adr/ADR-001-open-source-embeddings-and-reranker.md), [ADR-002](docs/adr/ADR-002-own-pipeline-vs-bedrock-knowledge-bases.md) |
| Retrieval | [`retrieval/service.py`](src/lexgrid/retrieval/service.py), [`retrieval/context.py`](src/lexgrid/retrieval/context.py), [`answer.py`](src/lexgrid/answer.py) | [RETRIEVAL_DECISIONS](docs/RETRIEVAL_DECISIONS.md) |
| Serving | [`api.py`](src/lexgrid/api.py), [`mcp_server.py`](src/lexgrid/mcp_server.py), [`static/index.html`](src/lexgrid/static/index.html) | [SPEC-003](docs/specs/SPEC-003-serving-and-safety.md) |
| Evaluation | [`evals/`](src/lexgrid/evals), [`evals/golden/golden_v1.yaml`](evals/golden/golden_v1.yaml) | [SPEC-002](docs/specs/SPEC-002-retrieval-and-eval.md) |

## Stack and tools

| Concern | Choice |
|---|---|
| Language, packaging, quality | Python 3.12, `uv`, `ruff`, `mypy --strict`, `pytest` (offline gate < 60 s) |
| Search | OpenSearch 2.19 (BM25 + Lucene HNSW kNN, language analysers, aliases) |
| Lineage store | PostgreSQL 16 via SQLAlchemy Core (SQLite in tests) |
| Embeddings | `BAAI/bge-m3` (default), `intfloat/multilingual-e5-base`; Amazon Titan V2 implemented behind the same interface |
| Reranking | `BAAI/bge-reranker-v2-m3` cross-encoder on Apple GPU (MPS) |
| API and UI | FastAPI, single-file vanilla JS console (no build step, untrusted text never rendered as HTML) |
| Agent interface | MCP server (`mcp` Python SDK, stdio) |
| Infra | Docker Compose (OpenSearch, Postgres), GitHub Actions |

Amazon Bedrock (Titan embeddings, Bedrock Rerank) was blocked on the lab account's Free plan; the decision to
run open-source models locally and how to switch back is recorded in [ADR-001](docs/adr/ADR-001-open-source-embeddings-and-reranker.md).

## For agents: MCP tools

The lab has no agent of its own; it exposes retrieval as tools any agent can call, with the same scope rules as the API.

| Tool | Purpose |
|---|---|
| `search_legal(query, jurisdictions?, as_of?, k?)` | Hybrid search within the caller's entitled jurisdictions |
| `get_article(citation_id)` | Full text of a cited article, all available languages |
| `get_lineage(chunk_id)` | Provenance of a passage |
| `get_index_status(jurisdiction)` | Live index version and release history |

Claude Desktop configuration (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "lexgrid": {
      "command": "uv",
      "args": ["--directory", "/path/to/lexgrid-lab", "run", "lexgrid", "mcp"],
      "env": { "LEXGRID_API_KEYS": "dev-fr:FR", "LEXGRID_MCP_KEY": "dev-fr",
               "LEXGRID_DB": "postgresql+psycopg://lexgrid:lexgrid@localhost:5432/lexgrid" }
    }
  }
}
```

## Screenshots

| | |
|---|---|
| ![Exact article reference placed first](docs/screenshots/01-search-article-number.png) **Exact reference** placed first, citation and date in force in the margin | ![Lineage panel](docs/screenshots/02-lineage.png) **Lineage**: result → chunk → version → raw file → official source |
| ![French question on German law](docs/screenshots/04-cross-lingual-weakness.png) **Known weakness**: French question on German law; keyword noise pulls hybrid down | ![Three countries](docs/screenshots/05-three-countries.png) **Comparative question**: one article per jurisdiction at the top |
| ![Cited answer](docs/screenshots/06-ask-cited-answer.png) **Cited answer**: quotes with citations, disclaimer | ![Abstention](docs/screenshots/07-ask-abstains.png) **Abstention** when the corpus cannot answer |
| ![Index history](docs/screenshots/08-index-history-and-gate.png) **Release history**: promoted, retired, rejected by the gate | ![Evaluation](docs/screenshots/09-evaluation.png) **Evaluation** with intervals and per-type scores |

![Scope refused](docs/screenshots/10-scope-refused.png)

## Engineering practice
- Spec first ([docs/specs](docs/specs)), decisions as ADRs ([docs/adr](docs/adr)), operating rules for coding agents ([AGENTS.md](AGENTS.md)).
- Three CI gates on every push ([ci.yml](.github/workflows/ci.yml)): `verify`, the offline retrieval regression gate, and the
  promptfoo API contract against a running server ([ADR-003](docs/adr/ADR-003-evaluation-tooling-python-runner-and-promptfoo.md)).
- `uv run scripts/verify.py`: lint, strict types, 100+ offline tests, registry and docs-consistency checks (every run id
  cited here must exist in FINDINGS), in CI on every push.
- CI retrieval gate: the golden set runs offline on every push and fails on any nDCG@10 drop beyond 0.01 or any exact
  article reference not at rank 1 ([`scripts/eval_gate.py`](scripts/eval_gate.py)).
- promptfoo suites in [evals/promptfoo](evals/promptfoo): **contract** (10 tests, CI) and **quality** (40 tests generated
  from the golden set, run against the real models: `npx promptfoo@0.126.0 eval -c evals/promptfoo/promptfooconfig.quality.yaml`).
- Append-only measurements with run ids and sample sizes ([evals/FINDINGS.md](evals/FINDINGS.md)); known gaps in [docs/RELIABILITY_BACKLOG.md](docs/RELIABILITY_BACKLOG.md).

## Known limitations (kept visible on purpose)
- **Language-blind fusion:** on cross-language questions, keyword noise pulls hybrid below dense (0.59 vs 0.76, n = 6).
- **Confusable articles:** BGB § 357b (financial services) can outrank § 357 (general refund rule).
- **Diversification side effect:** a country's best match can be wrong when its cross-language retrieval is weak.
- **Reranker latency:** ~3 s p50 on a laptop GPU.
- **Data:** only current French versions (as-of queries show absence, not older text); 30-question golden set.

## Status and roadmap
This is a **work in progress**. The 3-day lab covers the data plane, retrieval as a product and its evaluation. The
next phases (retrieval quality, freshness and scale with a Go fetcher and event-driven ingestion, observability,
multi-agent answers on Amazon Bedrock with a citation verifier, legal analysis delivered as a PDF by e-mail after
human approval, productisation) are planned with acceptance criteria in [docs/ROADMAP.md](docs/ROADMAP.md).

## Run it

```bash
uv sync --extra ml
docker compose -f infra/docker-compose.yml up -d --wait
export LEXGRID_DB=postgresql+psycopg://lexgrid:lexgrid@localhost:5432/lexgrid
uv run lexgrid ingest
uv run lexgrid embed --model bge-m3 && uv run lexgrid embed --model e5
uv run lexgrid index release --models bge-m3,e5
LEXGRID_API_KEYS="dev-fr:FR;dev-all:EU,FR,DE" uv run lexgrid serve   # console at http://127.0.0.1:8000/
```
Evaluation: `uv run lexgrid eval --embedder bge-m3 --warmup --run-id MY-RUN`. All commands: [AGENTS.md](AGENTS.md).
Live demo script (French): [docs/DEMO_15MIN.md](docs/DEMO_15MIN.md).

## Data and licences
EUR-Lex (© European Union, reuse authorised), Légifrance page capture (Licence Ouverte 2.0, to verify before
redistribution), gesetze-im-internet.de (official works, § 5 UrhG). Per source in [data/sources.yaml](data/sources.yaml).
