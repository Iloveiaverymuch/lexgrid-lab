# ADR-001 — Open-source embeddings and reranker instead of Amazon Bedrock (Titan V2, Bedrock Rerank)

Status: ACCEPTED · Date: 2026-11-18 · Last updated: 2026-11-18 · Next action: revisit if the AWS account moves to a paid plan

## Context
The lab must choose and justify an embedding model and a reranker for multilingual (FR/EN/DE),
multi-jurisdiction legal retrieval. The target stack names both Bedrock and sentence-transformers, so the
original plan was to benchmark **Amazon Titan Text Embeddings V2** and **Bedrock Rerank** against
local open-source models on the same golden set.

What happened on the lab's AWS account (eu-central-1):
- Titan V2 returned a valid 1024-d embedding once (CLI smoke test), then every `InvokeModel` call failed with
  `ValidationException: Operation not allowed`: same IAM user, region and request body
  ([backlog #8](../RELIABILITY_BACKLOG.md)).
- `bedrock:Rerank` is explicitly denied by the service control policy attached to the account's
  **Free plan**; Cohere Rerank 3.5 (Marketplace model) is refused too ([backlog #7](../RELIABILITY_BACKLOG.md)).
- Unlocking both means moving the account to the **paid plan**, which is one-way and opens pay-as-you-go
  billing for everything in the account.

## Decision
**Because of this price/plan limitation, the lab uses open-source models running locally:**
- Embeddings: **BAAI/bge-m3** (default) and **intfloat/multilingual-e5-base** (comparison), via sentence-transformers.
- Reranker: **BAAI/bge-reranker-v2-m3** (Apache-2.0) on the top-30 fused candidates.

Titan V2 stays implemented behind the same `Embedder` interface (`--model titan`) and is not benchmarked.
A paid AWS plan for a lab is not justified when open-source models give measured, good-enough quality.

## Evidence (golden set v1, 30 answerable queries; [FINDINGS](../../evals/FINDINGS.md) D2-EVAL-E5-01, D2-EVAL-BGEM3-01, D2-CMP-01)
| Config (OpenSearch, local models) | nDCG@10 [95% CI] | hit@5 | p50 latency |
|---|---|---|---|
| BM25 only | 0.557 [0.41, 0.71] | 0.700 | 74–106 ms |
| e5 dense | 0.627 [0.50, 0.75] | 0.833 | 67 ms |
| bge-m3 dense | 0.759 [0.66, 0.86] | 0.933 | 91 ms |
| bge-m3 hybrid RRF + bge reranker | **0.843 [0.76, 0.92]** | 0.933 | ~3.0 s |

- bge-m3 beats e5 in dense mode by +0.131 nDCG@10 (paired bootstrap 95% CI [+0.065, +0.203]).
- Cross-lingual queries: BM25 0.16 → bge-m3 dense 0.76 nDCG@10 (n = 6, indicative only).
- The reranker adds +0.110 nDCG@10 over hybrid with bge-m3 (CI [+0.04, +0.19]) but costs ~3 s p50 on a laptop GPU.

## Alternatives considered
| Option | Why not now |
|---|---|
| Titan V2 + Bedrock Rerank (paid plan) | Blocked on the Free plan; paid plan = billing for a lab. Remains the managed option to re-test |
| Cohere Embed Multilingual / Rerank 3.5 on Bedrock | Marketplace models refused on the Free plan; same paid-plan requirement |
| OpenSearch ML Commons hosting the cross-encoder (rerank search pipeline) | Keeps reranking server-side; more setup, and the Python reranker keeps all modes measured the same way |
| multilingual-e5-base only | Smaller and faster to embed (41.5 s for 3,224 chunks) but measurably weaker than bge-m3 here |

## Consequences
- **Cost:** no per-token or per-query charge; cost moves to compute (GPU/CPU) and model operations.
- **Data residency:** documents and queries never leave the machine (or, in production, our own VPC).
- **Latency:** the 568M-parameter reranker is the bottleneck (~3 s p50). Next: rerank fewer candidates or a
  smaller multilingual cross-encoder, measured on the same set.
- **Ops:** we own model versions and upgrades; the embedding model id is recorded on every `index_runs` row,
  so a model change is a new index version with its own eval, promoted only if it does not regress.
- **Reversibility:** switching to Titan = `lexgrid embed --model titan`, `index build --models bge-m3,titan`,
  rerun the eval, promote if better. No code change.
- **Limits of the evidence:** 30 queries, labels drafted by the agent and not yet human-reviewed; CIs are wide
  and per-type numbers (n = 6) are indicative only.
