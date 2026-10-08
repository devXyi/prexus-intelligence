"""Frequency–severity–vulnerability Monte Carlo and copula portfolio aggregation."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .copula import copula_uniforms
from .frequency import sample_counts
from .priors import HazardPrior, trend
from .severity import gpd_sample
from .vulnerability import mean_damage_ratio, sample_damage


@dataclass
class AnnualResult:
    annual: np.ndarray       # aggregate annual loss (USD mm), capped at asset value
    max_event: np.ndarray    # largest single-event loss per year (for OEP)
    counts: np.ndarray       # events per year


def annual_losses(h: HazardPrior, value: float, n_years: int, rng: np.random.Generator, *,
                  rate_multiplier: float = 1.0, year: int | None = None, rcp: str = "rcp45",
                  vuln_mult: float = 1.0) -> AnnualResult:
    lam = h.base_rate * rate_multiplier * (trend(year, rcp, h.name) if year is not None else 1.0)
    counts = sample_counts(rng, lam, n_years, h.dispersion)
    total = int(counts.sum())
    inten = np.minimum(h.threshold + gpd_sample(rng, total, h.xi, h.sigma), 1.0)
    dmg = sample_damage(rng, mean_damage_ratio(inten, h, vuln_mult), h.kappa)
    ev = value * dmg
    idx = np.repeat(np.arange(n_years), counts)
    annual = np.minimum(np.bincount(idx, weights=ev, minlength=n_years), value)
    mx = np.zeros(n_years)
    if total:
        np.maximum.at(mx, idx, ev)
    return AnnualResult(annual=annual, max_event=mx, counts=counts)


def portfolio_annual(rng: np.random.Generator, asset_annual: list[np.ndarray], corr: np.ndarray,
                     copula: str = "gaussian", nu: float = 4.0) -> np.ndarray:
    """Impose dependence on per-asset annual-loss marginals via a copula
    (rank coupling; marginals preserved exactly)."""
    n = asset_annual[0].size
    u = copula_uniforms(rng, corr, n, copula, nu)
    cols = []
    for j, a in enumerate(asset_annual):
        s = np.sort(a)
        cols.append(s[np.minimum((u[:, j] * n).astype(int), n - 1)])
    return np.column_stack(cols).sum(axis=1)
