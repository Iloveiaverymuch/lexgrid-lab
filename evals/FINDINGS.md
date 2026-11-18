# FINDINGS (append-only)

Every number shown in the README or the demo must appear here with its run id, config and sample size.

| Date | Run id | Config | Result | n | Conclusion |
|---|---|---|---|---|---|
| 2026-11-18 | D1-INGEST-01 | `lexgrid ingest` (SQLite), chunker `article-v1`, max 450 est. tokens, 1-sentence overlap; fixtures: GDPR + CRD (fr/en/de, EUR-Lex HTML), BGB (gii XML) | 7 doc versions, 3,216 chunks; GDPR 297 articles → 475 chunks (101 split), CRD 105 → 170 (30 split), BGB 2,486 § → 2,571 (66 split); ~2.3 s wall | 1 run | Article counts match the acts (99 / 35 per language); article numbering aligned across fr/en/de |
| 2026-11-18 | D1-INGEST-02 | Same input, second run | 0 new versions, 0 new chunks; ~2.2 s | 1 run | Re-run is a no-op (also asserted by `test_first_run_ingests_and_rerun_is_noop`) |
| 2026-11-18 | D1-INGEST-03 | All 4 sources pinned (adds Légifrance C. conso L221-1 to L221-29 capture, parser 1.0.0 with real-capture fixes) | 8 doc versions, 3,253 chunks; C. conso 31 articles → 37 chunks (5 split), per-article in-force dates parsed (e.g. L221-5 @2026-06-19) | 1 run | Data plane complete for the 3-day scope: 3 jurisdictions, 3 languages, 3 formats |
| 2026-11-18 | D1-INGEST-04 | Same input, second run | 0 new versions, 0 new chunks | 1 run | Idempotent on the full corpus |
