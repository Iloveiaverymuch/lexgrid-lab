# Demo — 15-minute tour with real use cases

Status: ACTIVE · Last updated: 2026-11-19 · Next action: rehearse twice with a timer; note any result that differs from "Expected"

"Expected" below comes from the golden-set labels and the recorded runs ([FINDINGS](../evals/FINDINGS.md)).
If a live result differs, say so and use it: the system is a lab, and explaining a miss is part of the demo.

## Before the call (5 min)

```bash
cd ~/Documents/Work/AI/"AI Formation"/lexgrid-lab
docker compose -f infra/docker-compose.yml up -d --wait
export LEXGRID_DB=postgresql+psycopg://lexgrid:lexgrid@localhost:5432/lexgrid
LEXGRID_API_KEYS="dev-fr:FR;dev-all:EU,FR,DE" uv run lexgrid serve
```
- Open http://127.0.0.1:8000/, connect with `dev-all`, run one search (the first query loads the models, ~10 s).
- Second terminal tab in the repo with `LEXGRID_DB` exported, ready for the gate demo.
- Tabs open: the console, the README on GitHub, [ADR-001](adr/ADR-001-open-source-embeddings-and-reranker.md).

## The story in one sentence
"A legal publisher's AI is only as good as its raw material: I built the pipeline that turns three countries'
law into versioned, measured, isolated search, and every claim you'll see is backed by a test or a results file."

## Tour (15 min)

| Min | Where | Do | Point out |
|---|---|---|---|
| 0–1 | README | Scroll "What it demonstrates" and "Results" | Lab scope, evidence links, sample sizes next to every number |
| 1–3 | Search, `dev-all`, Hybrid | **Use case 1** (article number) | Article placed first and labelled "you named it"; margin citation with in-force date |
| 3–4 | Same result | Trace source | Chain hit → chunk → version → raw file SHA-256 → official URL; parser version recorded |
| 4–6 | Search, Compare all four | **Use case 2** (paraphrase), point at L221-18 in each column | Each ranking places it differently; the reranker reorders the hybrid list |
| 6–7 | Search, Hybrid + rerank | **Use case 3** (French question, German law) | Cross-lingual: BM25 0.16 vs dense 0.76 nDCG on this kind of question (n = 6) |
| 7–8 | Search, Hybrid + rerank | **Use case 4** (three countries) | One article per country; comparative questions need every entitled jurisdiction |
| 8–10 | Evaluation, D2-EVAL-BGEM3-01 | Read the by-kind table | Why hybrid: BM25 owns identifiers, dense owns other languages; reranker +0.11 at ~3 s |
| 10–12 | Terminal, then Indexes | Gate demo (below) | A build missing 30% of chunks is rejected; live alias untouched; rejected row visible |
| 12–13 | Search, key `dev-fr` | **Use case 9** (outside your scope) | 403 from the server; the key decides scope; leak rate 0 over 4,516 hits |
| 13–14 | Ask, `dev-all` | **Use case 6**, then **use case 10** | Quotes with citations; then abstains on a question the corpus cannot answer |
| 14–15 | ADR-001 | — | Bedrock blocked on a Free plan; open-source models, recorded and reversible |

Gate demo (second terminal):
```bash
uv run lexgrid index release --models bge-m3,e5 --drop-fraction 0.3   # expect "promoted": false, exit code 3
uv run lexgrid index status | tail -3
```
Then refresh the Indexes view: the three new builds show as `rejected`; the promoted ones are unchanged.

## Use-case library (prompts to test)

Pick by audience. Each row says which key, view and ranking to use, and what a correct result looks like.

### Consumer law team at an e-commerce company

| # | Prompt | Key / view / ranking | Expected | What it shows |
|---|---|---|---|---|
| 1 | `article L. 221-18 code de la consommation` | `dev-all`, Search, Hybrid, FR only | C. conso art. L221-18 first, labelled "you named it" | Identifiers in the indexed text; exact references pinned |
| 2 | `combien de jours a le consommateur pour se rétracter après un achat en ligne ?` | `dev-all`, Search, Compare all four, FR only | L221-18; L221-19 / L221-20 related | Paraphrase without the legal vocabulary; ranking differences |
| 3 | `délai de remboursement après rétractation en droit allemand` | `dev-all`, Search, Hybrid + rerank, DE only | BGB § 357 (refund); § 355 related | French question, German statute. **Known weak spot:** the recorded run ranked § 357b first; explain confusable articles |
| 4 | `exceptions to the right of withdrawal for personalised goods` | `dev-all`, Search, Hybrid + rerank, all three | CRD art. 16, C. conso L221-28, BGB § 312g | Same rule across EU directive and its transpositions |
| 5 | `Muss ein Online-Shop eine Schaltfläche zum Widerrufen anbieten?` | `dev-all`, Search, Hybrid + rerank, DE only | BGB § 356a (electronic withdrawal function) | Recent provision found by meaning, not keywords |
| 6 | `combien de jours pour se rétracter après un achat en ligne ?` | `dev-all`, Ask | Quotes CRD art. 9 / L221-18 with citations | Cited, extractive answer; every line traceable |

