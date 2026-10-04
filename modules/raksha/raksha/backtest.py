"""Calibration harness: rolling-origin back-test of the gamma-Poisson forecaster against climatology.

Run this on YOUR history before anyone says "calibrated". Outputs Brier, ECE (expected calibration
error), reliability bins and skill vs climatology (positive = beats "it will be like the past").
"""
from __future__ import annotations

from typing import Dict, Sequence

import numpy as np

from .scoring import posterior, prob_at_least_one

N_BINS = 10


def reliability(p: np.ndarray, o: np.ndarray, bins: int = N_BINS) -> Dict[str, list]:
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    mp, fr, cn = [], [], []
    for b in range(bins):
        m = idx == b
        cn.append(int(m.sum())); mp.append(float(p[m].mean()) if m.any() else 0.0); fr.append(float(o[m].mean()) if m.any() else 0.0)
    return {"mean_forecast": mp, "observed_freq": fr, "count": cn}


def ece(p: np.ndarray, o: np.ndarray, bins: int = N_BINS) -> float:
    r = reliability(p, o, bins)
    cn = np.array(r["count"])
    return float((cn * np.abs(np.array(r["mean_forecast"]) - np.array(r["observed_freq"]))).sum() / max(cn.sum(), 1))


def backtest(counts: Sequence[int], *, min_train: int = 20, horizon: int = 1, prior_weeks: float = 8.0) -> Dict[str, object]:
    c = np.asarray(counts, dtype=int)
    ps, os_, clim = [], [], []
    for t in range(min_train, len(c) - horizon + 1):
        train = c[:t]
        a, b = posterior(train, train.mean(), prior_weeks)
        ps.append(prob_at_least_one(a, b, horizon))
        os_.append(1.0 if c[t:t + horizon].sum() >= 1 else 0.0)
        win = np.convolve(train, np.ones(horizon, dtype=int), mode="valid")
        clim.append(float((win >= 1).mean()) if win.size else 0.5)
    p, o, q = np.array(ps), np.array(os_), np.array(clim)
    if p.size == 0:
        raise ValueError("series too short for the requested min_train/horizon")
    brier, brier_clim = float(np.mean((p - o) ** 2)), float(np.mean((q - o) ** 2))
    return {"n_forecasts": int(p.size), "brier": brier, "brier_climatology": brier_clim, "skill_vs_climatology": 1.0 - brier / brier_clim if brier_clim > 0 else float("nan"),
            "ece": ece(p, o), "reliability": reliability(p, o), "base_rate": float(o.mean()), "mean_forecast": float(p.mean())}
