# Demo — 15 minutes

Status: DRAFT · Last updated: 2026-11-19 · Next action: rehearse once end-to-end on the Mac

Setup before the call: Docker up, `export LEXGRID_DB=postgresql+psycopg://lexgrid:lexgrid@localhost:5432/lexgrid`,
indexes released, API running with `LEXGRID_API_KEYS="dev-fr:FR;dev-all:EU,FR,DE"`.

| Min | Show | Say (one line) |
|---|---|---|
| 0–2 | README "What it demonstrates" table | "Every claim links to a test or a results file; this is a lab." |
| 2–4 | `data/sources.yaml`, a fixture `MANIFEST.json`, `lexgrid ingest` run twice | "Registry with licenses; checksummed captures; second run inserts nothing." |
| 4–5 | A chunk text (`BGB > Buch 2 > … > § 355`) | "One chunk per article, identifier inside the text: BM25 can find 'L. 221-18'." |
| 5–7 | `curl /search` for "article L. 221-18", then a cross-lingual query | "Exact references pinned first; dense handles FR→DE." |
| 7–8 | `curl /lineage/<chunk_id>` | "From any hit back to the raw bytes, URL and parser version." |
| 8–10 | FINDINGS table + D2-TYPES-01 | "BM25 owns identifiers, dense owns cross-lingual, hybrid is robust; reranker +0.11 at 3 s." |
| 10–12 | `lexgrid index release --drop-fraction 0.3` → rejected; `index status` | "A regressing index is never promoted; rollback is one alias swap." |
| 12–13 | `curl /search` with the FR key asking for DE → 403 | "Scope comes from the key; leak rate 0 over 4,516 hits." |
| 13–14 | `/ask` with a no-answer question | "Abstains below a threshold chosen by a sweep, with the sample size stated." |
| 14–15 | ADR-001 / backlog #7–#8 | "Bedrock was blocked on a Free plan; open-source models, decision recorded and reversible." |

```bash
H='-H Content-Type:application/json'
curl -s localhost:8000/search $H -H 'X-API-Key: dev-fr' -d '{"query":"article L. 221-18","k":3}' | jq '.hits[].citation_id'
curl -s localhost:8000/search $H -H 'X-API-Key: dev-all' -d '{"query":"délai de remboursement après rétractation en droit allemand","jurisdictions":["DE"],"k":3}' | jq '.hits[].citation_id'
curl -s localhost:8000/search $H -H 'X-API-Key: dev-fr' -d '{"query":"Widerrufsfrist","jurisdictions":["DE"]}' -w '\n%{http_code}\n'
curl -s localhost:8000/ask $H -H 'X-API-Key: dev-fr' -d '{"question":"durée maximale de la période d essai d un CDI"}' | jq '{abstained,reason}'
```
