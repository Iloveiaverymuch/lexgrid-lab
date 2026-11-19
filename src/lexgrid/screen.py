"""Ingest-time screening: instruction-like text never reaches an authoritative index.

Lesson learned: a reranker can push a poisoned passage to rank 1, so delimiters at prompt time are not enough.
Chunks matching these patterns are written to the `quarantine` table and excluded from `live_chunks()`.
Patterns are deliberately narrow (legal texts must not be false positives; checked on the real corpus).
"""

from __future__ import annotations

import re

_EMAIL_OR_URL = r"([\w.+-]+@[\w-]+\.[\w.]+|https?://\S+)"

_PATTERNS: dict[str, re.Pattern[str]] = {
    # EN / FR / DE: "ignore previous instructions", "ignorez les instructions précédentes",
    # "vergiss alle vorherigen Anweisungen"
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all)\b.{0,20}\b(instructions?|prompts?|rules)\b"
        r"|\b(ignore[zr]?|oublie[zr]?)\b.{0,30}\b(instructions?|consignes?|r[eè]gles)\b.{0,20}"
        r"\b(pr[eé]c[eé]dentes?|ci-dessus|ant[eé]rieures?)\b"
        r"|\b(vergiss|vergessen sie|ignorier(e|en sie)?)\b.{0,40}\b(anweisungen|instruktionen|regeln)\b",
        re.IGNORECASE,
    ),
    # "act as" was dropped: GDPR Art. 39 says the DPO shall "act as the contact point" (false positive).
    "role_hijack": re.compile(
        r"\b(system prompt|you are now (an?|the|my)\b|new instructions:|prompt syst[eè]me|systemprompt)",
        re.IGNORECASE,
    ),
    "exfiltration": re.compile(
        r"\b(send|email|e-mail|forward|upload|post|envo(ie|ye)[zr]?|transf[eè]re[zr]?|sende[nt]?|schick(e|en)?)\b"
        r".{0,60}" + _EMAIL_OR_URL,
        re.IGNORECASE,
    ),
    "markup_injection": re.compile(r"<\s*(script|iframe)\b|javascript:", re.IGNORECASE),
}


def screen(text: str) -> list[str]:
    """Return the names of the patterns that match (empty list = clean)."""
    return [name for name, pat in _PATTERNS.items() if pat.search(text)]
