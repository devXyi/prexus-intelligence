// =============================================================================
// Meteorium Engine — mc_asset.rs
// Prexus Intelligence · v2.0.0
//
// Asset-level Monte Carlo simulation and scenario stress testing.
// Called from intelligence.py via PyO3 as:
//   _rust.monte_carlo_asset(...)
//   _rust.stress_test_scenarios(...)
//
// Mirrors the Python fallback logic in intelligence.py exactly,
// but runs 10–40× faster via rayon parallel draws.
// =============================================================================

use rayon::prelude::*;
use rand::SeedableRng;
use rand::rngs::SmallRng;
use rand_distr::{Normal, LogNormal, Distribution};

// ── Scenario registry ─────────────────────────────────────────────────────────
// (display_label, scenario_key) — mirrors Python SCENARIO_MULTIPLIERS
const STRESS_SCENARIOS: &[(&str, &str)] = &[
    ("Baseline",       "baseline"),
    ("Paris 1.5°C",    "paris"),
    ("SSP2-4.5",       "ssp245"),
    ("SSP3-7.0",       "ssp370"),
    ("SSP5-8.5",       "ssp585"),
    ("Policy Failure", "failed"),
];

/// Scenario loss multiplier — matches Python SCENARIO_MULTIPLIERS
pub fn scenario_multiplier(scenario: &str) -> f64 {
    match scenario.to_lowercase().as_str() {
        // Must equal data-engine/python/core/config.py SCENARIO_MULTIPLIERS.
        // (v1 had these REVERSED — Paris 1.40 … SSP5-8.5 0.70 — so the Rust path ranked
        // the hottest scenario as the least risky. tests/test_rust_parity.py now guards this.)
        "ssp119" | "paris"    => 0.88,
        "ssp245" | "baseline" => 1.12,
        "ssp370"              => 1.24,
        "ssp585" | "failed"   => 1.38,
        _                     => 1.00,
    }
}

/// Asset vulnerability coefficient — matches Python ASSET_VULNERABILITY
pub fn asset_vulnerability(asset_type: &str) -> f64 {
    match asset_type.to_lowercase().as_str() {
        // Must equal data-engine/python/core/config.py ASSET_VULNERABILITY.
        "agriculture"                => 1.35,
        "energy"                     => 1.20,
        "infrastructure" | "transport" => 1.15,
        "real estate" | "real_estate"  => 1.10,
        "manufacturing"              => 1.08,
        "technology"                 => 1.05,
        "healthcare"                 => 1.00,
        "financial"                  => 0.85,
        "coastal"                    => 1.20,
        _                            => 1.00,
    }
}

// ── Asset Monte Carlo ─────────────────────────────────────────────────────────

/// Returns (composite_risk, var95, cvar95, mean_loss_mm, confidence)
///
/// var95 and cvar95 are normalised to [0, 1] as fractions of asset_value_mm
/// so they can be stored directly in the risk result.
pub fn run_asset_mc(
    physical_risk:   f64,
    transition_risk: f64,
    asset_value_mm:  f64,
    scenario:        &str,
    asset_type:      &str,
    horizon_days:    i64,
    n_draws:         usize,
    seed:            u64,
) -> (f64, f64, f64, f64, f64) {
    let s_mult      = scenario_multiplier(scenario);
    let vuln        = asset_vulnerability(asset_type);
    let horizon_amp = (1.0_f64 + (horizon_days as f64 / 365.0) * 0.15).min(1.30);
    let master_seed = if seed == 0 { rand::random::<u64>() } else { seed };

    // ── Parallel draw ─────────────────────────────────────────────────────────
    let mut losses: Vec<f64> = (0..n_draws)
        .into_par_iter()
        .map(|i| {
            let seed_i  = master_seed ^ (i as u64).wrapping_mul(0x9e3779b97f4a7c15);
            let mut rng = SmallRng::seed_from_u64(seed_i);

            // Physical and transition perturbation
            let p = Normal::new(physical_risk,   0.12)
                .expect("constant std-dev is valid")
                .sample(&mut rng)
                .clamp(0.0, 1.0);
            let t = Normal::new(transition_risk, 0.10)
                .expect("constant std-dev is valid")
                .sample(&mut rng)
                .clamp(0.0, 1.0);

            // Composite draw with scenario + horizon + vulnerability
            let composite = (p * 0.60 + t * 0.40) * s_mult * horizon_amp * vuln;

            // Loss severity — log-normal tail matching empirical asset loss distributions
            let severity  = LogNormal::new(-1.60_f64, 0.65_f64)
                .expect("constant parameters are valid")
                .sample(&mut rng);

            (composite * severity * asset_value_mm).min(asset_value_mm * 0.95_f64)
        })
        .collect();

    losses.sort_by(|a, b| a.total_cmp(b)); // total order: NaN can no longer panic the sort

    let mean_loss = losses.iter().sum::<f64>() / n_draws as f64;
    let idx95     = ((n_draws as f64 * 0.95) as usize).min(n_draws - 1);
    let var95_mm  = losses[idx95];
    let cvar95_mm = {
        let tail = &losses[idx95..];
        if tail.is_empty() { var95_mm } else { tail.iter().sum::<f64>() / tail.len() as f64 }
    };

    // Deterministic composite risk (point estimate, not sampled)
    let composite_risk = ((physical_risk * 0.60 + transition_risk * 0.40) * s_mult * vuln)
        .clamp(0.0, 1.0);

    // Confidence: inverse of coefficient of variation — tight dist = high confidence
    let variance   = losses.iter()
        .map(|l| (l - mean_loss).powi(2))
        .sum::<f64>()
        / n_draws as f64;
    let cv         = if mean_loss > 1e-9 { variance.sqrt() / mean_loss } else { 1.0 };
    let confidence = (1.0 - cv * 0.25).clamp(0.60, 0.97);

    (
        composite_risk,
        var95_mm  / asset_value_mm.max(1e-9),
        cvar95_mm / asset_value_mm.max(1e-9),
        mean_loss,
        confidence,
    )
}