### Data protection officer

| # | Prompt | Key / view / ranking | Expected | What it shows |
|---|---|---|---|---|
| 7 | `within how many hours must a controller notify a personal data breach to the authority?` | `dev-all`, Ask (or Search, EU only) | GDPR art. 33 (72 hours); art. 34 related | Answer quoted from the article itself |
| 8 | `from what age can a child consent alone to an online service processing their data?` | `dev-all`, Search, Hybrid + rerank, EU only | GDPR art. 8 | Paraphrase in plain English |
| 8b | `Art. 17 DSGVO Recht auf Löschung` | `dev-all`, Search, Hybrid, EU only | GDPR art. 17 first | German citation style, EU act, results in three languages collapsed to one article |
| 8c | `can I get a copy of my personal data in a machine-readable format to move it to another provider?` | `dev-all`, Search, Compare all four, EU only | GDPR art. 20; art. 15 related | Dense beats keywords on everyday wording |

### Platform and security (the "search as a product" audience)

| # | Prompt | Key / view / ranking | Expected | What it shows |
|---|---|---|---|---|
| 9 | `Widerrufsfrist 14 Tage` with DE selected | `dev-fr`, Search ("Outside your scope" example) | "Refused by the server: not entitled to DE" | Scope from the key; widening refused, never silently dropped |
| 9b | Any query, then Trace source on a result | `dev-fr` | Lineage shown for FR chunks only | Lineage of another country's chunk returns 404 (no existence leak) |
| 10 | `durée maximale de la période d'essai d'un CDI` | `dev-all`, Ask | Not answered; reason shows score vs threshold 0.15 | Abstention: labour code is not in the corpus |
| 11 | `informations précontractuelles à fournir avant un contrat à distance`, then set **In force on** = 2025-01-01 | `dev-all`, Search, all three | L221-5 present today, gone for 2025-01-01 | As-of filtering. **Limit:** the corpus holds only the current French version, so the older text is missing rather than shown (backlog #1–#2) |
| 12 | Gate demo above | Terminal + Indexes | Rejected build, alias unchanged | Eval-gated releases and instant rollback (`lexgrid index rollback --jurisdiction FR`) |

### More prompts to probe the system yourself
- `refund deadline after withdrawal` (all three): CRD art. 13, L221-24, BGB § 357. Recorded run put CRD art. 14 first: a related article on the consumer's return duty.
- `Ausnahmen vom Widerrufsrecht für versiegelte Waren` (FR only): German question, French answer L221-28. Recorded run missed at rank 1 and the reranker score fell below the threshold: a good example of abstention catching a likely wrong answer.
- `is a trader allowed to charge a surcharge for paying by credit card?` (EU): CRD art. 19.
- `maximum administrative fine for infringing the data protection rules` (EU): GDPR art. 83.
- `Mindestlohn pro Stunde in Deutschland` (DE, Ask): should abstain (minimum-wage law not in corpus).

## Questions to expect, and where the answer is

| Question | Answer in one line | Evidence |
|---|---|---|
| Why hybrid and not just embeddings? | Dense drops to ~0.5 nDCG on article numbers; BM25 to 0.16 across languages | FINDINGS D2-TYPES-01 |
| How do you know a new index is not worse? | Golden set on candidate vs live, paired, promote only within tolerance | D3-GATE-01/02, `gate.py` |
| How sure are these numbers? | 30 questions, bootstrap intervals shown, labels pending human review | Evaluation view, README |
| How do you stop one country's data leaking? | Scope from the key; aliases per country plus a filter; 0 leaks over 4,516 hits | D3-LEAK-01 |
| Prompt injection in source documents? | Screened at ingest and quarantined; 0 false positives on 3,224 real chunks | D3-SCREEN-01, `screen.py` |
| Why not Bedrock / Knowledge Bases? | Blocked on the Free plan; own pipeline needed for versioning and lineage anyway | ADR-001, ADR-002 |
| What would you do next? | Reranker latency (p95 12 s), weighted fusion, larger reviewed golden set, scale test | RETRIEVAL_DECISIONS, backlog |

## Fallback without the UI
```bash
curl -s localhost:8000/search -H 'Content-Type: application/json' -H 'X-API-Key: dev-fr' \
  -d '{"query":"article L. 221-18","k":3}' | python3 -m json.tool | grep citation_id
curl -s localhost:8000/ask -H 'Content-Type: application/json' -H 'X-API-Key: dev-all' \
  -d '{"question":"durée maximale de la période d essai d un CDI"}' | python3 -m json.tool | head -4
```
