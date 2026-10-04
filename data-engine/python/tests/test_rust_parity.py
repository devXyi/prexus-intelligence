"""The Rust core and the Python config must agree on every model parameter.
v1 had the Rust scenario table REVERSED (Paris 1.40 … SSP5-8.5 0.70) and nothing noticed.
Skipped when the extension wheel is not installed (CI builds it with maturin first)."""
import pytest

me = pytest.importorskip("meteorium_engine", reason="Rust extension not built (maturin build)")

from core import config


def test_scenario_multipliers_identical():
    for k, v in config.SCENARIO_MULTIPLIERS.items():
        assert me.scenario_multiplier(k) == pytest.approx(v), k
    assert me.scenario_multiplier("SSP585") == me.scenario_multiplier("ssp585")      # case-insensitive


def test_asset_vulnerability_identical():
    for k, v in config.ASSET_VULNERABILITY.items():
        assert me.asset_vulnerability(k) == pytest.approx(v), k


def test_hotter_scenario_is_never_cheaper():
    order = ["paris", "baseline", "ssp370", "ssp585"]
    losses = [me.monte_carlo_asset(0.5, 0.5, 100.0, s, "infrastructure", 365, 200_000)[3] for s in order]
    assert losses == sorted(losses), losses


def test_bad_inputs_raise_instead_of_crashing_the_process():
    for args in [(float("nan"), .5, 10., "baseline", "infrastructure", 365, 1000),
                 (.5, .5, 10., "baseline", "infrastructure", 365, 10**9),
                 (.5, .5, -1., "baseline", "infrastructure", 365, 1000),
                 (.5, .5, 10., "baseline", "infrastructure", -5, 1000)]:
        with pytest.raises(ValueError):
            me.monte_carlo_asset(*args)


def test_engine_uses_rust_when_available():
    from layer5.engine import RUST_AVAILABLE
    assert RUST_AVAILABLE is True
