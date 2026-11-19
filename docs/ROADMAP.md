# Roadmap — from retrieval lab to legal analysis platform

Status: ACTIVE (work in progress) · Last updated: 2026-11-19 · Next action: phase 1 (retrieval quality)

## Aim
Demonstrate, with code and measured results, what an **Expert Data & Retrieval** owns in a legal AI team: the
"raw material" of the AI. The target system has three parts:
1. **A data platform** that collects, parses, normalises, chunks, embeds and indexes legal texts from several
   European jurisdictions, with lineage, versioned indexes and freshness tracking.
2. **A retrieval service treated as a product** for other developers: hybrid search, metadata and temporal
   filters, reranking, per-country isolation, exposed over REST and MCP.
3. **A multi-agent RAG system** that answers legal questions with exact citations and, on request, writes a
   structured legal situation analysis, renders it as a PDF and emails it to the client after human approval.

Build order is deliberate: **data and retrieval evaluation before agents**. Agents are only as good as what
they retrieve, and retrieval is only improvable once it is measured.

## Where the lab stands (3 days of work)

| Part | Status | Evidence |
|---|---|---|
| Data platform: registry, 3 parsers, article chunking, lineage, versions, quarantine | **Done** (lab scale: 4 sources, 3,224 chunks) | [SPEC-001](specs/SPEC-001-data-plane.md), FINDINGS D1–D2 |
| Versioned indexes, alias promotion, rollback, eval-gated release | **Done** | [SPEC-003](specs/SPEC-003-serving-and-safety.md), D3-GATE-01/02 |
| Hybrid retrieval, rerank, filters, diversification, abstention | **Done**, with known weaknesses | [RETRIEVAL_DECISIONS](RETRIEVAL_DECISIONS.md), D4-CMP-01 |
| Retrieval as a product: REST, MCP, demo console | **Done** (static API keys, MCP over stdio) | [`api.py`](../src/lexgrid/api.py), [`mcp_server.py`](../src/lexgrid/mcp_server.py) |
| Evaluation: golden set, CIs, paired tests, CI gates, promptfoo | **Done** (30 + 10 questions, labels unreviewed) | [ADR-003](adr/ADR-003-evaluation-tooling-python-runner-and-promptfoo.md) |
| Freshness, scale, event-driven ingestion, Go fetcher | **Not started** | phase 2 |
| Observability (traces, dashboards, cost) | **Not started** | phase 3 |
| Multi-agent answers on Amazon Bedrock | **Not started** (Bedrock blocked on the lab account's Free plan) | phase 4, [ADR-001](adr/ADR-001-open-source-embeddings-and-reranker.md) |
| Legal analysis → PDF → human approval → e-mail | **Not started** | phase 5 |

## Phase 1 — Retrieval quality (≈ 3–4 days)
| Work | Acceptance (measured on the golden set, paired against the current run) |
|---|---|
| Golden set v2: ≥ 60 questions, labels reviewed by a person, plus a **hard set** (confusable articles such as BGB § 357 / § 357b, repealed versions, near-duplicates, poisoned chunks) | Labels reviewed; hard set reported separately |
| **Language-aware fusion**: weight keyword search by whether the query language matches the target law's language, or translate the query | Cross-language questions ≥ dense alone (0.76 today, hybrid 0.59) with no loss on exact references |
| **Credibility floor** for diversification: give a country a top slot only if its best article clears a calibrated reranker score | Removes wrong national articles (q28 § 997, q29 § 482) without losing q27/q30 gains |
| **Reranker latency**: fewer candidates, a smaller multilingual cross-encoder, batching | p95 < 1.5 s with ≤ 0.02 nDCG@10 loss |
| Near-duplicate detection (MinHash) at ingest and collapse at retrieval | Duplicate rate reported; no regression |

## Phase 2 — Data platform at scale and freshness (≈ 1 week)
| Work | Acceptance |
|---|---|
| **LEGI bulk XML** for French codes with per-article `date_debut` / `date_fin` (historical versions) | "As of date" returns the old text, not an absence (backlog #1–#2) |
| **Go fetcher**: conditional GET, rate limits, robots/terms, checksums, emits `doc.fetched` events | `go test ./...`; re-fetch of unchanged sources transfers nothing |
| **Event-driven ingestion** (Redpanda/Kafka or Postgres outbox) with idempotent consumers | Replaying a topic changes nothing |
| **Orchestration**: thin Airflow (or Prefect) DAG over the existing CLI steps | DAG run = same result as manual CLI |
| **Freshness**: `freshness_lag = indexed_at − source_updated_at` per source | `lexgrid status` and a dashboard show it |
| **Scale test**: ≥ 200k chunks (full codes + synthetic) | Indexing throughput, query p95 at scale, disk and memory, cost per 1k queries, with limits stated |
| Redis cache (query → results, text → embedding) keyed by index alias version | Hit rate and latency saved measured; cache never survives a reindex |

## Phase 3 — Observability (≈ 2–3 days)
| Work | Acceptance |
|---|---|
| OpenTelemetry spans per pipeline step, search mode, rerank, `/ask` and gate; **no legal text or client content in spans** | Trace of one request shows every stage with timings |
| Local Jaeger; AWS X-Ray / CloudWatch via ADOT collector (Frankfurt) | Same trace visible in X-Ray |
| Serving metrics: p50/p95 per mode, cache hit rate, abstention rate, cost per answer | Dashboard |

## Phase 4 — Multi-agent answers on Amazon Bedrock (≈ 1 week; needs a paid AWS plan)
| Work | Acceptance |
|---|---|
| LangGraph graph with typed state: **Intake/Router** → **Jurisdiction researchers** (one per country, in parallel, calling `search_legal` / `get_article` through MCP) → **Legal analyst** (strong model) → **Citation verifier** (fast model + deterministic checks), bounded loops and token budgets | Every claim carries a citation id; verifier removes unsupported claims |
| Bedrock Guardrails (PII, contextual grounding); tool allowlists per agent; exhausted tools removed from the request | Poisoned-chunk exfiltration test blocked |
| Generation evaluation: citation precision and recall, groundedness judge calibrated on ≥ 30 human labels (Cohen's kappa), promptfoo groundedness and red-team suites | Kappa reported; jurisdiction leak rate 0; abstention accuracy reported |
| Model routing by risk (strong model for analysis, fast model for routing and verification); cost per answer | Cost and latency per answer in FINDINGS |

## Phase 5 — Legal situation analysis delivered to the client (≈ 3–4 days)
| Work | Acceptance |
|---|---|
| `LegalAnalysis` schema (IRAC: issue, rule, application, conclusion; comparative table across countries) validated before rendering | Invalid analyses never rendered |
| PDF rendered by code from validated JSON (the model never formats the PDF) | Snapshot tests |
| **Human approval** before sending; Amazon SES (MailHog locally); recipient allowlist; idempotency key = sha256(analysis_id + recipient + pdf_sha256); audit trail | Second send returns the first message id; audit row per send |
| Client facts never indexed; per-request store with retention TTL; redaction in logs and traces | PII redaction tests |

## Phase 6 — Productisation (≈ 3–4 days)
| Work | Acceptance |
|---|---|
| MCP over streamable HTTP with bearer auth → entitlements; documentation for consuming teams | Contract tests over HTTP |
| Auth beyond static keys (JWT claims → jurisdictions) | Leak rate 0 maintained |
| Kubernetes manifests (kind), Terraform (plan-only) for AWS, optional Bedrock AgentCore deployment | `kind` deploy runs the contract suite green |

## Principles kept throughout
Spec before code; every number in a results file with its sample size; offline CI with zero paid calls; untrusted
content is data, never instructions; known weaknesses documented, not hidden.
