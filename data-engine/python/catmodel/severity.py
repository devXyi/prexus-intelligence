"""Severity: generalised Pareto (peaks-over-threshold) samplers and analytics."""
from __future__ import annotations

import numpy as np


def gpd_sample(rng: np.random.Generator, size: int, xi: float, sigma: float) -> np.ndarray:
    """Exceedances over the threshold, inverse-CDF method."""
    u = rng.random(size)
    if abs(xi) < 1e-9:
        return -sigma * np.log1p(-u)
    return sigma * ((1.0 - u) ** (-xi) - 1.0) / xi


def gpd_mean(xi: float, sigma: float) -> float:
    if xi >= 1:
        return float("inf")
    return sigma / (1.0 - xi)


def gpd_sf(x: np.ndarray | float, xi: float, sigma: float) -> np.ndarray | float:
    """P(exceedance > x) for x >= 0."""
    x = np.maximum(x, 0.0)
    if abs(xi) < 1e-9:
        return np.exp(-x / sigma)
    base = np.maximum(1.0 + xi * x / sigma, 1e-300)
    return base ** (-1.0 / xi)


def gpd_return_level(p_exceed: float, xi: float, sigma: float) -> float:
    """Exceedance x such that P(E > x) = p_exceed."""
    if abs(xi) < 1e-9:
        return -sigma * np.log(p_exceed)
    return sigma * (p_exceed ** (-xi) - 1.0) / xi
