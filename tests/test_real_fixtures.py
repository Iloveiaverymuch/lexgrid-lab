"""Contract tests on the pinned real captures. Skipped per source until its fixture is pinned."""

from collections import Counter
from pathlib import Path

import pytest

from lexgrid.chunking import chunk_document
from lexgrid.parsers import PARSERS
from lexgrid.registry import load_manifest, load_registry

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "data" / "fixtures"
SOURCES = {s.id: s for s in load_registry(REPO / "data" / "sources.yaml", set(PARSERS))}

# Known structural facts about the real acts (independent of our parser).
EXPECTED_ARTICLES = {"eu-gdpr": 99, "eu-crd": 35}
MUST_CONTAIN = {
    ("eu-gdpr", "17"): {"en": "erasure", "fr": "effacement", "de": "Löschung"},
    ("eu-crd", "9"): {"en": "14 days", "fr": "quatorze jours", "de": "14 Tagen"},
    ("de-bgb", "355"): {"de": "Widerruf"},
    ("fr-code-conso-l221", "L221-18"): {"fr": "quatorze jours"},
}


def _docs(source_id: str) -> list[tuple[str, object]]:
    m = load_manifest(FIXTURES, source_id)
    if not m.files:
        pytest.skip(f"{source_id}: no pinned fixture yet")
    src = SOURCES[source_id]
    return [
        (
            f.language,
            PARSERS[src.parser].parse(
                (FIXTURES / source_id / f.path).read_bytes(), source=src, language=f.language
            ),
        )
        for f in m.files
    ]


@pytest.mark.parametrize("source_id", sorted(SOURCES))
def test_real_capture_contract(source_id: str) -> None:
    src = SOURCES[source_id]
    for language, doc in _docs(source_id):
        numbers = [a.number for a in doc.articles]  # type: ignore[attr-defined]
        assert numbers, f"{source_id}/{language}: no articles"
        assert not [n for n, c in Counter(numbers).items() if c > 1], "duplicate article numbers"
        if source_id in EXPECTED_ARTICLES:
            assert len(numbers) == EXPECTED_ARTICLES[source_id]
        chunks = chunk_document(doc, source=src, doc_version_id="v")  # type: ignore[arg-type]
        assert all(c.article_number in c.text for c in chunks)
        assert all(c.token_count <= 470 for c in chunks)


@pytest.mark.parametrize(("key", "expected"), sorted(MUST_CONTAIN.items()))
def test_known_article_content(key: tuple[str, str], expected: dict[str, str]) -> None:
    source_id, number = key
    for language, doc in _docs(source_id):
        if language not in expected:
            continue
        art = next(a for a in doc.articles if a.number == number)  # type: ignore[attr-defined]
        assert expected[language] in " ".join(art.paragraphs), f"{source_id} {number} {language}"


@pytest.mark.parametrize("source_id", ["eu-gdpr", "eu-crd"])
def test_eu_languages_are_aligned(source_id: str) -> None:
    by_lang = {lang: [a.number for a in doc.articles] for lang, doc in _docs(source_id)}  # type: ignore[attr-defined]
    assert len({tuple(v) for v in by_lang.values()}) == 1, "article numbering differs across languages"
