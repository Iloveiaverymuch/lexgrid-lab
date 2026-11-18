"""Lineage store (SQLAlchemy Core). Postgres in Compose; SQLite for offline tests.

Idempotency comes from content-addressed ids + insert-or-ignore: re-running on unchanged input
inserts nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
    update,
)
from sqlalchemy.dialects import postgresql, sqlite

from lexgrid.models import Chunk
from lexgrid.registry import Source

metadata = MetaData()

sources_t = Table(
    "sources",
    metadata,
    Column("id", String, primary_key=True),
    Column("jurisdiction", String(2), nullable=False),
    Column("languages", JSON, nullable=False),
    Column("act_short", String, nullable=False),
    Column("license", Text, nullable=False),
    Column("license_url", Text, nullable=False),
    Column("format", String, nullable=False),
    Column("parser", String, nullable=False),
    Column("refresh_cadence", String, nullable=False),
    Column("pii_risk", String, nullable=False),
)

documents_t = Table(
    "documents",
    metadata,
    Column("id", String, primary_key=True),
    Column("source_id", String, ForeignKey("sources.id"), nullable=False),
    Column("external_id", String, nullable=False),
    Column("language", String, nullable=False),
    Column("doc_type", String, nullable=False),
    Column("title", Text, nullable=False),
    UniqueConstraint("source_id", "external_id", "language"),
)

doc_versions_t = Table(
    "doc_versions",
    metadata,
    Column("id", String, primary_key=True),
    Column("document_id", String, ForeignKey("documents.id"), nullable=False),
    Column("content_sha256", String(64), nullable=False),
    Column("raw_uri", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("parser_name", String, nullable=False),
    Column("parser_version", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("superseded_by", String, nullable=True),
)

chunks_t = Table(
    "chunks",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("doc_version_id", String, ForeignKey("doc_versions.id"), nullable=False, index=True),
    Column("chunk_path", Text, nullable=False),
    Column("article_number", String, nullable=False),
    Column("article_key", String, nullable=False, index=True),
    Column("citation_id", String, nullable=False),
    Column("part", Integer, nullable=False),
    Column("n_parts", Integer, nullable=False),
    Column("language", String, nullable=False),
    Column("jurisdiction", String(2), nullable=False, index=True),
    Column("text", Text, nullable=False),
    Column("token_count", Integer, nullable=False),
    Column("chunker_version", String, nullable=False),
    Column("license", Text, nullable=False),
    Column("valid_from", Date, nullable=True),
    Column("valid_to", Date, nullable=True),
)

index_runs_t = Table(
    "index_runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("jurisdiction", String(2), nullable=False),
    Column("index_name", String, nullable=False),
    Column("corpus_snapshot_sha", String(64), nullable=False),
    Column("embedding_model", String, nullable=False),
    Column("chunker_version", String, nullable=False),
    Column("n_docs", Integer, nullable=False),
    Column("n_chunks", Integer, nullable=False),
    Column("duration_s", Float, nullable=False),
    Column("eval_run_id", String, nullable=True),
    Column("status", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("promoted_at", DateTime(timezone=True), nullable=True),
)

eval_runs_t = Table(
    "eval_runs",
    metadata,
    Column("run_id", String, nullable=False),
    Column("index_run_id", String, nullable=True),
    Column("mode", String, nullable=False),
    Column("metric", String, nullable=False),
    Column("k", Integer, nullable=True),
    Column("value", Float, nullable=False),
    Column("ci_low", Float, nullable=True),
    Column("ci_high", Float, nullable=True),
    Column("n_queries", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def _short_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


@dataclass(frozen=True)
class VersionResult:
    id: str
    created: bool


class LineageStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata.create_all(engine)

    @classmethod
    def from_url(cls, url: str) -> LineageStore:
        return cls(create_engine(url, future=True))

    def _insert_ignore(self, table: Table, rows: Sequence[dict[str, Any]], key: str) -> int:
        if not rows:
            return 0
        dialect = self.engine.dialect.name
        mod: Any = postgresql if dialect == "postgresql" else sqlite
        stmt = mod.insert(table).values(list(rows)).on_conflict_do_nothing(index_elements=[key])
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
            return int(result.rowcount or 0)

    def upsert_source(self, s: Source) -> None:
        row = {
            "id": s.id,
            "jurisdiction": s.jurisdiction,
            "languages": s.languages,
            "act_short": s.act_short,
            "license": s.license,
            "license_url": str(s.license_url),
            "format": s.format,
            "parser": s.parser,
            "refresh_cadence": s.refresh_cadence,
            "pii_risk": s.pii_risk,
        }
        with self.engine.begin() as conn:
            existing = conn.execute(select(sources_t).where(sources_t.c.id == s.id)).mappings().first()
            if existing is None:
                conn.execute(sources_t.insert().values(**row))
            elif dict(existing) != row:
                conn.execute(update(sources_t).where(sources_t.c.id == s.id).values(**row))

    def upsert_document(self, *, source: Source, language: str, title: str) -> str:
        doc_id = _short_hash(source.id, source.external_id, language)
        self._insert_ignore(
            documents_t,
            [
                {
                    "id": doc_id,
                    "source_id": source.id,
                    "external_id": source.external_id,
                    "language": language,
                    "doc_type": source.doc_type,
                    "title": title,
                }
            ],
            "id",
        )
        return doc_id

    def add_version(
        self,
        *,
        document_id: str,
        content_sha256: str,
        raw_uri: str,
        source_url: str,
        fetched_at: datetime,
        parser_name: str,
        parser_version: str,
    ) -> VersionResult:
        vid = _short_hash(document_id, content_sha256, parser_name, parser_version)
        created = (
            self._insert_ignore(
                doc_versions_t,
                [
                    {
                        "id": vid,
                        "document_id": document_id,
                        "content_sha256": content_sha256,
                        "raw_uri": raw_uri,
                        "source_url": source_url,
                        "fetched_at": fetched_at,
                        "parser_name": parser_name,
                        "parser_version": parser_version,
                        "created_at": datetime.now(tz=UTC),
                    }
                ],
                "id",
            )
            == 1
        )
        if created:  # tombstone previous live versions of the same document
            with self.engine.begin() as conn:
                conn.execute(
                    update(doc_versions_t)
                    .where(doc_versions_t.c.document_id == document_id)
                    .where(doc_versions_t.c.id != vid)
                    .where(doc_versions_t.c.superseded_by.is_(None))
                    .values(superseded_by=vid)
                )
        return VersionResult(vid, created)

    def add_chunks(self, chunks: Iterable[Chunk]) -> int:
        rows = [c.model_dump() for c in chunks]
        inserted = 0
        for i in range(0, len(rows), 500):
            inserted += self._insert_ignore(chunks_t, rows[i : i + 500], "id")
        return inserted

    def live_chunks(self, jurisdiction: str | None = None) -> list[dict[str, Any]]:
        """Chunks of non-superseded versions: what an index build should contain."""
        q = (
            select(chunks_t, documents_t.c.doc_type)
            .join(doc_versions_t, chunks_t.c.doc_version_id == doc_versions_t.c.id)
            .join(documents_t, doc_versions_t.c.document_id == documents_t.c.id)
            .where(doc_versions_t.c.superseded_by.is_(None))
        )
        if jurisdiction:
            q = q.where(chunks_t.c.jurisdiction == jurisdiction)
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(q.order_by(chunks_t.c.id)).mappings()]

    def lineage(self, chunk_id: str) -> dict[str, Any] | None:
        q = (
            select(
                chunks_t.c.id.label("chunk_id"),
                chunks_t.c.citation_id,
                chunks_t.c.chunk_path,
                chunks_t.c.chunker_version,
                chunks_t.c.license,
                doc_versions_t.c.id.label("doc_version_id"),
                doc_versions_t.c.content_sha256,
                doc_versions_t.c.raw_uri,
                doc_versions_t.c.source_url,
                doc_versions_t.c.fetched_at,
                doc_versions_t.c.parser_name,
                doc_versions_t.c.parser_version,
                doc_versions_t.c.superseded_by,
                documents_t.c.source_id,
                documents_t.c.external_id,
                documents_t.c.language,
            )
            .join(doc_versions_t, chunks_t.c.doc_version_id == doc_versions_t.c.id)
            .join(documents_t, doc_versions_t.c.document_id == documents_t.c.id)
            .where(chunks_t.c.id == chunk_id)
        )
        with self.engine.connect() as conn:
            row = conn.execute(q).mappings().first()
        return dict(row) if row else None

    # --- index runs -------------------------------------------------------------------------
    def add_index_run(self, row: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(index_runs_t.insert().values(**row))

    def set_index_run_status(self, run_id: str, status: str, *, promoted: bool = False) -> None:
        values: dict[str, Any] = {"status": status}
        if promoted:
            values["promoted_at"] = datetime.now(tz=UTC)
        with self.engine.begin() as conn:
            conn.execute(update(index_runs_t).where(index_runs_t.c.run_id == run_id).values(**values))

    def index_runs(self, jurisdiction: str) -> list[dict[str, Any]]:
        q = (
            select(index_runs_t)
            .where(index_runs_t.c.jurisdiction == jurisdiction)
            .order_by(index_runs_t.c.created_at)
        )
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(q).mappings()]

    def add_eval_rows(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            with self.engine.begin() as conn:
                conn.execute(eval_runs_t.insert(), rows)

    def counts(self) -> dict[str, int]:
        with self.engine.connect() as conn:
            return {
                t.name: int(conn.execute(select(func.count()).select_from(t)).scalar_one())
                for t in (sources_t, documents_t, doc_versions_t, chunks_t)
            }
