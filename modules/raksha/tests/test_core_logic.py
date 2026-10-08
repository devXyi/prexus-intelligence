import json
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from scipy import stats

from raksha import backtest, cascade, geo, scoring
from raksha.cascade import Graph
from raksha.connectors import epss, firms, gdelt, kev
from raksha.model import Labels, det_id
from raksha.store import Store
from conftest import FIX, NOW

END = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


# ── connectors ───────────────────────────────────────────────────────────────
def test_kev_parser_maps_fields_and_rejects_malformed():
    recs, errs = kev.parse((FIX / "kev.json").read_text())
    assert len(recs) == 8 and not errs
    v = json.loads(recs[0].obj.serialize())
    assert v["type"] == "vulnerability" and v["name"].startswith("CVE-") and v["x_prexus_source"] == "cisa-kev"
    assert v["x_prexus_reliability"] == "A" and v["confidence"] == 95
    bad = json.dumps({"vulnerabilities": [{"cveID": "not-a-cve", "dateAdded": "2024-01-01"}, {"cveID": "CVE-2024-0001", "dateAdded": "yesterday"}]})
    r2, e2 = kev.parse(bad)
    assert r2 == [] and len(e2) == 2


def test_gdelt_parser_filters_categories_and_reports_bad_lines():
    recs, errs = gdelt.parse((FIX / "gdelt_events.tsv").read_text())
    events = [json.loads(r.obj.serialize()) for r in recs if r.obj.type == "x-prexus-event"]
    assert len(events) == 178 and len(errs) == 1 and "61 columns" in errs[0]
    assert {e["category"] for e in events} <= {"protest", "military-posture", "coercion", "assault", "armed-conflict", "mass-violence"}
    assert all(e["h3_r7"] and e["location_ref"].startswith("location--") for e in events)
    e = events[0]
    assert e["x_prexus_credibility"] in "234" and e["confidence"] in (75, 55, 35)
    row = ["0"] * 61
    row[28], row[56], row[57], row[59], row[32] = "19", "95.0", "10", "20260401000000", "1"
    assert gdelt.parse("\t".join(row))[0] == []                                   # lat out of range
    assert "invalid coordinates" in gdelt.parse("\t".join(row))[1][0]


def test_firms_drops_low_confidence_and_dedups_by_id():
    recs, errs = firms.parse((FIX / "firms_viirs.csv").read_text())
    evs = [r for r in recs if r.obj.type == "x-prexus-event"]
    assert 0 < len(evs) < 120 and not errs
    assert all(json.loads(r.obj.serialize())["x_prexus_detect_confidence"] in ("n", "h") for r in evs)
    s = Store()
    for r in recs: s.put(r)
    for r in recs: assert s.put(r) == "duplicate"


def test_epss_parser():
    m, d = epss.parse((FIX / "epss.csv").read_text(), ["CVE-2021-44228", "CVE-9999-0000"])
    assert list(m) == ["CVE-2021-44228"] and d == "2026-09-29T00:00:00Z"
    assert epss.parse("cve,epss,percentile\nCVE-1,1.5,0.2\nCVE-2,abc,0.1\n")[0] == {}      # out-of-range / non-numeric dropped


# ── store: idempotence, versioning, pagination ───────────────────────────────
def test_store_versioning_idempotency_and_cursor(loaded_store):
    s = loaded_store
    vid = det_id("vulnerability", "CVE-2021-44228")
    vs = s.versions(vid)
    assert len(vs) == 2 and vs[1].modified > vs[0].modified and "x_prexus_epss" not in vs[0].body and vs[1].body["x_prexus_epss"] == 0.944
    page1 = s.query(types=["x-prexus-event"], limit=50)
    page2 = s.query(types=["x-prexus-event"], limit=50, cursor=Store.cursor_for(page1[-1]))
    assert len(page1) == 50 and {o.id for o in page1}.isdisjoint({o.id for o in page2})
    assert len(s.query(types=["x-prexus-event"], limit=10_000)) == s.count("x-prexus-event")


