import math

import pytest

from lexgrid.evals.metrics import hit_at, mrr, ndcg_at, per_query, precision_at, recall_at
from lexgrid.evals.stats import bootstrap_ci, mcnemar_exact, paired_bootstrap

QRELS = {"A": 2, "B": 1, "C": 0}


def test_hand_computed_values() -> None:
    ranked = ["X", "B", "A", "Y"]
    assert recall_at(ranked, QRELS, 2) == 0.5
    assert recall_at(ranked, QRELS, 3) == 1.0
    assert precision_at(ranked, QRELS, 2) == 0.5
    assert hit_at(ranked, QRELS, 1) == 0.0 and hit_at(ranked, QRELS, 2) == 1.0
    assert mrr(ranked, QRELS) == 0.5
    dcg = (2**1 - 1) / math.log2(3) + (2**2 - 1) / math.log2(4)
    idcg = (2**2 - 1) / math.log2(2) + (2**1 - 1) / math.log2(3)
    assert ndcg_at(ranked, QRELS) == pytest.approx(dcg / idcg)


def test_perfect_and_empty_rankings() -> None:
    assert ndcg_at(["A", "B"], QRELS) == pytest.approx(1.0)
    assert per_query([], QRELS)["ndcg@10"] == 0.0
    assert recall_at(["A"], {}, 5) == 0.0


def test_bootstrap_ci_contains_mean_and_is_deterministic() -> None:
    vals = [0.0, 1.0] * 15
    a = bootstrap_ci(vals)
    assert a == bootstrap_ci(vals)
    assert a[1] <= a[0] <= a[2]
    assert a[0] == 0.5


def test_paired_bootstrap_detects_consistent_gain() -> None:
    base = [0.2] * 20
    better = [0.6] * 20
    res = paired_bootstrap(base, better)
    assert res["diff"] == pytest.approx(0.4) and res["ci_low"] > 0 and res["p"] < 0.01


def test_mcnemar_exact() -> None:
    a = [0, 0, 0, 0, 0, 0, 1, 1]
    b = [1, 1, 1, 1, 1, 1, 1, 1]
    r = mcnemar_exact(a, b)
    assert r["n01"] == 6 and r["n10"] == 0
    assert r["p"] == pytest.approx(2 / 64)
    assert mcnemar_exact([1, 0], [1, 0])["p"] == 1.0
