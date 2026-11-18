# SPEC-002 — Versioned indexes, hybrid retrieval, evaluation

Status: APPROVED (3-day scope) · Last updated: 2026-11-18 · Next action: live runs on the Mac

## 1. Problem
The offer asks for BM25 + embeddings + reranking + metadata filters, index freshness/rebuilds with versioning,
and continuous evaluation (recall, precision, nDCG, MRR). We need all four retrieval modes behind one contract,
measured on a labelled set with honest uncertainty.

## 2. Behavior
- Embedders: `hash` (offline fake), `e5` (intfloat/multilingual-e5-base, local), `titan` (Bedrock Titan V2,
  eu-central-1, explicit). SQLite cache keyed by model + kind + sha256(text): re-runs cost nothing.
- Index per jurisdiction `legal-<cc>-<timestamp>-<snapshot8>` with BM25 (folded + fr/en/de analyzers) and one
  kNN field per embedder (HNSW, Lucene, cosine). `index_runs` row per build; alias `legal-<cc>-current`
  moved atomically on promote; rollback moves it back to the last promoted index.
- `RetrievalService.search(query, Filters, k, mode)`; modes `bm25 | dense | hybrid_rrf | hybrid_rrf_rerank`.
  Decisions R1–R7 in [RETRIEVAL_DECISIONS.md](../RETRIEVAL_DECISIONS.md).
- Golden set v1: 30 answerable + 4 no-answer queries (FR/EN/DE; exact refs, paraphrases, cross-lingual,
  multi-jurisdiction), graded qrels on article keys. Draft by the agent, human review pending.
- `lexgrid eval` writes `evals/results/<run_id>.json` (config, git sha, per-query ranks and metrics, summary)
  and optionally a FINDINGS row.

## 3. Failure modes
Misaligned vectors → build refused. Promote of an unknown index → refused. Rollback with no history → error.
Bedrock throttling → adaptive retries; Free-plan SCP blocks Rerank (backlog #7).

## 4. Security
Scope from entitlements only; aliases + filter (R6). No document text in logs.

## 5. Acceptance criteria → tests
| AC | Test |
|---|---|
| Metrics match hand-computed values | `tests/test_metrics.py` |
| Scope never widened, any mode | `test_retrieval.py::test_scope_is_never_widened` |
| As-of filter excludes not-yet-in-force and repealed text | `test_retrieval.py::test_as_of_filters_out_not_yet_in_force_and_repealed` |
| Build → promote → rollback, atomic alias swap | `test_opensearch_index.py::test_build_promote_rollback` |
| Exact references rank first on the real corpus | `test_offline_eval.py::test_exact_reference_queries_rank_first` |
| Golden labels exist in the corpus | `test_offline_eval.py::test_golden_set_is_valid_and_labels_exist` |
| Embedding cache only pays for misses | `test_retrieval.py::test_embedding_cache_only_pays_for_misses` |
