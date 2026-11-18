"""Legal-structure chunking: one chunk per article; only long articles are split, on paragraph
then sentence boundaries, with sentence overlap. The article number is always in the chunk text
(BM25 cannot find an identifier that is not in the indexed text)."""

from __future__ import annotations

import hashlib

from lexgrid.models import ArticleUnit, Chunk, NormalizedDocument
from lexgrid.normalize import estimate_tokens, split_sentences
from lexgrid.registry import Source

CHUNKER_VERSION = "article-v1"

_LABEL = {
    ("EU", "fr"): "Article",
    ("EU", "en"): "Article",
    ("EU", "de"): "Artikel",
    ("FR", "fr"): "Article",
    ("DE", "de"): "§",
}


def article_label(jurisdiction: str, language: str) -> str:
    return _LABEL.get((jurisdiction, language), "Article")


def citation_id(source: Source, article: ArticleUnit) -> str:
    """Language-independent, human-readable id, e.g. [FR:C. conso art. L221-18 @2016-07-01]."""
    sym = "§" if source.jurisdiction == "DE" else "art."
    date_part = f" @{article.valid_from.isoformat()}" if article.valid_from else ""
    return f"[{source.jurisdiction}:{source.act_short} {sym} {article.number}{date_part}]"


def _hard_split(text: str, budget: int) -> list[str]:
    words = text.split()
    step = max(1, int(budget / 1.3))
    return [" ".join(words[i : i + step]) for i in range(0, len(words), step)]


def _split_long(paragraphs: list[str], budget: int, overlap_sentences: int) -> list[list[str]]:
    units: list[str] = []
    for p in paragraphs:
        if estimate_tokens(p) <= budget:
            units.append(p)
            continue
        for sentence in split_sentences(p):
            units.extend([sentence] if estimate_tokens(sentence) <= budget else _hard_split(sentence, budget))
    parts: list[list[str]] = []
    cur: list[str] = []
    cur_tokens = 0
    for u in units:
        t = estimate_tokens(u)
        if cur and cur_tokens + t > budget:
            parts.append(cur)
            tail = split_sentences(cur[-1])[-overlap_sentences:] if overlap_sentences else []
            tail_tokens = sum(estimate_tokens(x) for x in tail)
            cur, cur_tokens = (list(tail), tail_tokens) if tail_tokens + t <= budget else ([], 0)
        cur.append(u)
        cur_tokens += t
    if cur:
        parts.append(cur)
    return parts


def chunk_document(
    doc: NormalizedDocument,
    *,
    source: Source,
    doc_version_id: str,
    max_tokens: int = 450,
    overlap_sentences: int = 1,
) -> list[Chunk]:
    label = article_label(source.jurisdiction, doc.language)
    chunks: list[Chunk] = []
    for art in doc.articles:
        if art.valid_from is None and source.default_valid_from is not None:
            art = art.model_copy(update={"valid_from": source.default_valid_from})
        art_title = f"{label} {art.number}" + (f" — {art.heading}" if art.heading else "")
        path = " > ".join([*art.path, f"{label} {art.number}"])
        header = f"{source.act_short} ({source.jurisdiction}) > {' > '.join([*art.path, art_title])}"
        budget = max(64, max_tokens - estimate_tokens(header))
        body_parts = _split_long(art.paragraphs, budget, overlap_sentences)
        n = len(body_parts)
        for i, body in enumerate(body_parts, start=1):
            suffix = f" (part {i}/{n})" if n > 1 else ""
            text = f"{header}{suffix}\n" + "\n".join(body)
            cid = hashlib.sha256(f"{doc_version_id}|{path}|{i}|{text}".encode()).hexdigest()
            chunks.append(
                Chunk(
                    id=cid,
                    doc_version_id=doc_version_id,
                    chunk_path=path,
                    article_number=art.number,
                    article_key=f"{source.jurisdiction}:{source.act_short}:{art.number}",
                    citation_id=citation_id(source, art),
                    part=i,
                    n_parts=n,
                    language=doc.language,
                    jurisdiction=source.jurisdiction,
                    text=text,
                    token_count=estimate_tokens(text),
                    chunker_version=CHUNKER_VERSION,
                    license=source.license,
                    valid_from=art.valid_from,
                    valid_to=art.valid_to,
                )
            )
    return chunks
