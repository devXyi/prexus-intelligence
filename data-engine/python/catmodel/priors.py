"""PLACEHOLDER hazard priors. NOT fitted to data. Replace via calibration."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, Optional

BASE_YEAR = 2023
PROVENANCE = "placeholder-prior-v0 (uncalibrated; see catmodel/validation.py for the fitting harness)"


@dataclass(frozen=True)
class HazardPrior:
    name: str
    base_rate: float               # events/yr for an average asset at BASE_YEAR
    dispersion: Optional[float]    # NegBin k (variance = λ + λ²/k); None → Poisson
    threshold: float               # min relative intensity that counts as an event (0–1)
    xi: float                      # GPD shape of exceedances over threshold
    sigma: float                   # GPD scale
    dmax: float                    # asymptotic max damage ratio
    x_scale: float                 # Weibull damage-curve scale (relative intensity)
    k_shape: float                 # Weibull damage-curve shape
    kappa: float                   # Beta concentration of damage around its mean
    trend: Dict[str, float]        # d ln(rate)/d year by RCP
    duration_coeff: float          # extra damage per ln(1+days)/ln(31)


PRIORS: Dict[str, HazardPrior] = {
    "flood":    HazardPrior("flood",    0.30, 3.0, 0.15, 0.15, 0.20, 0.65, 0.55, 1.8, 20.0,
                            {"rcp26": .004, "rcp45": .008, "rcp60": .010, "rcp85": .014}, 0.35),
    "wildfire": HazardPrior("wildfire", 0.18, 2.0, 0.20, 0.20, 0.22, 0.80, 0.60, 2.0, 15.0,
                            {"rcp26": .005, "rcp45": .010, "rcp60": .013, "rcp85": .018}, 0.30),
    "heat":     HazardPrior("heat",     0.60, 5.0, 0.10, 0.05, 0.18, 0.30, 0.70, 1.6, 25.0,
                            {"rcp26": .006, "rcp45": .012, "rcp60": .015, "rcp85": .022}, 0.50),
    "drought":  HazardPrior("drought",  0.25, 4.0, 0.15, 0.10, 0.20, 0.45, 0.65, 1.7, 20.0,
                            {"rcp26": .004, "rcp45": .009, "rcp60": .012, "rcp85": .017}, 0.60),
}

# asset-class vulnerability multipliers (placeholders)
VULN_MULT: Dict[str, Dict[str, float]] = {
    "default":        {"flood": 1.0, "wildfire": 1.0, "heat": 1.0, "drought": 1.0},
    "infrastructure": {"flood": 1.0, "wildfire": 0.8, "heat": 0.9, "drought": 0.5},
    "energy":         {"flood": 1.1, "wildfire": 1.0, "heat": 1.2, "drought": 0.8},
    "agriculture":    {"flood": 0.9, "wildfire": 0.9, "heat": 1.3, "drought": 1.5},
    "real estate":    {"flood": 1.2, "wildfire": 1.1, "heat": 0.7, "drought": 0.3},
}

_RCP_ALIASES = {
    "rcp26": "rcp26", "rcp45": "rcp45", "rcp60": "rcp60", "rcp85": "rcp85",
    "ssp119": "rcp26", "ssp126": "rcp26", "ssp245": "rcp45", "ssp370": "rcp60", "ssp585": "rcp85",
    "paris": "rcp26", "baseline": "rcp45", "failed": "rcp85",
}


def norm_rcp(label: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", str(label).lower())
    key = {"rcp85": "rcp85", "rcp26": "rcp26", "rcp45": "rcp45", "rcp60": "rcp60"}.get(key.replace("rcp8.5", "rcp85"), key)
    if key in _RCP_ALIASES:
        return _RCP_ALIASES[key]
    raise ValueError(f"unknown climate scenario {label!r}; use rcp26/45/60/85 or ssp119..ssp585")


def trend(year: int, rcp: str, hazard: str) -> float:
    """Multiplicative change of the annual event rate relative to BASE_YEAR."""
    slope = PRIORS[hazard].trend[norm_rcp(rcp)]
    return math.exp(slope * (year - BASE_YEAR))


def vuln_mult(asset_type: str, hazard: str) -> float:
    row = VULN_MULT.get(str(asset_type).strip().lower(), VULN_MULT["default"])
    return row[hazard]
