"""Parser interface (Strategy pattern): one class per source format."""

from __future__ import annotations

from typing import Protocol

from lexgrid.models import NormalizedDocument
from lexgrid.registry import Source


class ParseError(ValueError):
    """Raised when a raw file does not match the structure its parser expects."""


class Parser(Protocol):
    name: str
    version: str

    def parse(self, raw: bytes, *, source: Source, language: str) -> NormalizedDocument: ...
