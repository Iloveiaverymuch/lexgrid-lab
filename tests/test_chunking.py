from lexgrid.chunking import chunk_document
from lexgrid.models import ArticleUnit, NormalizedDocument
from lexgrid.parsers import PARSERS
from tests.conftest import SAMPLES, make_source


def _doc(paragraphs: list[str]) -> NormalizedDocument:
    return NormalizedDocument(
        source_id="eu-gdpr",
        external_id="CELEX:32016R0679",
        title="t",
        language="en",
        doc_type="regulation",
        articles=[
            ArticleUnit(number="17", heading="Right to erasure", path=["CHAPTER III"], paragraphs=paragraphs)
        ],
    )


def test_article_number_is_in_every_chunk_text() -> None:
    doc = PARSERS["eurlex_html"].parse(
        (SAMPLES / "eurlex_en.html").read_bytes(), source=make_source(), language="en"
    )
    chunks = chunk_document(doc, source=make_source(), doc_version_id="v1")
    assert chunks
    for c in chunks:
        assert f"Article {c.article_number}" in c.text
        assert c.license == "test-license"


def test_short_article_is_one_chunk_with_stable_ids() -> None:
    a = chunk_document(_doc(["1. Short text."]), source=make_source(), doc_version_id="v1")
    b = chunk_document(_doc(["1. Short text."]), source=make_source(), doc_version_id="v1")
    assert len(a) == 1 and a[0].n_parts == 1
    assert a[0].id == b[0].id
    assert a[0].citation_id == "[EU:GDPR art. 17 @2016-05-24]"
    assert a[0].article_key == "EU:GDPR:17"


def test_long_article_split_with_overlap_and_budget() -> None:
    sentences = [f"Sentence number {i} explains a rule about data erasure in detail." for i in range(120)]
    chunks = chunk_document(
        _doc([" ".join(sentences)]), source=make_source(), doc_version_id="v1", max_tokens=200
    )
    assert len(chunks) > 1
    assert all(c.n_parts == len(chunks) for c in chunks)
    assert all(c.token_count <= 200 + 30 for c in chunks)  # header + one overlap sentence of slack
    last_sentence_first = chunks[0].text.split("\n")[-1].split(". ")[-1].rstrip(".")
    assert last_sentence_first in chunks[1].text  # overlap
    assert len({c.id for c in chunks}) == len(chunks)


def test_different_version_gives_different_chunk_ids() -> None:
    a = chunk_document(_doc(["x"]), source=make_source(), doc_version_id="v1")
    b = chunk_document(_doc(["x"]), source=make_source(), doc_version_id="v2")
    assert a[0].id != b[0].id
