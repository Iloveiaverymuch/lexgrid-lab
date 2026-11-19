import pytest

from lexgrid.normalize import canonical_article_number, estimate_tokens, normalize_text, split_sentences


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Art. L. 221-18", "L221-18"),
        ("article L221-18", "L221-18"),
        ("Article L. 221 - 18", "L221-18"),
        ("Article premier", "1"),
        ("Article 17", "17"),
        ("Artikel 17", "17"),
        ("§ 312g", "312g"),
        ("§312K", "312k"),
        ("R. 221-1", "R221-1"),
    ],
)
def test_canonical_article_number(raw: str, expected: str) -> None:
    assert canonical_article_number(raw) == expected


@pytest.mark.parametrize("raw", ["Article", "Annex I", "Article seventeen"])
def test_unrecognised_number_fails_loudly(raw: str) -> None:
    with pytest.raises(ValueError):
        canonical_article_number(raw)


def test_normalize_text_nfc_and_spaces() -> None:
    decomposed = "délai de   rétractation\n"
    assert normalize_text(decomposed) == "délai de rétractation"


def test_estimate_tokens_monotonic() -> None:
    assert estimate_tokens("a b c") < estimate_tokens("a b c d e f")


def test_split_sentences_keeps_numbers() -> None:
    assert split_sentences("Le délai est de 14 jours. Il court dès la conclusion.") == [
        "Le délai est de 14 jours.",
        "Il court dès la conclusion.",
    ]


def test_split_sentences_keeps_legal_abbreviations_together() -> None:
    text = "Le délai court selon l'article L. 221-4 dont l'exécution a commencé. Le montant est proportionné."
    assert split_sentences(text) == [
        "Le délai court selon l'article L. 221-4 dont l'exécution a commencé.",
        "Le montant est proportionné.",
    ]
    assert len(split_sentences("Nach § 3 Abs. 2 gilt die Frist. Sie beginnt sofort.")) == 2
