from datetime import date
from pathlib import Path
from typing import Any

import pytest

from lexgrid.embed import CachedEmbedder, EmbeddingCache, HashEmbedder
from lexgrid.retrieval.base import Filters, Hit, article_refs, collapse_by_article, rrf
from lexgrid.retrieval.memory import MemoryBackend
from lexgrid.retrieval.rerank import OverlapReranker
from lexgrid.retrieval.service import RetrievalService


def chunk(cid: str, key: str, num: str, jur: str, lang: str, text: str, **kw: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "article_key": key,
        "article_number": num,
        "citation_id": f"[{key}]",
        "jurisdiction": jur,
        "language": lang,
        "chunk_path": key,
        "text": text,
        "doc_type": kw.get("doc_type", "code"),
        "valid_from": kw.get("valid_from"),
        "valid_to": kw.get("valid_to"),
    }


CHUNKS = [
    chunk("c1", "FR:C:L221-18", "L221-18", "FR", "fr", "Article L221-18 délai de quatorze jours rétractation"),
    chunk(
        "c2",
        "FR:C:L221-21",
        "L221-21",
        "FR",
        "fr",
        "Article L221-21 rétractation voir article L. 221-18 délai",
    ),
    chunk("c3", "DE:BGB:355", "355", "DE", "de", "§ 355 Widerrufsfrist beträgt 14 Tage"),
    chunk("c4", "EU:CRD:9", "9", "EU", "en", "Article 9 withdrawal period of 14 days"),
    chunk("c5", "EU:CRD:9", "9", "EU", "fr", "Article 9 délai de rétractation de quatorze jours"),
    chunk(
        "c6",
        "FR:C:L221-5",
        "L221-5",
        "FR",
        "fr",
        "Article L221-5 information précontractuelle",
        valid_from=date(2026, 6, 19),
    ),
    chunk(
        "c7",
        "FR:C:OLD",
        "L121-21",
        "FR",
        "fr",
        "Article L121-21 ancien délai de rétractation abrogé",
        valid_from=date(2014, 6, 14),
        valid_to=date(2016, 7, 1),
    ),
]


@pytest.fixture
def service() -> RetrievalService:
    emb = HashEmbedder()
    vecs = emb.embed([c["text"] for c in CHUNKS], "passage")
    return RetrievalService(MemoryBackend(CHUNKS, {"vec_hash": vecs}), emb, OverlapReranker(), candidates=10)


def test_article_refs_detection() -> None:
    assert article_refs("article L. 221-18 du code") == {"L221-18"}
    assert article_refs("Art. 17 DSGVO und § 355 BGB") == {"17", "355"}
    assert article_refs("Article premier") == {"1"}
    assert article_refs("délai de rétractation") == set()


def test_rrf_and_collapse() -> None:
    h = lambda cid, key: Hit(cid, key, "1", key, "EU", "en", key, "t", 0.0)  # noqa: E731
    fused = rrf([[h("a", "K1"), h("b", "K2")], [h("b", "K2"), h("c", "K1")]], k=60)
    assert fused[0].chunk_id == "b"  # in both lists
    assert [x.article_key for x in collapse_by_article(fused)] == ["K2", "K1"]


def test_filters_require_scope() -> None:
    with pytest.raises(ValueError):
        Filters(jurisdictions=())


@pytest.mark.parametrize("mode", ["bm25", "dense", "hybrid_rrf", "hybrid_rrf_rerank"])
def test_scope_is_never_widened(service: RetrievalService, mode: str) -> None:
    res = service.search("Widerrufsfrist 14 Tage délai rétractation", Filters(jurisdictions=("FR",)), mode=mode)  # type: ignore[arg-type]
    assert res.hits and all(h.jurisdiction == "FR" for h in res.hits)


def test_exact_reference_is_pinned_first(service: RetrievalService) -> None:
    res = service.search("article L. 221-18", Filters(jurisdictions=("FR",)), mode="hybrid_rrf")
    assert res.hits[0].article_key == "FR:C:L221-18"


def test_collapse_dedups_languages_of_same_eu_article(service: RetrievalService) -> None:
    res = service.search("withdrawal 14 days rétractation quatorze jours", Filters(jurisdictions=("EU",)), mode="bm25")
    assert [h.article_key for h in res.hits].count("EU:CRD:9") == 1


