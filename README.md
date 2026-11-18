# lexgrid-lab

A 3-day **lab** on multi-jurisdiction legal retrieval: ingestion with lineage, versioned hybrid indexes,
and measured retrieval quality. **Not legal advice, not a product.** Scope and limits are stated below.

## Status
Day 1 (data plane) done; Day 2 (retrieval + evaluation) next. See [docs/STATE.md](docs/STATE.md) and [docs/LAB_PLAN.md](docs/LAB_PLAN.md).

## Corpus
Consumer-contract law across the EU (GDPR, Consumer Rights Directive in FR/EN/DE), France
(Code de la consommation L221-x) and Germany (BGB). Licenses are recorded per source in
[data/sources.yaml](data/sources.yaml) and copied onto every chunk.

## Run
```bash
uv sync
uv run scripts/verify.py            # offline gate, < 60 s
uv run lexgrid ingest --dry-run     # parse + chunk, writes nothing
uv run lexgrid ingest               # SQLite lineage store in var/
```
More commands in [AGENTS.md](AGENTS.md).

## Results
None yet. Every number will be in [evals/FINDINGS.md](evals/FINDINGS.md) with its run id and sample size.

## Known limits
[docs/RELIABILITY_BACKLOG.md](docs/RELIABILITY_BACKLOG.md).