def test_changed_content_creates_new_version_not_edit():
    s = Store()
    recs, _ = kev.parse((FIX / "kev.json").read_text())
    s.put(recs[0], fetched_at="2026-09-01T00:00:00Z")
    body = json.loads(recs[0].obj.serialize()); body["description"] = "UPDATED"
    assert s.put_body(body, recs[0].labels, fetched_at="2026-09-02T00:00:00Z") == "updated"
    vs = s.versions(recs[0].obj.id)
    assert len(vs) == 2 and vs[0].body["description"] != "UPDATED" and vs[1].body["description"] == "UPDATED"


# ── gamma-Poisson maths ──────────────────────────────────────────────────────
def test_posterior_is_conjugate_update():
    a, b = scoring.posterior([2, 0, 3], prior_mean=0.5, prior_weeks=8)
    assert (a, b) == (0.5 * 8 + 5, 8 + 3)


def test_prob_at_least_one_matches_monte_carlo_predictive():
    a, b, tau = 6.0, 10.0, 4.0
    rng = np.random.default_rng(0)
    lam = rng.gamma(a, 1 / b, 400_000)
    mc = (rng.poisson(lam * tau) >= 1).mean()
    assert scoring.prob_at_least_one(a, b, tau) == pytest.approx(mc, abs=0.003)


def test_rate_ci_and_empirical_bayes_shrinkage():
    a, b = scoring.posterior([0] * 26, prior_mean=1.0, prior_weeks=8)
    lo, hi = scoring.rate_ci(a, b)
    assert 0 < lo < a / b < hi
    assert a / b > 0 and scoring.posterior([], 0.0)[0] > 0                    # floor keeps prior positive
    big = scoring.posterior([5] * 26, 0.1)
    assert 3.5 < big[0] / big[1] < 5.0                                          # data dominates; 8 pseudo-weeks of prior still pull it down a little


def test_weekly_counts_bucketing():
    times = [END - timedelta(days=d) for d in (0.5, 6.9, 7.1, 20, 400)]
    c = scoring.weekly_counts(times, END, 4)
    assert c.tolist() == [0, 1, 1, 2]                                          # oldest → newest; the 400-day-old event is excluded


# ── asset scoring ────────────────────────────────────────────────────────────
def _scored(store, asset_key):
    assets = {o.body["x_prexus_asset_key"]: o.body for o in map(lambda x: x, store.query(types=["x-prexus-asset"]))}
    a = assets[asset_key]
    events = [o.body for o in store.query(types=["x-prexus-event"], limit=100000)]
    vulns = [o.body for o in store.query(types=["vulnerability"])]
    return scoring.score_asset({"id": asset_key, "name": a["name"], "h3_r7": a["h3_r7"], "criticality": a["criticality"], "technologies": a.get("technologies", [])},
                               events, vulns, now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc))


def test_asset_scores_reflect_the_planted_burst_and_cyber_exposure(loaded_store):
    hot, quiet = _scored(loaded_store, "port-alpha"), _scored(loaded_store, "depot-epsilon")
    assert hot["calibrated"] is False and hot["method"] == "raksha-v0" and "Do not treat" in hot["disclaimer"]
    assert hot["components"]["violence"]["events_last_4_weeks"] > quiet["components"]["violence"]["events_last_4_weeks"]
    assert hot["risk"] > quiet["risk"]
    assert {m["cve"] for m in hot["components"]["cyber"]["matched"]} >= {"CVE-2021-26855", "CVE-2023-4966"}
    assert quiet["components"]["cyber"]["p"] == 0.0
    assert all(0.0 <= c["p"] <= 1.0 for c in hot["components"].values()) and 0 <= hot["risk"] <= 1


def test_patching_removes_cyber_exposure(loaded_store):
    a = _scored(loaded_store, "port-alpha")["components"]["cyber"]
    assets = {o.body["x_prexus_asset_key"]: o.body for o in loaded_store.query(types=["x-prexus-asset"])}["port-alpha"]
    vulns = [o.body for o in loaded_store.query(types=["vulnerability"])]
    b = scoring.cyber_exposure(assets.get("technologies", []), vulns, patched=[m["cve"] for m in a["matched"]])
    assert b["p"] == 0.0 and b["matched"] == []