def test_as_of_filters_out_not_yet_in_force_and_repealed(service: RetrievalService) -> None:
    keys = lambda d: {  # noqa: E731
        h.article_key
        for h in service.search(
            "article information précontractuelle délai rétractation",
            Filters(("FR",), as_of=d),
            k=20,
            mode="bm25",
        ).hits
    }
    assert "FR:C:L221-5" not in keys(date(2025, 1, 1))
    assert "FR:C:L221-5" in keys(date(2026, 7, 1))
    assert "FR:C:OLD" in keys(date(2015, 1, 1))
    assert "FR:C:OLD" not in keys(date(2020, 1, 1))


def test_rerank_mode_requires_reranker() -> None:
    emb = HashEmbedder()
    svc = RetrievalService(MemoryBackend(CHUNKS, {"vec_hash": emb.embed([c["text"] for c in CHUNKS], "passage")}), emb)
    with pytest.raises(ValueError):
        svc.search("x", Filters(("FR",)), mode="hybrid_rrf_rerank")


def test_embedding_cache_only_pays_for_misses(tmp_path: Path) -> None:
    emb = CachedEmbedder(HashEmbedder(), EmbeddingCache(tmp_path / "e.sqlite"))
    a = emb.embed(["alpha", "beta", "alpha"], "passage")
    assert emb.misses == 2
    b = emb.embed(["beta", "alpha"], "passage")
    assert emb.misses == 2
    assert (a[1] == b[0]).all()
    emb.embed(["alpha"], "query")  # query and passage vectors are cached separately
    assert emb.misses == 3


DIVERSE = [
    chunk("e1", "EU:CRD:16", "16", "EU", "en", "Article 16 exceptions right of withdrawal personalised goods"),
    chunk("e2", "EU:CRD:9", "9", "EU", "en", "Article 9 right of withdrawal personalised period"),
    chunk("e3", "EU:CRD:14", "14", "EU", "en", "Article 14 withdrawal goods obligations"),
    chunk("e4", "EU:CRD:6", "6", "EU", "en", "Article 6 information withdrawal goods"),
    chunk("f1", "FR:C:L221-28", "L221-28", "FR", "fr", "Article L221-28 biens nettement personnalisés exception"),
    chunk("d1", "DE:BGB:312g", "312g", "DE", "de", "§ 312g Widerrufsrecht Ausnahmen Waren"),
]


def _svc(diversify: bool) -> RetrievalService:
    emb = HashEmbedder()
    vecs = emb.embed([c["text"] for c in DIVERSE], "passage")
    return RetrievalService(
        MemoryBackend(DIVERSE, {"vec_hash": vecs}), emb, OverlapReranker(), diversify_jurisdictions=diversify
    )


@pytest.mark.parametrize("mode", ["dense", "hybrid_rrf", "hybrid_rrf_rerank"])
def test_every_jurisdiction_in_scope_gets_a_top_slot(mode: str) -> None:
    scope = Filters(("EU", "FR", "DE"))
    query = "exceptions to the right of withdrawal for personalised goods"
    after = [h.jurisdiction for h in _svc(True).search(query, scope, k=3, mode=mode).hits]  # type: ignore[arg-type]
    assert set(after) == {"EU", "FR", "DE"}, after
    if mode != "dense":  # lexical evidence favours the English EU texts without diversification
        before = [h.jurisdiction for h in _svc(False).search(query, scope, k=3, mode=mode).hits]  # type: ignore[arg-type]
        assert set(before) == {"EU"}, before


def test_diversification_never_invents_results() -> None:
    """Keyword mode: French and German texts share no word with the query, so nothing is shown for them."""
    hits = _svc(True).search("exceptions to the right of withdrawal", Filters(("EU", "FR", "DE")), mode="bm25").hits
    assert {h.jurisdiction for h in hits} == {"EU"} and all(h.score > 0 for h in hits)


def test_diversification_keeps_named_article_first_and_single_scope_unchanged() -> None:
    svc = _svc(True)
    res = svc.search("article L. 221-28 exceptions withdrawal", Filters(("EU", "FR", "DE")), k=5, mode="hybrid_rrf")
    assert res.hits[0].article_key == "FR:C:L221-28"
    one = Filters(("EU",))
    a = [h.chunk_id for h in _svc(True).search("withdrawal goods", one, mode="hybrid_rrf").hits]
    b = [h.chunk_id for h in _svc(False).search("withdrawal goods", one, mode="hybrid_rrf").hits]
    assert a == b
