"""Ingest step: fixtures -> parse -> normalize -> chunk -> lineage store.

Each step is a plain function so any orchestrator (Airflow, Prefect, cron) can wrap it.
`dry_run=True` parses and chunks but writes nothing (no side effects, by test).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lexgrid.chunking import chunk_document
from lexgrid.parsers import PARSERS
from lexgrid.registry import Source, load_manifest, sha256_bytes
from lexgrid.screen import screen
from lexgrid.store import LineageStore


@dataclass
class SourceReport:
    source_id: str
    files: int = 0
    articles: int = 0
    chunks: int = 0
    new_versions: int = 0
    new_chunks: int = 0
    max_tokens: int = 0
    split_articles: int = 0
    quarantined: int = 0
    languages: list[str] = field(default_factory=list)


class IntegrityError(RuntimeError):
    pass


def ingest(
    sources: list[Source],
    fixtures_root: Path,
    store: LineageStore | None,
    *,
    dry_run: bool = False,
) -> list[SourceReport]:
    if not dry_run and store is None:
        raise ValueError("a store is required unless dry_run=True")
    reports: list[SourceReport] = []
    for source in sources:
        if not source.enabled:
            continue
        rep = SourceReport(source.id)
        parser = PARSERS[source.parser]
        manifest = load_manifest(fixtures_root, source.id)
        if store is not None and not dry_run:
            store.upsert_source(source)
        for entry in manifest.files:
            path = fixtures_root / source.id / entry.path
            raw = path.read_bytes()
            if sha256_bytes(raw) != entry.sha256:
                raise IntegrityError(f"{source.id}/{entry.path}: checksum mismatch, refusing to ingest")
            doc = parser.parse(raw, source=source, language=entry.language)
            rep.files += 1
            rep.articles += len(doc.articles)
            rep.languages.append(entry.language)

            if dry_run or store is None:
                version_id = f"dry-{entry.sha256[:12]}"
            else:
                doc_id = store.upsert_document(source=source, language=entry.language, title=doc.title)
                v = store.add_version(
                    document_id=doc_id,
                    content_sha256=entry.sha256,
                    raw_uri=str(path.relative_to(fixtures_root.parent)),
                    source_url=entry.url,
                    fetched_at=entry.fetched_at,
                    parser_name=parser.name,
                    parser_version=parser.version,
                )
                version_id = v.id
                rep.new_versions += int(v.created)

            chunks = chunk_document(doc, source=source, doc_version_id=version_id)
            rep.chunks += len(chunks)
            rep.max_tokens = max([rep.max_tokens, *(c.token_count for c in chunks)])
            rep.split_articles += len({c.article_key for c in chunks if c.n_parts > 1})
            flagged = {c.id: r for c in chunks if (r := screen(c.text))}
            rep.quarantined += len(flagged)
            if store is not None and not dry_run:
                rep.new_chunks += store.add_chunks(chunks)  # kept for lineage/audit...
                store.quarantine(flagged)  # ...but never served or indexed
        reports.append(rep)
    return reports
