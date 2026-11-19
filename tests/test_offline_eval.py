"""Tier-1 offline retrieval eval: real fixtures, in-memory BM25, golden set v1.

Not a quality benchmark (no stemming, hash embedder). It guards invariants that must never regress:
every exact-reference query finds its article at rank 1, and the golden set stays valid.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from lexgrid.embed import HashEmbedder
from lexgrid.evals.runner import load_golden, run_mode
from lexgrid.retrieval.memory import MemoryBackend
from lexgrid.retrieval.service import RetrievalService
from lexgrid.store import LineageStore

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "evals" / "golden" / "golden_v1.yaml"


@pytest.fixture(scope="module")
def chunks(real_store: LineageStore) -> list[dict[str, object]]:
    return real_store.live_chunks()


def test_golden_set_is_valid_and_labels_exist(chunks: list[dict[str, object]]) -> None:
    queries = load_golden(GOLDEN)
    assert len([q for q in queries if q.type != "no_answer"]) >= 30
    keys = {c["article_key"] for c in chunks}
    missing = {k for q in queries for k in q.qrels if k not in keys}
    assert not missing, f"qrels point to articles absent from the corpus: {missing}"


def test_exact_reference_queries_rank_first(chunks: list[dict[str, object]]) -> None:
    exact = [q for q in load_golden(GOLDEN) if q.type == "exact_ref"]
    emb = HashEmbedder()
    svc = RetrievalService(
        MemoryBackend(chunks, {"vec_hash": emb.embed([str(c["text"]) for c in chunks], "passage")}), emb
    )
    res = run_mode(svc, exact, "bm25")
    misses = {q: m for q, m in res.per_query.items() if m["hit@1"] < 1.0}
    assert not misses, f"exact references not at rank 1: { {q: res.ranked[q][:3] for q in misses} }"


def test_fixtures_are_never_line_ending_normalized() -> None:
    """CRLF in EUR-Lex captures broke CI once: git must treat fixtures as binary-exact."""
    try:
        out = subprocess.run(
            ["git", "check-attr", "text", "data/fixtures/eu-gdpr/en.html"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    assert out.strip().endswith("unset"), out


def test_promptfoo_quality_suite_matches_golden_set() -> None:
    """The promptfoo quality tests are generated from the golden set; they must never drift from it."""
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_promptfoo.py"), "--check"], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stdout + out.stderr
