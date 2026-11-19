"""Tier-1 tests are offline by construction: any outbound socket connection fails the test."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from lexgrid.registry import Source
from lexgrid.store import LineageStore

SAMPLES = Path(__file__).parent / "samples"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> None:
        if self.family == socket.AF_UNIX:
            real_connect(self, address)  # type: ignore[arg-type]
            return
        raise RuntimeError(f"network access attempted in an offline test: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield


def make_source(**overrides: object) -> Source:
    base: dict[str, object] = {
        "id": "eu-gdpr",
        "jurisdiction": "EU",
        "languages": ["fr", "en", "de"],
        "act_short": "GDPR",
        "external_id": "CELEX:32016R0679",
        "title": "GDPR",
        "publisher": "EU",
        "license": "test-license",
        "license_url": "https://example.org/license",
        "url": "https://example.org/{lang}",
        "format": "eurlex_html",
        "parser": "eurlex_html",
        "refresh_cadence": "P30D",
        "pii_risk": "low",
        "doc_type": "regulation",
        "default_valid_from": date(2016, 5, 24),
    }
    base.update(overrides)
    return Source.model_validate(base)


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def real_store(tmp_path_factory: pytest.TempPathFactory) -> LineageStore:
    """The pinned real corpus ingested once per test session (SQLite, offline)."""
    from lexgrid.parsers import PARSERS
    from lexgrid.pipeline import ingest
    from lexgrid.registry import load_registry

    store = LineageStore.from_url(f"sqlite:///{tmp_path_factory.mktemp('real') / 'lin.sqlite'}")
    ingest(load_registry(REPO / "data" / "sources.yaml", set(PARSERS)), REPO / "data" / "fixtures", store)
    return store
