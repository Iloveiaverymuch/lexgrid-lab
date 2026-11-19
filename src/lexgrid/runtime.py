"""Wiring shared by the CLI, the REST API and the MCP server: one place builds the retrieval stack.

Configuration comes from the environment (no secrets in the repo):
  LEXGRID_DB                 SQLAlchemy URL of the lineage store
  LEXGRID_BACKEND            opensearch | memory          (default opensearch)
  OPENSEARCH_URL             default http://localhost:9200
  LEXGRID_EMBEDDER           bge-m3 | e5 | hash | titan   (default bge-m3, ADR-001)
  LEXGRID_RERANKER           bge-m3 | mminilm | overlap | none (default bge-m3)
  LEXGRID_ABSTAIN_THRESHOLD  float, reranker score below which /ask abstains (default 0.15)
  LEXGRID_API_KEYS           "key:EU,FR;other:DE"  API key -> entitled jurisdictions
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lexgrid.answer import AskService, ExtractiveAnswerer
from lexgrid.embed import build_embedder
from lexgrid.retrieval.base import Mode
from lexgrid.retrieval.rerank import build_reranker
from lexgrid.retrieval.service import RetrievalService
from lexgrid.store import LineageStore

ROOT = Path(__file__).resolve().parents[2]
JURISDICTIONS = ("EU", "FR", "DE")


def parse_keys(spec: str) -> dict[str, tuple[str, ...]]:
    keys: dict[str, tuple[str, ...]] = {}
    for part in filter(None, (p.strip() for p in spec.split(";"))):
        key, _, jurs = part.partition(":")
        scope = tuple(j.strip().upper() for j in jurs.split(",") if j.strip())
        if not key or not scope or any(j not in JURISDICTIONS for j in scope):
            raise ValueError(f"invalid LEXGRID_API_KEYS entry for key ending ...{key[-4:]}")
        keys[key] = scope
    return keys


def entitlements(keys: dict[str, tuple[str, ...]], presented: str | None) -> tuple[str, ...] | None:
    """Constant-time comparison; returns the entitled jurisdictions or None."""
    if not presented:
        return None
    for key, scope in keys.items():
        if hmac.compare_digest(key.encode(), presented.encode()):
            return scope
    return None


@dataclass
class Settings:
    db: str = f"sqlite:///{ROOT / 'var' / 'lexgrid.db'}"
    backend: str = "opensearch"
    opensearch_url: str = "http://localhost:9200"
    embedder: str = "bge-m3"
    reranker: str = "bge-m3"
    abstain_threshold: float = 0.15
    api_keys: dict[str, tuple[str, ...]] = field(default_factory=dict)
    aws_profile: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ
        return cls(
            db=e.get("LEXGRID_DB", cls.db),
            backend=e.get("LEXGRID_BACKEND", cls.backend),
            opensearch_url=e.get("OPENSEARCH_URL", cls.opensearch_url),
            embedder=e.get("LEXGRID_EMBEDDER", cls.embedder),
            reranker=e.get("LEXGRID_RERANKER", cls.reranker),
            abstain_threshold=float(e.get("LEXGRID_ABSTAIN_THRESHOLD", cls.abstain_threshold)),
            api_keys=parse_keys(e.get("LEXGRID_API_KEYS", "")),
            aws_profile=e.get("AWS_PROFILE"),
        )


@dataclass
class Runtime:
    settings: Settings
    store: LineageStore
    retrieval: RetrievalService
    ask: AskService


def build_runtime(settings: Settings) -> Runtime:
    (ROOT / "var").mkdir(exist_ok=True)
    store = LineageStore.from_url(settings.db)
    emb = build_embedder(settings.embedder, cache_dir=ROOT / "var", profile=settings.aws_profile)
    reranker = None if settings.reranker == "none" else build_reranker(settings.reranker)
    backend: Any
    if settings.backend == "memory":
        from lexgrid.retrieval.memory import MemoryBackend

        chunks = store.live_chunks()
        backend = MemoryBackend(chunks, {f"vec_{emb.name}": emb.embed([c["text"] for c in chunks], "passage")})
    else:
        from lexgrid.retrieval.opensearch import OpenSearchBackend, make_client

        backend = OpenSearchBackend(make_client(settings.opensearch_url))
    retrieval = RetrievalService(backend, emb, reranker)
    mode: Mode = "hybrid_rrf_rerank" if reranker else "hybrid_rrf"
    ask = AskService(retrieval, ExtractiveAnswerer(), mode=mode, abstain_threshold=settings.abstain_threshold)
    return Runtime(settings, store, retrieval, ask)
