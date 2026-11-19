"""REST + MCP contract and the jurisdiction-isolation (leak) test on the real corpus."""

import re
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient

from lexgrid.answer import AskService, ExtractiveAnswerer
from lexgrid.api import create_app
from lexgrid.embed import HashEmbedder
from lexgrid.evals.runner import load_golden
from lexgrid.mcp_server import LegalTools, ScopeError, create_mcp
from lexgrid.retrieval.memory import MemoryBackend
from lexgrid.retrieval.rerank import OverlapReranker
from lexgrid.retrieval.service import RetrievalService
from lexgrid.runtime import entitlements, parse_keys
from lexgrid.store import LineageStore

REPO = Path(__file__).resolve().parents[1]
KEYS = parse_keys("key-fr:FR;key-all:EU,FR,DE")
FR = {"X-API-Key": "key-fr"}
ALL = {"X-API-Key": "key-all"}


@pytest.fixture(scope="module")
def retrieval(real_store: LineageStore) -> RetrievalService:
    chunks = real_store.live_chunks()
    emb = HashEmbedder()
    backend = MemoryBackend(chunks, {"vec_hash": emb.embed([c["text"] for c in chunks], "passage")})
    return RetrievalService(backend, emb, OverlapReranker())


@pytest.fixture(scope="module")
def client(retrieval: RetrievalService, real_store: LineageStore) -> TestClient:
    ask = AskService(retrieval, ExtractiveAnswerer(), abstain_threshold=None)
    return TestClient(create_app(retrieval, ask, real_store, KEYS))


def test_parse_keys_and_entitlements() -> None:
    assert KEYS == {"key-fr": ("FR",), "key-all": ("EU", "FR", "DE")}
    assert entitlements(KEYS, "key-fr") == ("FR",) and entitlements(KEYS, "nope") is None
    with pytest.raises(ValueError):
        parse_keys("k:US")


def test_auth_required(client: TestClient) -> None:
    assert client.post("/search", json={"query": "délai"}).status_code == 401
    assert client.post("/search", json={"query": "délai"}, headers={"X-API-Key": "bad"}).status_code == 401


def test_widening_is_refused_narrowing_allowed(client: TestClient) -> None:
    r = client.post("/search", json={"query": "Widerrufsfrist", "jurisdictions": ["DE"]}, headers=FR)
    assert r.status_code == 403
    r = client.post("/search", json={"query": "Widerrufsfrist", "jurisdictions": ["DE"]}, headers=ALL)
    assert r.status_code == 200 and {h["jurisdiction"] for h in r.json()["hits"]} == {"DE"}


def test_leak_rate_is_zero_over_the_golden_set(client: TestClient) -> None:
    """Every golden query, every mode, with an FR-only key: no hit may come from EU or DE."""
    leaks, total = 0, 0
    for q in load_golden(REPO / "evals" / "golden" / "golden_v1.yaml"):
        for mode in ("bm25", "dense", "hybrid_rrf", "hybrid_rrf_rerank"):
            hits = client.post("/search", json={"query": q.query, "mode": mode}, headers=FR).json()["hits"]
            total += len(hits)
            leaks += sum(h["jurisdiction"] != "FR" for h in hits)
    assert total > 0 and leaks == 0


def test_lineage_hidden_outside_entitlement(client: TestClient, real_store: LineageStore) -> None:
    de_chunk = real_store.live_chunks("DE")[0]["id"]
    assert client.get(f"/lineage/{de_chunk}", headers=FR).status_code == 404
    body = client.get(f"/lineage/{de_chunk}", headers=ALL).json()
    assert body["jurisdiction"] == "DE" and len(body["content_sha256"]) == 64


def test_ask_returns_cited_answer(client: TestClient) -> None:
    body = client.post("/ask", json={"question": "délai de rétractation contrat à distance"}, headers=FR).json()
    assert not body["abstained"] and body["answer"]
    cited = {a["citation_id"] for a in body["answer"]}
    assert cited <= {s["citation_id"] for s in body["sources"]}
    assert all(c.startswith("[FR:") for c in cited) and "not legal advice" in body["disclaimer"]


def test_mcp_tools_contract_and_scope(retrieval: RetrievalService, real_store: LineageStore) -> None:
    tools = LegalTools(retrieval, real_store, ("FR",))
    server = create_mcp(tools)

    listed: list[Any] = anyio.run(server.list_tools)
    assert {t.name for t in listed} == {"search_legal", "get_article", "get_lineage", "get_index_status"}
    search_schema = next(t for t in listed if t.name == "search_legal").input_schema
    assert search_schema["required"] == ["query"]

    res = tools.search_legal("délai de rétractation")
    assert res["scope"] == ["FR"] and all(h["jurisdiction"] == "FR" for h in res["hits"])
    with pytest.raises(ScopeError):
        tools.search_legal("Widerrufsfrist", jurisdictions=["DE"])
    art = tools.get_article(res["hits"][0]["citation_id"])
    assert art["found"] and art["jurisdiction"] == "FR" and "fr" in art["texts"]
    de = real_store.live_chunks("DE")[0]
    assert tools.get_article(de["citation_id"]) == {"found": False, "citation_id": de["citation_id"]}
    assert tools.get_lineage(de["id"]) == {"found": False}


def test_ui_and_console_endpoints(retrieval: RetrievalService, real_store: LineageStore, tmp_path: Path) -> None:
    (tmp_path / "RUN-1.json").write_text(
        '{"run_id": "RUN-1", "created_at": "2026-11-19", "git_sha": "abc", "config": {}, "summary": {"modes": {}},'
        ' "per_query": {"bm25": {}}}'
    )
    (tmp_path / "broken.json").write_text("{not json")
    ask = AskService(retrieval, ExtractiveAnswerer(), abstain_threshold=0.15)
    c = TestClient(create_app(retrieval, ask, real_store, KEYS, results_dir=tmp_path))
    page = c.get("/")
    assert page.status_code == 200 and "lexgrid" in page.text
    assert not re.search(
        r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML", page.text
    )  # untrusted text only via textContent
    assert c.get("/whoami", headers=FR).json()["scope"] == ["FR"]
    assert c.get("/whoami").status_code == 401
    assert set(c.get("/indexes", headers=FR).json()) == {"FR"}  # other jurisdictions' index history not exposed
    runs = c.get("/evals", headers=FR).json()
    assert [r["run_id"] for r in runs] == ["RUN-1"] and "per_query" not in runs[0]


def test_named_article_is_flagged_as_pinned(client: TestClient) -> None:
    hits = client.post("/search", json={"query": "article L. 221-18", "k": 3}, headers=FR).json()["hits"]
    assert hits[0]["article_key"].endswith("L221-18") and hits[0]["pinned"] is True
    assert not any(h["pinned"] for h in hits[1:])
