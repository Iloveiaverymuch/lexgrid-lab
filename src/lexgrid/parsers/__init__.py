from lexgrid.parsers.base import ParseError, Parser
from lexgrid.parsers.eurlex_html import EurLexHtmlParser
from lexgrid.parsers.gii_xml import GiiXmlParser
from lexgrid.parsers.legifrance_html import LegifranceHtmlParser

PARSERS: dict[str, Parser] = {p.name: p for p in (EurLexHtmlParser(), GiiXmlParser(), LegifranceHtmlParser())}

__all__ = ["PARSERS", "ParseError", "Parser"]
