"""Transparent v0 scoring. Every number is a posterior or a noisy-OR of posteriors — no hidden weights.

* Event rates: Gamma–Poisson (conjugate). λ ~ Gamma(α0, β0) with an EMPIRICAL-BAYES prior from the
  regional average; after W weeks with Σn events: Gamma(α0+Σn, β0+W). P(≥1 event in τ weeks) =
  1 − (β/(β+τ))^α (negative-binomial predictive).
* Cyber: noisy-OR of EPSS over KEV CVEs matching the asset's technologies, ASSUMING UNPATCHED
  (an upper bound; supply `patched_cves` to remove entries).
* Combined: 1 − Π(1 − pᵢ). Output is labelled calibrated=False until backtest.py says otherwise.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
from scipy import stats

from . import METHOD, geo
from .model import parse_ts

UNREST = ("protest", "coercion", "military-posture")
VIOLENCE = ("assault", "armed-conflict", "mass-violence")
THERMAL = ("thermal-anomaly",)
PRIOR_WEEKS = 8.0
MIN_PRIOR_MEAN = 0.02            # never let the prior rate collapse to ~0 (regions with no history)


def posterior(counts: Sequence[int], prior_mean: float, prior_weeks: float = PRIOR_WEEKS) -> tuple[float, float]:
    pm = max(float(prior_mean), MIN_PRIOR_MEAN)
    return pm * prior_weeks + float(np.sum(counts)), prior_weeks + len(counts)


def prob_at_least_one(alpha: float, beta: float, horizon_weeks: float) -> float:
    return float(1.0 - (beta / (beta + horizon_weeks)) ** alpha)


def rate_ci(alpha: float, beta: float, level: float = 0.9) -> tuple[float, float]:
    lo, hi = stats.gamma.ppf([(1 - level) / 2, 1 - (1 - level) / 2], a=alpha, scale=1.0 / beta)
    return float(lo), float(hi)


def weekly_counts(times: Iterable[datetime], end: datetime, weeks: int) -> np.ndarray:
    """Counts per week, oldest → newest, for the `weeks` weeks ending at `end`."""
    out = np.zeros(weeks, dtype=int)
    for t in times:
        age = (end - t).total_seconds() / (7 * 86400)
        if 0 <= age < weeks:
            out[weeks - 1 - int(age)] += 1
    return out


def _event_view(body: Dict[str, Any]) -> tuple[str, datetime, str]:
    return body["category"], parse_ts(body["event_time"]), body["h3_r7"]


def regional_prior(events: Sequence[Dict[str, Any]], categories: Sequence[str], end: datetime, weeks: int) -> float:
    """Mean weekly rate per res-5 area over all areas that have any events (empirical Bayes)."""
    per_area = defaultdict(list)
    for e in events:
        cat, t, c = _event_view(e)
        if cat in categories:
            per_area[geo.parent(c)].append(t)
    if not per_area:
        return MIN_PRIOR_MEAN
    return float(np.mean([weekly_counts(ts, end, weeks).mean() for ts in per_area.values()]))


def _component(events, area, categories, end, weeks, horizon, prior_mean) -> Dict[str, Any]:
    sel = [(e["id"], _event_view(e)) for e in events if e["category"] in categories and geo.parent(e["h3_r7"]) in area]
    counts = weekly_counts([v[1] for _, v in sel], end, weeks)
    a, b = posterior(counts, prior_mean)
    lo, hi = rate_ci(a, b)
    last4 = int(counts[-4:].sum())
    return {"p": prob_at_least_one(a, b, horizon), "rate_per_week": {"mean": a / b, "ci90": [lo, hi]}, "events_in_window": int(counts.sum()),
            "events_last_4_weeks": last4, "prior_mean_per_week": max(prior_mean, MIN_PRIOR_MEAN),
            "evidence": [i for i, _ in sel][-20:]}


def cyber_exposure(technologies: Sequence[str], vulns: Sequence[Dict[str, Any]], patched: Sequence[str] = ()) -> Dict[str, Any]:
    techs = [t.lower() for t in technologies]
    matched = []
    for v in vulns:
        name = v.get("name", "")
        if name in patched:
            continue
        hay = f"{v.get('x_prexus_vendor_project', '')} {v.get('x_prexus_product', '')}".lower()
        if any(t and (t in hay or hay.strip() in t) for t in techs):
            matched.append({"cve": name, "epss": v.get("x_prexus_epss"), "ransomware": v.get("x_prexus_ransomware_use") == "Known", "id": v["id"]})
    probs = [m["epss"] if m["epss"] is not None else 0.05 for m in matched]
    p = float(1.0 - np.prod([1.0 - x for x in probs])) if probs else 0.0
    return {"p": p, "matched": matched, "assumption": "asset assumed unpatched for every matched KEV CVE (upper bound); EPSS = 30-day exploitation probability; missing EPSS → 0.05"}


def noisy_or(ps: Iterable[float]) -> float:
    return float(1.0 - np.prod([1.0 - p for p in ps]))


def score_asset(asset: Dict[str, Any], events: Sequence[Dict[str, Any]], vulns: Sequence[Dict[str, Any]], *, now: Optional[datetime] = None,
                weeks: int = 26, horizon_weeks: float = 4.0, ring: int = 1, patched: Sequence[str] = ()) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    area = geo.area_cells(asset["h3_r7"], ring)
    comps: Dict[str, Any] = {}
    for name, cats in (("unrest", UNREST), ("violence", VIOLENCE), ("thermal", THERMAL)):
        comps[name] = _component(events, area, cats, now, weeks, horizon_weeks, regional_prior(events, cats, now, weeks))
    comps["cyber"] = cyber_exposure(asset.get("technologies", []), vulns, patched)
    risk = noisy_or(c["p"] for c in comps.values())
    return {"asset_id": asset["id"], "asset_name": asset.get("name"), "criticality": asset.get("criticality"), "method": METHOD, "calibrated": False,
            "disclaimer": "Transparent v0 model with an empirical-Bayes prior; not yet back-tested on your history. Do not treat as a calibrated probability.",
            "horizon_weeks": horizon_weeks, "window_weeks": weeks, "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "components": comps, "risk": risk}
