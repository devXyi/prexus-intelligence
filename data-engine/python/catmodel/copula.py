"""Spatial/peril dependence across assets: Gaussian and Student-t copulas."""
from __future__ import annotations

import numpy as np
from scipy import stats


def nearest_psd_corr(c: np.ndarray) -> np.ndarray:
    c = (np.asarray(c, dtype=float) + np.asarray(c, dtype=float).T) / 2.0
    w, v = np.linalg.eigh(c)
    w = np.clip(w, 1e-10, None)
    c = (v * w) @ v.T
    d = np.sqrt(np.diag(c))
    c = c / np.outer(d, d)
    np.fill_diagonal(c, 1.0)
    return c


def copula_uniforms(rng: np.random.Generator, corr: np.ndarray, n: int, kind: str = "gaussian", nu: float = 4.0) -> np.ndarray:
    corr = nearest_psd_corr(corr)
    k = corr.shape[0]
    L = np.linalg.cholesky(corr)
    z = rng.standard_normal((n, k)) @ L.T
    if kind == "gaussian":
        return stats.norm.cdf(z)
    if kind == "t":
        g = rng.chisquare(nu, size=(n, 1)) / nu
        return stats.t.cdf(z / np.sqrt(g), df=nu)
    raise ValueError("copula kind must be 'gaussian' or 't'")


def equicorrelation(k: int, rho: float) -> np.ndarray:
    c = np.full((k, k), rho)
    np.fill_diagonal(c, 1.0)
    return c
