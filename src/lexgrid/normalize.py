"""Text and legal-identifier normalization. Pure functions, no I/O."""

from __future__ import annotations

import math
import re
import unicodedata

_SPACES = re.compile(r"[\s    ]+")

_ARTICLE_PREFIX = re.compile(r"^\s*(?:artikel|articles?|art\.?|§+|paragraph|section)\s*", flags=re.IGNORECASE)
# "L. 221-18", "L221-18", "R.* 221-1", "D 111-2"
_CODE_NUMBER = re.compile(r"^([LRD])\s*\.?\s*\*?\s*(\d+(?:\s*-\s*\d+)*)$", flags=re.IGNORECASE)
_PLAIN_NUMBER = re.compile(r"^(\d+)\s*([a-z]{0,2})$", flags=re.IGNORECASE)
_ORDINAL_FIRST = {"premier", "1er", "erster", "first"}


def normalize_text(text: str) -> str:
    """NFC, unify exotic spaces, collapse whitespace."""
    return _SPACES.sub(" ", unicodedata.normalize("NFC", text)).strip()


def canonical_article_number(raw: str) -> str:
    """Map surface forms to one canonical number.

    'Art. L. 221-18' == 'article L221-18' -> 'L221-18'; 'Article premier' -> '1';
    '§ 312g' -> '312g'; 'Artikel 17' -> '17'.
    Raises ValueError on anything it cannot recognise (fail loudly, never guess).
    """
    s = _ARTICLE_PREFIX.sub("", normalize_text(raw)).strip().rstrip(".")
    if s.lower() in _ORDINAL_FIRST:
        return "1"
    m = _CODE_NUMBER.match(s)
    if m:
        digits = re.sub(r"\s+", "", m.group(2))
        return f"{m.group(1).upper()}{digits}"
    m = _PLAIN_NUMBER.match(s)
    if m:
        return f"{m.group(1)}{m.group(2).lower()}"
    raise ValueError(f"unrecognised article number: {raw!r}")


def estimate_tokens(text: str) -> int:
    """Cheap, model-agnostic estimate (words x 1.3). Good enough for budgeting, not billing."""
    return math.ceil(len(text.split()) * 1.3)


_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+(?=[A-ZÀ-ÖØ-Þ(\d])")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text)]
    return [p for p in parts if p]
