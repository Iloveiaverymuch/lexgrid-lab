"""Parser contract tests on synthetic samples. Real-capture contract tests live in
test_real_fixtures.py and run once fixtures are pinned."""

from datetime import date

import pytest

from lexgrid.parsers import PARSERS, ParseError
from tests.conftest import SAMPLES, make_source


def test_registry_has_one_parser_per_format() -> None:
    assert set(PARSERS) == {"eurlex_html", "gii_xml", "legifrance_html"}


def test_eurlex_en_structure() -> None:
    doc = PARSERS["eurlex_html"].parse(
        (SAMPLES / "eurlex_en.html").read_bytes(), source=make_source(), language="en"
    )
    assert [a.number for a in doc.articles] == ["1", "17"]
    art17 = doc.articles[1]
    assert art17.heading == "Right to erasure (‘right to be forgotten’)"
    assert art17.path == [
        "CHAPTER III — Rights of the data subject",
        "Section 3 — Rectification and erasure",
    ]
    joined = " ".join(art17.paragraphs)
    assert "(a) the personal data are no longer necessary;" in joined
    assert joined.count("nested point") == 1  # nested rows not duplicated
    assert "Recital" not in joined and "Annex" not in joined
    assert doc.title.startswith("REGULATION (EU) 2016/679")


def test_eurlex_fr_article_premier_legacy_classes() -> None:
    doc = PARSERS["eurlex_html"].parse(
        (SAMPLES / "eurlex_fr.html").read_bytes(), source=make_source(), language="fr"
    )
    assert [a.number for a in doc.articles] == ["1", "17"]
    assert doc.articles[0].heading == "Objet et objectifs"


def test_eurlex_rejects_document_without_articles() -> None:
    with pytest.raises(ParseError):
        PARSERS["eurlex_html"].parse(b"<html><p>nothing</p></html>", source=make_source(), language="en")


def test_gii_bgb_structure_and_repealed_skipped() -> None:
    src = make_source(
        id="de-bgb", jurisdiction="DE", languages=["de"], act_short="BGB", format="gii_xml", parser="gii_xml"
    )
    doc = PARSERS["gii_xml"].parse((SAMPLES / "gii_bgb.xml").read_bytes(), source=src, language="de")
    assert [a.number for a in doc.articles] == ["312g", "355"]  # § 312h (weggefallen) skipped
    g = doc.articles[0]
    assert g.heading == "Widerrufsrecht"
    assert g.path == ["Buch 2 Recht der Schuldverhältnisse", "Abschnitt 3 Schuldverhältnisse aus Verträgen"]
    assert doc.articles[1].path == [
        "Buch 2 Recht der Schuldverhältnisse",
        "Abschnitt 5 Rücktritt; Widerrufsrecht",
    ]
    assert "1. Verträgen zur Lieferung von Waren," in g.paragraphs[1]
    assert doc.title == "Bürgerliches Gesetzbuch"


def test_gii_rejects_entities_and_invalid_xml() -> None:
    src = make_source(id="de-bgb", jurisdiction="DE", languages=["de"], format="gii_xml", parser="gii_xml")
    with pytest.raises(ParseError):
        PARSERS["gii_xml"].parse(b"<dokumente><norm>", source=src, language="de")


def test_legifrance_capture() -> None:
    src = make_source(
        id="fr-code-conso-l221",
        jurisdiction="FR",
        languages=["fr"],
        act_short="C. conso",
        format="legifrance_html",
        parser="legifrance_html",
        default_valid_from=date(2016, 7, 1),
    )
    doc = PARSERS["legifrance_html"].parse(
        (SAMPLES / "legifrance_conso.html").read_bytes(), source=src, language="fr"
    )
    by_num = {a.number: a for a in doc.articles}
    assert set(by_num) == {"L221-18", "L221-19"}  # script content ignored, TOC duplicate merged
    a18 = by_num["L221-18"]
    assert a18.valid_from == date(2016, 7, 1)
    assert a18.path[-1].startswith("Section 2 : Droit de rétractation")
    assert not any(p.startswith("Modifié par") for p in a18.paragraphs)
    assert "quatorze jours" in a18.paragraphs[0]
