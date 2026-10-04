"""Frequency: Poisson and negative-binomial (over-dispersed / clustered) counts."""
from __future__ import annotations

from typing import Optional

import numpy as np


def sample_counts(rng: np.random.Generator, lam: float, n: int, dispersion: Optional[float] = None) -> np.ndarray:
    """Annual event counts. dispersion=None → Poisson(λ). Otherwise gamma-Poisson with
    mean λ and variance λ + λ²/k (k = dispersion): clustering of events in bad years."""
    if lam < 0:
        raise ValueError("rate must be >= 0")
    if lam == 0:
        return np.zeros(n, dtype=np.int64)
    if dispersion is None:
        return rng.poisson(lam, n)
    return rng.poisson(rng.gamma(shape=dispersion, scale=lam / dispersion, size=n))
