"""EUR-Lex HTML (Official Journal layout, both legacy `ti-art` and current `oj-ti-art` classes)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from lexgrid.models import ArticleUnit, NormalizedDocument
from lexgrid.normalize import canonical_article_number, normalize_text
from lexgrid.parsers.base import ParseError
from lexgrid.registry import Source

_ART = {"ti-art", "oj-ti-art"}
_ART_SUB = {"sti-art", "oj-sti-art"}
_SEC_LABEL = {"ti-section-1", "oj-ti-section-1"}
_SEC_TITLE = {"ti-section-2", "oj-ti-section-2"}
_DOC_TITLE = {"doc-ti", "oj-doc-ti"}
_NOTE = {"note", "oj-note"}
_CHAPTER = re.compile(r"^(chapter|chapitre|kapitel|title|titre|titel)\b", re.IGNORECASE)
_QUOTES = set("„“”‘’\"«»'")
_ANNEX = re.compile(r"^(annex|annexe|anhang)\b", re.IGNORECASE)


def _classes(el: Tag) -> set[str]:
    cls = el.get("class")
    if cls is None:
        return set()
    return set(cls) if isinstance(cls, list) else {str(cls)}


class EurLexHtmlParser:
    name = "eurlex_html"
    version = "1.1.0"

    def parse(self, raw: bytes, *, source: Source, language: str) -> NormalizedDocument:
        soup = BeautifulSoup(raw, "lxml")
        title_el = next((p for p in soup.find_all("p") if _classes(p) & _DOC_TITLE), None)
        title = normalize_text(title_el.get_text(" ")) if title_el else source.title

        articles: list[ArticleUnit] = []
        chapter: str | None = None
        section: str | None = None
        pending_label: tuple[str, str] | None = None  # (level, label) awaiting its title line
        current: ArticleUnit | None = None
        expect_heading = False

        for el in soup.find_all(["p", "tr"]):
            if el.name == "p" and el.find_parent("table") is not None:
                continue  # table content is emitted row by row
            if el.name == "tr" and el.find_parent("tr") is not None:
                continue  # nested list rows are included in their outer row
            cls = _classes(el) if el.name == "p" else set()
            text = normalize_text(el.get_text(" "))
            if not text:
                continue

            if cls & _NOTE:
                continue  # footnotes (OJ references), not normative text
            if articles and cls & _DOC_TITLE:
                break  # a new document title after the articles = annexes start
            if cls & _SEC_LABEL:
                if _ANNEX.match(text):
                    break  # annexes are out of scope for article chunking
                level = "chapter" if _CHAPTER.match(text) else "section"
                pending_label = (level, text)
                if level == "chapter":
                    chapter, section = text, None
                else:
                    section = text
                current = None
                continue
            if cls & _SEC_TITLE and pending_label is not None:
                level, label = pending_label
                full = f"{label} — {text}"
                if level == "chapter":
                    chapter = full
                else:
                    section = full
                pending_label = None
                continue
            if cls & _ART and text[0] in _QUOTES:
                # Quoted article inside an amending provision ("„Artikel 8a ..."): text of the
                # current article, not a new article of this act.
                if current is not None:
                    current.paragraphs.append(text)
                continue
            if cls & _ART:
                try:
                    number = canonical_article_number(text)
                except ValueError as exc:
                    raise ParseError(f"{source.id}/{language}: {exc}") from exc
                current = ArticleUnit(
                    number=number,
                    path=[p for p in (chapter, section) if p],
                    paragraphs=[],
                    valid_from=source.default_valid_from,
                )
                articles.append(current)
                expect_heading = True
                continue
            if current is None:
                continue  # recitals, preamble, headers before Article 1
            if expect_heading and cls & _ART_SUB:
                current.heading = text
                expect_heading = False
                continue
            expect_heading = False
            current.paragraphs.append(text)

        articles = [a for a in articles if a.paragraphs]
        if not articles:
            raise ParseError(f"{source.id}/{language}: no articles found")
        return NormalizedDocument(
            source_id=source.id,
            external_id=source.external_id,
            title=title,
            language=language,
            doc_type=source.doc_type,
            articles=articles,
        )
