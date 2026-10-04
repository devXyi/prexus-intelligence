"""Scenario simulation for the UI's "Run Simulation" (event-conditional CAT v0)."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from .priors import BASE_YEAR, PRIORS, PROVENANCE, norm_rcp, trend, vuln_mult
from .severity import gpd_sf
from .vulnerability import mean_damage_ratio, sample_damage

N_DRAWS = 5000


def _label(damage_ratio: float) -> str:
    return ("Catastrophic" if damage_ratio >= 0.40 else "Severe" if damage_ratio >= 0.20
            else "Moderate" if damage_ratio >= 0.07 else "Low")


def simulate_event(*, hazard: str, intensity: float, duration_days: float, target_year: int, rcp: str,
                   value_mm: float, composite_risk: float, asset_type: str = "infrastructure",
                   seed: Optional[int] = None, n: int = N_DRAWS) -> dict:
    h = PRIORS[hazard]
    rcp_n = norm_rcp(rcp)
    rng = np.random.default_rng(seed)
    susceptibility = 0.6 + 0.8 * float(composite_risk)          # asset-specific, from its risk score
    mult = vuln_mult(asset_type, hazard) * susceptibility

    # 1) conditional loss if the event occurs (Monte Carlo over damage uncertainty)
    mdr = float(mean_damage_ratio(intensity, h, mult, duration_days))
    loss = value_mm * sample_damage(rng, np.full(n, mdr), h.kappa)

    # 2) probability of >= 1 event at least this intense between BASE_YEAR and target_year
    p_exc = float(gpd_sf(max(intensity - h.threshold, 0.0), h.xi, h.sigma)) if intensity > h.threshold else 1.0
    lam_year = lambda y: h.base_rate * (0.5 + composite_risk) * trend(y, rcp_n, hazard) * p_exc
    cum = sum(lam_year(y) for y in range(BASE_YEAR, max(target_year, BASE_YEAR) + 1))
    prob = 1.0 - math.exp(-cum)

    # 3) premium loading: growth in expected annual loss vs BASE_YEAR (rate trend only)
    growth = trend(target_year, rcp_n, hazard) / trend(BASE_YEAR, rcp_n, hazard) - 1.0
    ins_pct = 100.0 * growth * (0.5 + composite_risk)

    return {
        "cost_impact": round(float(loss.mean()), 4),                # USD mm
        "loss_p50_mm": round(float(np.quantile(loss, 0.5)), 4),
        "loss_p90_mm": round(float(np.quantile(loss, 0.9)), 4),
        "damage_ratio": round(mdr, 4),
        "damage_label": _label(mdr),
        "insurance_increase_pct": round(ins_pct, 1),
        "probability_pct": round(100.0 * prob, 1),
        "hazard": hazard, "intensity": intensity, "duration_days": duration_days,
        "target_year": target_year, "climate_scenario": rcp_n,
        "method": "catmodel-v0", "calibrated": False, "parameters": PROVENANCE,
        "disclaimer": "Illustrative scenario model with placeholder priors; not calibrated to observed losses.",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
