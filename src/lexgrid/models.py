"""Core data contracts shared by parsers, chunker, store and (later) retrieval."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Jurisdiction = Literal["EU", "FR", "DE"]
DocType = Literal["law", "decree", "code", "case", "directive", "regulation"]


class ArticleUnit(BaseModel):
    """One article (or §) as produced by a parser, before chunking."""

    model_config = ConfigDict(extra="forbid")

    number: str = Field(description="Canonical number, e.g. '17', 'L221-18', '312g'")
    heading: str | None = None
    path: list[str] = Field(default_factory=list, description="Hierarchy above the article")
    paragraphs: list[str]
    valid_from: date | None = None
    valid_to: date | None = None


class NormalizedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    external_id: str
    title: str
    language: str
    doc_type: DocType
    articles: list[ArticleUnit]


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    doc_version_id: str
    chunk_path: str
    article_number: str
    article_key: str = Field(description="Language-independent key, e.g. 'EU:GDPR:17'")
    citation_id: str
    part: int
    n_parts: int
    language: str
    jurisdiction: Jurisdiction
    text: str
    token_count: int
    chunker_version: str
    license: str
    valid_from: date | None = None
    valid_to: date | None = None
