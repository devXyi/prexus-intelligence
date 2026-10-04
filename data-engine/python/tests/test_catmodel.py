"""catmodel is verified against closed-form results, not against itself."""
import math

import numpy as np
import pytest
from scipy import stats

from catmodel import copula, engine, frequency, metrics, priors, severity, simulate, validation, vulnerability
from catmodel.priors import PRIORS, HazardPrior, norm_rcp, trend

RNG = lambda s=1: np.random.default_rng(s)


# ── frequency ────────────────────────────────────────────────────────────────
def test_poisson_mean_variance():
    c = frequency.sample_counts(RNG(), 0.7, 400_000)
    assert c.mean() == pytest.approx(0.7, rel=0.01)
    assert c.var() == pytest.approx(0.7, rel=0.02)


def test_negbin_overdispersion_matches_theory():
    lam, k = 0.6, 3.0
    c = frequency.sample_counts(RNG(2), lam, 600_000, dispersion=k)
    assert c.mean() == pytest.approx(lam, rel=0.01)
    assert c.var() == pytest.approx(lam + lam ** 2 / k, rel=0.03)
    assert c.var() > c.mean()


def test_zero_rate_and_negative_rate():
    assert frequency.sample_counts(RNG(), 0.0, 10).sum() == 0
    with pytest.raises(ValueError):
        frequency.sample_counts(RNG(), -1.0, 10)


# ── severity (GPD) ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("xi,sigma", [(0.0, 0.2), (0.15, 0.2), (0.3, 0.1)])
def test_gpd_sampler_matches_analytic_tail(xi, sigma):
    x = severity.gpd_sample(RNG(3), 500_000, xi, sigma)
    if xi < 0.25:   # finite mean & stable sample mean only for small ξ
        assert x.mean() == pytest.approx(severity.gpd_mean(xi, sigma), rel=0.03)
    for q in (0.1, 0.5, 1.0):
        assert (x > q * sigma * 3).mean() == pytest.approx(float(severity.gpd_sf(q * sigma * 3, xi, sigma)), abs=0.004)


def test_gpd_return_level_roundtrip():
    for xi in (0.0, 0.2):
        for p in (0.5, 0.1, 0.01):
            assert float(severity.gpd_sf(severity.gpd_return_level(p, xi, 0.2), xi, 0.2)) == pytest.approx(p, rel=1e-9)


# ── vulnerability ────────────────────────────────────────────────────────────
def test_damage_curve_shape():
    h = PRIORS["flood"]
    x = np.linspace(0, 1, 101)
    d = vulnerability.mean_damage_ratio(x, h)
    assert d[0] == 0.0 and np.all(np.diff(d) >= 0) and d.max() <= h.dmax + 1e-12
    assert vulnerability.mean_damage_ratio(0.5, h, duration_days=30) > vulnerability.mean_damage_ratio(0.5, h)


def test_beta_damage_preserves_mean():
    d = vulnerability.sample_damage(RNG(4), np.full(300_000, 0.3), 20.0)
    assert d.mean() == pytest.approx(0.3, rel=0.01) and d.min() >= 0 and d.max() <= 1


# ── compound loss: AAL against the analytic expectation ──────────────────────
def test_aal_matches_analytic_expected_loss():
    h = HazardPrior("t", 0.5, None, 0.15, 0.10, 0.20, 0.6, 0.55, 1.8, 400.0, {"rcp45": 0.0}, 0.0)
    value, n = 100.0, 300_000
    r = engine.annual_losses(h, value, n, RNG(5))
    # analytic: E[loss/yr] = λ · value · E[mdr(min(thr+E,1))], E ~ GPD (integrated on a fine quantile grid)
    u = (np.arange(400_000) + 0.5) / 400_000
    e = h.sigma * ((1 - u) ** (-h.xi) - 1) / h.xi
    mdr = vulnerability.mean_damage_ratio(np.minimum(h.threshold + e, 1.0), h)
    analytic = h.base_rate * value * float(mdr.mean())
    assert r.annual.mean() == pytest.approx(analytic, rel=0.02)
    assert r.counts.mean() == pytest.approx(h.base_rate, rel=0.01)