// ── Stress test ───────────────────────────────────────────────────────────────

/// Run all 6 standard scenarios. Returns Vec<(label, composite_risk, var95, mean_loss_mm)>
/// var95 is normalised as a fraction of asset_value_mm.
pub fn run_stress_scenarios(
    physical_risk:   f64,
    transition_risk: f64,
    asset_value_mm:  f64,
    asset_type:      &str,
    n_draws:         usize,
) -> Vec<(String, f64, f64, f64)> {
    STRESS_SCENARIOS
        .par_iter()
        .map(|(label, scenario_key)| {
            let (cr, var95, _cvar, loss, _conf) = run_asset_mc(
                physical_risk,
                transition_risk,
                asset_value_mm,
                scenario_key,
                asset_type,
                365,        // standard 1-year horizon for stress test
                n_draws,
                42,
            );
            (label.to_string(), cr, var95, loss)
        })
        .collect()
}


#[cfg(test)]
mod tests {
    use super::*;

    const N: usize = 20_000;

    #[test]
    fn scenario_multipliers_increase_with_warming() {
        let order = ["paris", "baseline", "ssp370", "ssp585"];
        for w in order.windows(2) {
            assert!(scenario_multiplier(w[0]) < scenario_multiplier(w[1]), "{} !< {}", w[0], w[1]);
        }
        assert_eq!(scenario_multiplier("SSP585"), scenario_multiplier("failed"));
    }

    #[test]
    fn deterministic_for_fixed_seed() {
        let a = run_asset_mc(0.6, 0.4, 100.0, "baseline", "infrastructure", 365, N, 7);
        let b = run_asset_mc(0.6, 0.4, 100.0, "baseline", "infrastructure", 365, N, 7);
        assert_eq!(a, b);
    }

    #[test]
    fn outputs_are_bounded_and_ordered() {
        let (cr, var95, cvar95, mean, conf) = run_asset_mc(0.7, 0.5, 250.0, "ssp585", "agriculture", 1000, N, 3);
        assert!((0.0..=1.0).contains(&cr));
        assert!((0.0..=0.95).contains(&var95), "var95 {}", var95);
        assert!(cvar95 >= var95 - 1e-12, "cvar {} < var {}", cvar95, var95);
        assert!(mean > 0.0 && mean <= 0.95 * 250.0);
        assert!((0.60..=0.97).contains(&conf));
    }

    #[test]
    fn loss_increases_with_risk_and_scenario() {
        let lo = run_asset_mc(0.2, 0.2, 100.0, "baseline", "infrastructure", 365, N, 11).3;
        let hi = run_asset_mc(0.8, 0.8, 100.0, "baseline", "infrastructure", 365, N, 11).3;
        assert!(hi > lo);
        let cool = run_asset_mc(0.5, 0.5, 100.0, "paris", "infrastructure", 365, N, 11).3;
        let hot = run_asset_mc(0.5, 0.5, 100.0, "ssp585", "infrastructure", 365, N, 11).3;
        assert!(hot > cool, "hot-house scenario must not be cheaper than Paris");
    }

    #[test]
    fn stress_test_is_ordered_by_warming() {
        let r = run_stress_scenarios(0.5, 0.5, 100.0, "infrastructure", N);
        let get = |k: &str| r.iter().find(|x| x.0 == k).unwrap().3;
        assert!(get("Paris 1.5°C") < get("Baseline"));
        assert!(get("Baseline") < get("SSP3-7.0"));
        assert!(get("SSP3-7.0") < get("SSP5-8.5"));
        assert_eq!(r.len(), 6);
    }

    #[test]
    fn nan_input_cannot_panic_the_sort() {
        // Boundary validation rejects NaN; this proves the core no longer panics if it slips through.
        let _ = run_asset_mc(f64::NAN, 0.5, 100.0, "baseline", "infrastructure", 365, 1_000, 5);
    }

    #[test]
    fn single_draw_is_fine() {
        let (_, var95, cvar95, mean, _) = run_asset_mc(0.5, 0.5, 10.0, "baseline", "infrastructure", 30, 1, 9);
        assert!(var95 >= 0.0 && cvar95 >= 0.0 && mean >= 0.0);
    }

    #[test]
    fn validation_rejects_bad_inputs() {
        use crate::validate_asset_inputs as v;
        assert!(v(0.5, 0.5, 10.0, 365, 1000).is_ok());
        for bad in [
            v(f64::NAN, 0.5, 10.0, 365, 1000), v(1.5, 0.5, 10.0, 365, 1000), v(0.5, -0.1, 10.0, 365, 1000),
            v(0.5, 0.5, 0.0, 365, 1000), v(0.5, 0.5, f64::INFINITY, 365, 1000), v(0.5, 0.5, 10.0, -1, 1000),
            v(0.5, 0.5, 10.0, 365, 0), v(0.5, 0.5, 10.0, 365, crate::MAX_DRAWS + 1),
        ] {
            assert!(bad.is_err());
        }
    }
}
