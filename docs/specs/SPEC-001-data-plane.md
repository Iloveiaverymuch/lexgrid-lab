# SPEC-001 — Data plane: registry, fixtures, parsing, chunking, lineage

Status: APPROVED (3-day scope, 2026-11-18) · Last updated: 2026-11-18 · Next action: real-capture tests

## 1. Problem
Every downstream metric depends on knowing, for each indexed byte, its source, license, jurisdiction and
version, and on chunks that keep legal structure (article numbers searchable, hierarchy preserved).

## 2. Proposed behavior
- `data/sources.yaml` validated by `Source` (unknown fields/parsers fail).
- `data/fixtures/<source>/` holds raw captures + `MANIFEST.json` (sha256, bytes, url, fetched_at).
- One parser per format behind `Parser.parse(raw, source, language) -> NormalizedDocument`.
- Normalization: NFC, spaces, canonical article numbers (`Art. L. 221-18` ≡ `L221-18`, `Article premier` ≡ `1`).
- Chunking: one chunk per article; long articles split on paragraph then sentence boundaries with 1-sentence
  overlap; header `act > path > Article N — heading` in the text.
- Lineage store: `sources → documents → doc_versions → chunks`, content-addressed ids, insert-or-ignore;
  a new content hash creates a new version and tombstones the previous one (`superseded_by`).

## 3. Contracts
See `src/lexgrid/models.py`, `registry.py`, `store.py`. Citation id: `[FR:C. conso art. L221-18 @2016-07-01]`,
language-independent; `article_key` = `EU:GDPR:17` (used by qrels across languages).

## 4. Retrieval impact
Fixes corpus composition and chunk boundaries; any change → new `corpus_snapshot_sha` → reindex + re-eval.

## 5. Failure modes
Unknown article number format → `ParseError` (never guessed). Checksum mismatch → ingest refused.
Annexes and recitals excluded (backlog). Légifrance markup drift → parser works on text lines and fails loudly.

## 6. Security & privacy
Legislation only (`pii_risk: low`); license on every chunk; XML parsed with entities and network disabled.

## 7. Acceptance criteria → tests
| AC | Test |
|---|---|
| Registry rejects unknown field / parser / bad cadence | `tests/test_registry.py` |
| Tampered fixture and orphan files detected | `test_registry.py::test_pin_then_check_detects_tamper_and_orphans` |
| Re-run on unchanged input inserts nothing | `test_pipeline.py::test_first_run_ingests_and_rerun_is_noop` |
| Dry-run writes nothing | `test_pipeline.py::test_dry_run_has_no_side_effects` |
| Changed content → new version, old chunks tombstoned | `test_pipeline.py::test_changed_content_creates_new_version_and_tombstones_old` |
| Chunk traceable to raw file + parser version | `test_pipeline.py::test_lineage_traces_chunk_to_raw_file` |
| Article number in every chunk text | `test_chunking.py::test_article_number_is_in_every_chunk_text` |
| Parser contracts per format | `tests/test_parsers.py` (synthetic) + `tests/test_real_fixtures.py` (real captures) |

## 8. Rollback
Registry and fixtures are in git; the store is derived and rebuilt with `lexgrid ingest`.
