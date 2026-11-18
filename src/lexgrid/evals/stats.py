"""Uncertainty for small eval sets: percentile bootstrap CIs, paired bootstrap, exact McNemar.

With ~30 queries the intervals are wide; that is the honest result, not a bug.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

SEED = 13
N_BOOT = 2000


def bootstrap_ci(
    values: Sequence[float], *, n_boot: int = N_BOOT, seed: int = SEED, alpha: float = 0.05
) -> tuple[float, float, float]:
    x = np.asarray(values, dtype=np.float64)
    if x.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, x.size, size=(n_boot, x.size))].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(x.mean()), float(lo), float(hi)


def paired_bootstrap(
    a: Sequence[float], b: Sequence[float], *, n_boot: int = N_BOOT, seed: int = SEED
) -> dict[str, float]:
    """Mean difference b - a with 95% CI and a two-sided bootstrap p-value (paired by query)."""
    xa, xb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if xa.shape != xb.shape or xa.size == 0:
        raise ValueError("paired samples must have the same non-zero length")
    d = xb - xa
    rng = np.random.default_rng(seed)
    boots = d[rng.integers(0, d.size, size=(n_boot, d.size))].mean(axis=1)
    lo, hi = np.quantile(boots, [0.025, 0.975])
    p = 2 * min(float((boots <= 0).mean()), float((boots >= 0).mean()))
    return {"diff": float(d.mean()), "ci_low": float(lo), "ci_high": float(hi), "p": min(1.0, p)}


def mcnemar_exact(a: Sequence[float], b: Sequence[float]) -> dict[str, float]:
    """Exact McNemar on paired binary outcomes (e.g. hit@5). n01 = a miss / b hit."""
    n01 = sum(1 for x, y in zip(a, b, strict=True) if x < 0.5 <= y)
    n10 = sum(1 for x, y in zip(a, b, strict=True) if y < 0.5 <= x)
    n = n01 + n10
    if n == 0:
        return {"n01": 0, "n10": 0, "p": 1.0}
    k = min(n01, n10)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2**n)
    return {"n01": n01, "n10": n10, "p": p}
