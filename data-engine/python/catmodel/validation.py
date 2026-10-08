"""Forecast-verification harness: the evidence a DST scientist will ask for.

CRPS (ensemble), Brier score, reliability (calibration) curves, PIT histograms.
Use on hindcasts (e.g. Kerala 2018, Chennai 2015, 2022 heatwave) before any
"calibrated" claim is made in product copy.
"""
from __future__ import annotations

from typing import Dict

import numpy as np


def crps_ensemble(ens: np.ndarray, obs: np.ndarray) -> np.ndarray:
    """CRPS per case. ens: (n, m) members; obs: (n,). Energy form,
    CRPS = E|X−y| − ½E|X−X'| using the sorted-sample identity."""
    ens = np.sort(np.asarray(ens, dtype=float), axis=1)
    obs = np.asarray(obs, dtype=float)
    n, m = ens.shape
    term1 = np.abs(ens - obs[:, None]).mean(axis=1)
    w = 2.0 * np.arange(1, m + 1) - m - 1.0
    e_xx = 2.0 * (ens * w).sum(axis=1) / (m * m)
    return term1 - 0.5 * e_xx


def brier_score(p: np.ndarray, o: np.ndarray) -> float:
    p, o = np.asarray(p, float), np.asarray(o, float)
    return float(np.mean((p - o) ** 2))


def reliability_bins(p: np.ndarray, o: np.ndarray, n_bins: int = 10) -> Dict[str, np.ndarray]:
    p, o = np.asarray(p, float), np.asarray(o, float)
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    mean_p, freq, cnt = np.zeros(n_bins), np.zeros(n_bins), np.zeros(n_bins, dtype=int)
    for b in range(n_bins):
        m = idx == b
        cnt[b] = int(m.sum())
        if cnt[b]:
            mean_p[b], freq[b] = p[m].mean(), o[m].mean()
    return {"mean_forecast": mean_p, "observed_freq": freq, "count": cnt}


def expected_calibration_error(p: np.ndarray, o: np.ndarray, n_bins: int = 10) -> float:
    r = reliability_bins(p, o, n_bins)
    tot = r["count"].sum()
    return float((r["count"] * np.abs(r["mean_forecast"] - r["observed_freq"])).sum() / max(tot, 1))


def pit_values(ens: np.ndarray, obs: np.ndarray, rng: np.random.Generator | None = None) -> np.ndarray:
    """Randomised PIT: uniform iff the ensemble is calibrated."""
    rng = rng or np.random.default_rng(0)
    ens, obs = np.asarray(ens, float), np.asarray(obs, float)
    below = (ens < obs[:, None]).sum(axis=1)
    equal = (ens == obs[:, None]).sum(axis=1)
    return (below + rng.random(obs.size) * equal) / ens.shape[1]


def skill_score(score: float, reference: float) -> float:
    """1 − score/reference (>0 beats the reference forecast, e.g. climatology)."""
    return 1.0 - score / reference if reference else float("nan")
