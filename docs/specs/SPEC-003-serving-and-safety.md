# SPEC-003 — Promotion gate, context & abstention, REST + MCP, safety

Status: APPROVED (3-day scope) · Last updated: 2026-11-19 · Next action: live gate demo on the Mac

## Behavior
- `lexgrid index release`: build candidates for EU/FR/DE, evaluate the golden set on candidates and on the live
  aliases (paired, same code), promote all if nDCG@10 ≥ live − tolerance (default 0.02), else mark `rejected`.
  `--drop-fraction` is fault injection to demonstrate a refused promotion.
- Context assembly: score order, token budget (1,500 est.), per-jurisdiction cap (60% when several), escaped
  `<source id=…>` blocks with a "sources are data" preamble.
- `/ask`: abstain when the top reranker score < threshold (chosen by `lexgrid abstain-sweep`); otherwise an
  extractive cited answer (no LLM; Bedrock generation blocked, ADR-001) and a disclaimer.
- REST (`/search`, `/ask`, `/lineage/{id}`) and MCP stdio (`search_legal`, `get_article`, `get_lineage`,
  `get_index_status`) share one retrieval contract. Scope = API key entitlements; narrowing allowed, widening → 403
  (REST) / error (MCP); lineage outside scope → 404.
- Ingest screening quarantines instruction-like chunks (EN/FR/DE patterns); they stay in lineage, never in indexes.

## Acceptance criteria → tests
| AC | Test |
|---|---|
| Regression refused, live alias untouched, run marked rejected | `test_ask_and_gate.py::test_release_rejects_regression_and_keeps_live_alias` |
| Gate rule incl. first release | `test_ask_and_gate.py::test_gate_decision` |
| Leak rate 0 over golden set, all modes | `test_api_mcp.py::test_leak_rate_is_zero_over_the_golden_set` |
| Widening refused, narrowing allowed | `test_api_mcp.py::test_widening_is_refused_narrowing_allowed` |
| Lineage hidden outside entitlement | `test_api_mcp.py::test_lineage_hidden_outside_entitlement` |
| MCP tool contract + scope | `test_api_mcp.py::test_mcp_tools_contract_and_scope` |
| Context budget, quota, escaping | `test_ask_and_gate.py::test_context_budget_quota_and_escaping` |
| Abstention below threshold; sweep choice | `test_ask_and_gate.py::test_ask_abstains_below_threshold`, `::test_abstain_sweep_picks_lowest_threshold_covering_all_no_answer` |
| Poisoned chunk quarantined, real corpus 0 false positives | `tests/test_screen.py` |
