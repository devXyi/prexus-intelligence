"""Loss metrics: AAL, VaR, TVaR, exceedance-probability curves."""
from __future__ import annotations

from typing import Dict, Iterable, Optional

import numpy as np

DEFAULT_RPS = (2, 5, 10, 25, 50, 100, 250, 500)


def var(annual: np.ndarray, q: float) -> float:
    return float(np.quantile(annual, q))


def tvar(annual: np.ndarray, q: float) -> float:
    v = np.quantile(annual, q)
    tail = annual[annual >= v]
    return float(tail.mean()) if tail.size else float(v)


def ep_curve(losses: np.ndarray, return_periods: Iterable[int] = DEFAULT_RPS) -> Dict[int, float]:
    """Loss at each return period: the (1 − 1/RP) quantile of the annual loss distribution."""
    n = losses.size
    return {int(rp): float(np.quantile(losses, 1.0 - 1.0 / rp)) for rp in return_periods if rp <= n}


def risk_metrics(annual: np.ndarray, max_event: Optional[np.ndarray] = None,
                 alphas=(0.95, 0.99), rps: Iterable[int] = DEFAULT_RPS) -> dict:
    out = {
        "aal": float(annual.mean()),
        "std": float(annual.std(ddof=1)),
        "prob_any_loss": float((annual > 0).mean()),
        "var": {f"{a:g}": var(annual, a) for a in alphas},
        "tvar": {f"{a:g}": tvar(annual, a) for a in alphas},
        "aep": ep_curve(annual, rps),
        "n_years": int(annual.size),
    }
    if max_event is not None:
        out["oep"] = ep_curve(max_event, rps)
    return out
