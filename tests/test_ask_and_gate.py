from datetime import date
from typing import Any

import pytest

from lexgrid.answer import AskService, ExtractiveAnswerer
from lexgrid.embed import HashEmbedder
from lexgrid.evals.abstain import choose, sweep
from lexgrid.gate import decide
from lexgrid.retrieval.base import Hit
from lexgrid.retrieval.context import PREAMBLE, assemble
from lexgrid.retrieval.memory import MemoryBackend
from lexgrid.retrieval.rerank import OverlapReranker
from lexgrid.retrieval.service import RetrievalService
from tests.test_retrieval import CHUNKS


def hit(key: str, jur: str, text: str, score: float = 1.0) -> Hit:
    return Hit(key, key, "1", f"[{key}]", jur, "fr", key, text, score, date(2016, 7, 1))


def test_context_budget_quota_and_escaping() -> None:
    long = "mot " * 900
    hits = [hit("FR:a", "FR", long), hit("FR:b", "FR", long), hit("DE:c", "DE", "kurz <script>x</script>")]
    pack = assemble(hits, budget_tokens=1000, per_jurisdiction_share=0.6)
    assert pack.tokens <= 1000
    assert {i.jurisdiction for i in pack.items} == {"FR", "DE"}  # FR cannot take the whole budget
    assert any(i.truncated for i in pack.items)
    out = pack.render()
    assert out.startswith(PREAMBLE)
    assert "<script>" not in out and "&lt;script&gt;" in out


def test_single_jurisdiction_may_use_full_budget() -> None:
    pack = assemble([hit("FR:a", "FR", "mot " * 300), hit("FR:b", "FR", "mot " * 300)], budget_tokens=1000)
    assert len(pack.items) == 2 and pack.dropped == 0


def _ask(threshold: float | None) -> AskService:
    emb = HashEmbedder()
    retrieval = RetrievalService(
        MemoryBackend(CHUNKS, {"vec_hash": emb.embed([c["text"] for c in CHUNKS], "passage")}), emb, OverlapReranker()
    )
    return AskService(retrieval, ExtractiveAnswerer(), abstain_threshold=threshold)


def test_ask_answers_with_citations_and_disclaimer() -> None:
    r = _ask(0.1).ask("délai de rétractation quatorze jours", ("FR",))
    assert not r.abstained and r.lines
    assert all(line.citation_id.startswith("[FR:") for line in r.lines)
    assert "not legal advice" in r.disclaimer


def test_ask_abstains_below_threshold() -> None:
    r = _ask(0.99).ask("Mindestlohn pro Stunde", ("FR",))
    assert r.abstained and r.lines == [] and "insufficient evidence" in (r.reason or "")


def test_abstain_sweep_picks_lowest_threshold_covering_all_no_answer() -> None:
    top = {"a1": 0.9, "a2": 0.05, "n1": 0.10, "n2": 0.02}
    rows = sweep(top, {"n1", "n2"}, {"a1": 1.0, "a2": 0.0}, [0.0, 0.05, 0.11, 0.5, 0.95])
    best = choose(rows)
    assert best.threshold == 0.11
    assert best.no_answer_abstain == 1.0 and best.answerable_answered == 0.5 and best.answered_hit1 == 1.0


@pytest.mark.parametrize(
    ("cand", "base", "tol", "promote"),
    [
        ([0.8] * 10, None, 0.02, True),
        ([0.79] * 10, [0.80] * 10, 0.02, True),
        ([0.70] * 10, [0.80] * 10, 0.02, False),
        ([0.90] * 10, [0.80] * 10, 0.0, True),
    ],
)
def test_gate_decision(cand: list[float], base: list[float] | None, tol: float, promote: bool) -> None:
    d = decide(cand, base, tol)
    assert d.promote is promote
    assert ("first release" in d.reason) is (base is None)


def test_release_rejects_regression_and_keeps_live_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    import numpy as np

    from lexgrid import gate
    from lexgrid.evals.runner import GoldenQuery, ModeResult
    from lexgrid.store import LineageStore
    from tests.test_opensearch_index import FakeClient, _chunks

    store = LineageStore.from_url(f"sqlite:///{tmp_path / 'db.sqlite'}")
    monkeypatch.setattr(store, "live_chunks", lambda j=None: _chunks(3, j or "FR"))
    golden = [GoldenQuery(id="q", query="x", language="fr", scope=["FR"], type="paraphrase", qrels={"FR:X:1": 2})]

    def fake_run_mode(service: RetrievalService, queries: Any, mode: Any, k: int = 10) -> ModeResult:
        candidate = bool(service.backend.overrides)  # type: ignore[attr-defined]
        score = 0.5 if candidate and state["degraded"] else 0.9
        return ModeResult(mode, {"q": {"ndcg@10": score}}, {"q": []}, {"q": 0.0}, [1.0])

    state = {"degraded": False}
    monkeypatch.setattr(gate, "run_mode", fake_run_mode)
    client = FakeClient()

    class Emb:
        name, model_id, dim = "e5", "m", 4

        def embed(self, texts: list[str], kind: str) -> Any:
            return np.ones((len(texts), 4), dtype=np.float32)

    kw: dict[str, Any] = dict(
        client=client, store=store, jurisdictions=["FR"], embedders=[Emb()], gate_embedder=Emb(), golden=golden
    )
    first, built1 = gate.release(**kw)
    assert first.promote and client.indices.get_alias("legal-fr-current").keys() == {built1["FR"]}

    import time

    time.sleep(1.1)
    state["degraded"] = True
    second, built2 = gate.release(**kw)
    assert not second.promote and "regression" in second.reason
    assert client.indices.get_alias("legal-fr-current").keys() == {built1["FR"]}  # live alias untouched
    status = {r["run_id"]: (r["status"], r["eval_run_id"]) for r in store.index_runs("FR")}
    assert status[built2["FR"]][0] == "rejected" and status[built2["FR"]][1].startswith("GATE-")