def test_losses_bounded_and_consistent():
    r = engine.annual_losses(PRIORS["flood"], 50.0, 50_000, RNG(6), rate_multiplier=5.0)
    assert r.annual.min() >= 0 and r.annual.max() <= 50.0 + 1e-9
    assert np.all(r.max_event <= r.annual + 1e-9)
    assert (r.annual[r.counts == 0] == 0).all()


def test_climate_trend_raises_losses_and_is_ordered_by_scenario():
    assert trend(2023, "rcp85", "flood") == pytest.approx(1.0)
    assert trend(2050, "rcp85", "heat") > trend(2050, "rcp26", "heat") > 1.0
    lo = engine.annual_losses(PRIORS["flood"], 100, 100_000, RNG(7), year=2023, rcp="rcp85").annual.mean()
    hi = engine.annual_losses(PRIORS["flood"], 100, 100_000, RNG(7), year=2050, rcp="rcp85").annual.mean()
    assert hi > lo


def test_scenario_aliases():
    assert norm_rcp("SSP585") == "rcp85" and norm_rcp("rcp8.5") == "rcp85" and norm_rcp("paris") == "rcp26"
    with pytest.raises(ValueError):
        norm_rcp("nonsense")


# ── copula ───────────────────────────────────────────────────────────────────
def test_gaussian_copula_spearman_matches_theory():
    rho = 0.7
    u = copula.copula_uniforms(RNG(8), copula.equicorrelation(2, rho), 200_000)
    sp = stats.spearmanr(u[:, 0], u[:, 1])[0]
    assert sp == pytest.approx(6 / math.pi * math.asin(rho / 2), abs=0.01)


def test_t_copula_has_more_joint_tail_than_gaussian():
    c = copula.equicorrelation(2, 0.5)
    ug = copula.copula_uniforms(RNG(9), c, 400_000, "gaussian")
    ut = copula.copula_uniforms(RNG(9), c, 400_000, "t", nu=4)
    joint = lambda u: np.mean((u[:, 0] > 0.99) & (u[:, 1] > 0.99))
    assert joint(ut) > 1.5 * joint(ug)


def test_portfolio_dependence_increases_tail_risk_but_not_aal():
    n = 100_000
    a = [engine.annual_losses(PRIORS["flood"], 100.0, n, RNG(10 + i), rate_multiplier=2.0).annual for i in range(3)]
    ind = engine.portfolio_annual(RNG(1), a, np.eye(3))
    dep = engine.portfolio_annual(RNG(1), a, copula.equicorrelation(3, 0.9))
    assert dep.mean() == pytest.approx(ind.mean(), rel=0.03)               # AAL is dependence-free
    assert metrics.var(dep, 0.99) > 1.05 * metrics.var(ind, 0.99)          # tail is not


def test_nearest_psd_repairs_invalid_correlation():
    bad = np.array([[1, 0.9, -0.9], [0.9, 1, 0.9], [-0.9, 0.9, 1]])
    fixed = copula.nearest_psd_corr(bad)
    assert np.all(np.linalg.eigvalsh(fixed) > 0) and np.allclose(np.diag(fixed), 1)


# ── metrics ──────────────────────────────────────────────────────────────────
def test_var_tvar_against_exponential():
    x = RNG(11).exponential(1.0, 2_000_000)
    assert metrics.var(x, 0.99) == pytest.approx(math.log(100), rel=0.01)
    assert metrics.tvar(x, 0.99) == pytest.approx(math.log(100) + 1.0, rel=0.01)
    assert metrics.tvar(x, 0.95) >= metrics.var(x, 0.95)