def test_noisy_or_properties():
    assert scoring.noisy_or([]) == 0.0 and scoring.noisy_or([0.3]) == pytest.approx(0.3)
    assert scoring.noisy_or([0.5, 0.5]) == pytest.approx(0.75) and scoring.noisy_or([1.0, 0.2]) == 1.0


# ── cascade vs exact enumeration ─────────────────────────────────────────────
def test_cascade_chain_matches_analytic():
    g = Graph({"a": 0.3, "b": 0.0, "c": 0.0}, [("a", "b", 0.5), ("b", "c", 0.4)])
    ex = cascade.exact(g)
    assert ex["c"] == pytest.approx(0.3 * 0.5 * 0.4) and ex["b"] == pytest.approx(0.15)
    mc = cascade.simulate(g, 400_000, np.random.default_rng(1))["p_fail"]
    assert mc["c"] == pytest.approx(ex["c"], abs=0.003) and mc["b"] == pytest.approx(ex["b"], abs=0.004)


def test_cascade_diamond_and_shared_cause_match_exact():
    g = Graph({"s": 0.4, "x": 0.05, "y": 0.0, "t": 0.1}, [("s", "x", 0.7), ("s", "y", 0.6), ("x", "t", 0.5), ("y", "t", 0.8)])
    ex = cascade.exact(g)
    mc = cascade.simulate(g, 500_000, np.random.default_rng(2))["p_fail"]
    for n in g.nodes:
        assert mc[n] == pytest.approx(ex[n], abs=0.004), n
    assert ex["t"] > 0.1 + 0.4 * 0.7 * 0.5 * 0.9                               # shared cause correlates failures


def test_cascade_monotone_and_validation():
    base = Graph({"a": 0.3, "b": 0.1}, [("a", "b", 0.5)])
    hi = Graph({"a": 0.3, "b": 0.1}, [("a", "b", 0.9)])
    assert cascade.exact(hi)["b"] > cascade.exact(base)["b"] > 0.1
    for bad in (Graph({"a": 1.2}), Graph({"a": 0.1}, [("a", "zzz", 0.5)]), Graph({"a": 0.1}, [("a", "a", 0.5)]), Graph({})):
        with pytest.raises(ValueError): bad.validate()
    with pytest.raises(ValueError): cascade.simulate(base, 0, np.random.default_rng(0))


def test_edge_criticality_ranks_the_load_bearing_dependency():
    g = Graph({"s": 0.5, "u": 0.0, "t": 0.0}, [("s", "u", 0.9), ("u", "t", 0.9), ("s", "t", 0.05)])
    ranked = cascade.edge_criticality(g, "t", 100_000, 3)
    assert ranked[-1]["edge"] == ["s", "t"] and ranked[0]["reduction"] > ranked[-1]["reduction"] > 0


# ── back-test harness ────────────────────────────────────────────────────────
def test_backtest_calibrated_on_stationary_process_and_flags_regime_shift():
    rng = np.random.default_rng(7)
    ok = backtest.backtest(rng.poisson(0.35, 1500), min_train=30, horizon=1)
    assert ok["ece"] < 0.04 and abs(ok["skill_vs_climatology"]) < 0.05
    # the rate triples halfway through: a stationary forecaster must be visibly miscalibrated
    shifted = np.concatenate([rng.poisson(0.1, 400), rng.poisson(0.8, 400)])
    bad = backtest.backtest(shifted, min_train=30, horizon=1)
    assert bad["ece"] > ok["ece"] * 2 and bad["mean_forecast"] < bad["base_rate"]


def test_backtest_beats_climatology_with_a_gamma_distributed_rate():
    """Hierarchical truth (rate ~ Gamma per series) → Bayesian updating should beat plain frequency."""
    rng = np.random.default_rng(11)
    skills = []
    for _ in range(60):
        lam = rng.gamma(2.0, 0.1)
        skills.append(backtest.backtest(rng.poisson(lam, 80), min_train=15)["brier"])
    assert np.mean(skills) < 0.25


def test_backtest_rejects_short_series():
    with pytest.raises(ValueError):
        backtest.backtest([1, 0, 1], min_train=20)
