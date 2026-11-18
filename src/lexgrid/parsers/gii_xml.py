"""gesetze-im-internet.de XML (gii-norm DTD): one <norm> per § or per structural heading."""

from __future__ import annotations

from typing import Any

from lxml import etree

from lexgrid.models import ArticleUnit, NormalizedDocument
from lexgrid.normalize import canonical_article_number, normalize_text
from lexgrid.parsers.base import ParseError
from lexgrid.registry import Source

_REPEALED = {"-", "(weggefallen)", "weggefallen"}


def _text(el: Any) -> str:
    return normalize_text(" ".join(el.itertext())) if el is not None else ""


class GiiXmlParser:
    name = "gii_xml"
    version = "1.0.0"

    def parse(self, raw: bytes, *, source: Source, language: str) -> NormalizedDocument:
        try:
            root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        except etree.XMLSyntaxError as exc:
            raise ParseError(f"{source.id}: invalid XML: {exc}") from exc

        title = source.title
        path_by_level: dict[int, str] = {}
        articles: list[ArticleUnit] = []

        for norm in root.iter("norm"):
            meta = norm.find("metadaten")
            if meta is None:
                continue
            if title == source.title and meta.find("langue") is not None:
                title = _text(meta.find("langue")) or title
            unit = meta.find("gliederungseinheit")
            if unit is not None:
                code = _text(unit.find("gliederungskennzahl"))
                level = max(1, len(code) // 3)
                label = " ".join(
                    t for t in (_text(unit.find("gliederungsbez")), _text(unit.find("gliederungstitel"))) if t
                )
                path_by_level = {k: v for k, v in path_by_level.items() if k < level}
                path_by_level[level] = label
                continue
            enbez = _text(meta.find("enbez"))
            if not enbez.startswith("§"):
                continue  # Inhaltsübersicht, Anlagen, etc.
            content = norm.find("textdaten/text/Content")
            paragraphs = [_text(p) for p in content.iter("P")] if content is not None else []
            paragraphs = [p for p in paragraphs if p and p not in _REPEALED]
            if not paragraphs:
                continue  # repealed (weggefallen) or empty
            try:
                number = canonical_article_number(enbez)
            except ValueError as exc:
                raise ParseError(f"{source.id}: {exc}") from exc
            heading = _text(meta.find("titel")) or None
            articles.append(
                ArticleUnit(
                    number=number,
                    heading=heading,
                    path=[path_by_level[k] for k in sorted(path_by_level)],
                    paragraphs=paragraphs,
                    valid_from=source.default_valid_from,
                )
            )
        if not articles:
            raise ParseError(f"{source.id}: no § norms found")
        return NormalizedDocument(
            source_id=source.id,
            external_id=source.external_id,
            title=title,
            language=language,
            doc_type=source.doc_type,
            articles=articles,
        )
