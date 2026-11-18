"""Légifrance saved code page (HTML). Markup changes often, so this parser works on text lines.

Assumption to re-check on every new capture: each article starts with a line 'Article L221-1'
and the hierarchy uses lines starting with Livre / Titre / Chapitre / Section / Sous-section.
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from lexgrid.models import ArticleUnit, NormalizedDocument
from lexgrid.normalize import canonical_article_number, normalize_text
from lexgrid.parsers.base import ParseError
from lexgrid.registry import Source

_ART_LINE = re.compile(r"^Article\s+([LRD]\.?\s?\*?\s?\d+(?:-\d+)*)\s*$")
_LEVELS = ["Livre", "Titre", "Chapitre", "Section", "Sous-section", "Paragraphe"]
_LEVEL_LINE = re.compile(r"^(" + "|".join(_LEVELS) + r")\b\s+[^\s]+\s*:\s*\S", re.IGNORECASE)
_VERSION = re.compile(
    r"^(?:Version\s+)?en vigueur depuis le\s+(\d{1,2})(?:er)?\s+([^\s\d]+?)\.?\s+(\d{4})", re.IGNORECASE
)
_LEVEL_RANGE = re.compile(r"\s*\(Articles? [^)]*\)\s*$")
_NOISE_PREFIXES = (
    "Modifié par",
    "Création",
    "Créé par",
    "Version en vigueur",
    "Versions",
    "Liens relatifs",
    "Naviguer dans le sommaire",
    "Masquer",
    "Afficher",
    "Copier le texte",
    "Abrogé",
    "Voir les versions",
    "Comparer les versions",
    "Textes liés",
    "Informations pratiques",
    "Fermer",
    "Déplier/Replier",
    "Ouvrir",
    "Réduire",
    "En vigueur au ",
)
_NOISE_EXACT = {"Code de la consommation"}
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "janvier",
            "février",
            "mars",
            "avril",
            "mai",
            "juin",
            "juillet",
            "août",
            "septembre",
            "octobre",
            "novembre",
            "décembre",
        ]
    )
}


def _parse_fr_date(day: str, month: str, year: str) -> date | None:
    key = month.lower().rstrip(".")
    m = _MONTHS.get(key) or next((v for k, v in _MONTHS.items() if k.startswith(key) and len(key) >= 3), None)
    return date(int(year), m, int(day)) if m else None


class LegifranceHtmlParser:
    name = "legifrance_html"
    version = "1.0.0"

    def parse(self, raw: bytes, *, source: Source, language: str) -> NormalizedDocument:
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()
        for inline in soup.find_all(["a", "span", "strong", "em", "b", "i", "sup", "sub", "abbr"]):
            inline.unwrap()  # inline links would otherwise split sentences across lines
        soup.smooth()
        lines = [normalize_text(t) for t in soup.get_text("\n").split("\n")]
        lines = [ln for ln in lines if ln]

        by_number: dict[str, ArticleUnit] = {}
        path: dict[int, str] = {}
        current: ArticleUnit | None = None

        for line in lines:
            lvl = _LEVEL_LINE.match(line)
            if lvl:
                depth = next(i for i, name in enumerate(_LEVELS) if name.lower() == lvl.group(1).lower())
                path = {k: v for k, v in path.items() if k < depth}
                path[depth] = _LEVEL_RANGE.sub("", line)
                current = None
                continue
            art = _ART_LINE.match(line)
            if art:
                number = canonical_article_number(art.group(1))
                current = ArticleUnit(
                    number=number,
                    path=[path[k] for k in sorted(path)],
                    paragraphs=[],
                    valid_from=source.default_valid_from,
                )
                # Same article can appear in the table of contents and in the body: keep the longest.
                previous = by_number.get(number)
                if previous is None or not previous.paragraphs:
                    by_number[number] = current
                continue
            if current is None:
                continue
            ver = _VERSION.search(line)
            if ver:
                current.valid_from = _parse_fr_date(*ver.groups()) or current.valid_from
                continue
            if line.startswith(_NOISE_PREFIXES) or line in _NOISE_EXACT:
                continue
            current.paragraphs.append(line)

        articles = [a for a in by_number.values() if a.paragraphs]
        if not articles:
            raise ParseError(f"{source.id}: no 'Article Lxxx' blocks found; capture format changed?")
        return NormalizedDocument(
            source_id=source.id,
            external_id=source.external_id,
            title=source.title,
            language=language,
            doc_type=source.doc_type,
            articles=articles,
        )