def test_ep_curve_monotone_and_oep_below_aep():
    r = engine.annual_losses(PRIORS["heat"], 100.0, 50_000, RNG(12), rate_multiplier=3.0)
    m = metrics.risk_metrics(r.annual, r.max_event)
    rps = sorted(m["aep"])
    assert all(m["aep"][a] <= m["aep"][b] for a, b in zip(rps, rps[1:]))
    assert all(m["oep"][k] <= m["aep"][k] + 1e-9 for k in rps)
    assert m["tvar"]["0.99"] >= m["var"]["0.99"]


# ── validation harness ───────────────────────────────────────────────────────
def test_crps_matches_closed_form_gaussian():
    obs = np.array([0.0, 0.5, -1.2, 2.0])
    ens = RNG(13).normal(0, 1, (obs.size, 8000))
    z = obs
    analytic = z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / math.sqrt(math.pi)
    assert validation.crps_ensemble(ens, obs) == pytest.approx(analytic, abs=0.02)


def test_crps_zero_for_perfect_ensemble():
    obs = np.array([1.0, 2.0])
    assert np.allclose(validation.crps_ensemble(np.tile(obs[:, None], (1, 5)), obs), 0.0)


def test_brier_and_reliability():
    rng = RNG(14)
    p = rng.random(300_000)
    o_cal = (rng.random(p.size) < p).astype(float)
    o_bad = (rng.random(p.size) < p ** 2).astype(float)
    assert validation.brier_score(o_cal, o_cal) == 0.0
    assert validation.expected_calibration_error(p, o_cal) < 0.01
    assert validation.expected_calibration_error(p, o_bad) > 0.08
    assert validation.brier_score(np.full(1000, 0.3), (RNG(1).random(1000) < 0.3).astype(float)) == pytest.approx(0.21, abs=0.03)


def test_pit_detects_underdispersion():
    rng = RNG(15)
    obs = rng.normal(0, 1, 20_000)
    good = validation.pit_values(rng.normal(0, 1, (obs.size, 200)), obs)
    narrow = validation.pit_values(rng.normal(0, 0.5, (obs.size, 200)), obs)
    assert stats.kstest(good, "uniform").pvalue > 0.001
    assert np.mean((narrow < 0.1) | (narrow > 0.9)) > 0.3       # U-shaped
    assert validation.skill_score(0.5, 1.0) == 0.5


# ── event simulation ─────────────────────────────────────────────────────────
def _sim(**kw):
    base = dict(hazard="flood", intensity=0.5, duration_days=7, target_year=2040, rcp="rcp85",
                value_mm=100.0, composite_risk=0.5, seed=1)
    base.update(kw)
    return simulate.simulate_event(**base)


def test_simulation_is_reproducible_bounded_and_honest():
    a, b = _sim(), _sim()
    assert a["cost_impact"] == b["cost_impact"]
    assert 0 <= a["cost_impact"] <= 100 and 0 <= a["probability_pct"] <= 100
    assert a["calibrated"] is False and "placeholder" in a["parameters"]


def test_simulation_monotonicity():
    assert _sim(intensity=0.9)["cost_impact"] > _sim(intensity=0.3)["cost_impact"]
    assert _sim(value_mm=200)["cost_impact"] == pytest.approx(2 * _sim()["cost_impact"], rel=0.02)
    assert _sim(target_year=2060)["probability_pct"] > _sim(target_year=2030)["probability_pct"]
    assert _sim(intensity=0.9)["probability_pct"] < _sim(intensity=0.3)["probability_pct"]   # rarer events
    assert _sim(rcp="rcp85")["insurance_increase_pct"] > _sim(rcp="rcp26")["insurance_increase_pct"]
    assert _sim(composite_risk=0.9)["cost_impact"] > _sim(composite_risk=0.1)["cost_impact"]


def test_every_hazard_runs():
    for h in PRIORS:
        assert _sim(hazard=h)["damage_label"] in {"Low", "Moderate", "Severe", "Catastrophic"}
