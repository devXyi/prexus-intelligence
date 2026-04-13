# meteorium_engine — Python Integration Guide
# Prexus Intelligence · v2.0.0
# ─────────────────────────────────────────────────────────────────────────────
# Build:  maturin develop --release
# Import: import meteorium_engine

import json
import meteorium_engine

# ─────────────────────────────────────────────────────────────────────────────
# 1. GBM — Carbon / Commodity price path (financial)
# ─────────────────────────────────────────────────────────────────────────────
gbm_params = {
    "distribution": {
        "type": "gbm",
        "mu": 0.07,        # 7% annualised drift
        "sigma": 0.15,     # 15% annualised volatility
        "s0": 100.0,       # starting price
        "dt": 1 / 252      # daily steps
    },
    "n_paths": 50_000,
    "n_steps": 252,        # 1 trading year
    "seed": 42,
    "label": "carbon_price_1yr"
}
result = json.loads(meteorium_engine.simulate(json.dumps(gbm_params)))
print("── GBM Carbon Price ──────────────────────────────────")
print(f"  Terminal mean : {result['terminal_mean']:.2f}")
print(f"  VaR  95%      : {result['var_95']:.2f}")
print(f"  CVaR 99%      : {result['cvar_99']:.2f}")
print(f"  P5 / P95      : {result['p5']:.2f} / {result['p95']:.2f}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Ornstein–Uhlenbeck — Temperature anomaly (mean-reverting climate)
# ─────────────────────────────────────────────────────────────────────────────
ou_params = {
    "distribution": {
        "type": "mean_reverting",
        "mu": 1.5,         # long-run anomaly target (°C above baseline)
        "theta": 0.3,      # reversion speed
        "sigma": 0.4,      # daily volatility
        "x0": 0.8,         # current anomaly
        "dt": 1 / 365      # daily steps
    },
    "n_paths": 30_000,
    "n_steps": 365,
    "seed": 7,
    "label": "temp_anomaly_1yr"
}
result = json.loads(meteorium_engine.simulate(json.dumps(ou_params)))
print("\n── OU Temperature Anomaly ────────────────────────────")
print(f"  Terminal mean : {result['terminal_mean']:.3f} °C")
print(f"  Median        : {result['p50']:.3f} °C")
print(f"  P99 tail      : {result['p99']:.3f} °C")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Poisson — Extreme event frequency (storm count per season)
# ─────────────────────────────────────────────────────────────────────────────
poisson_params = {
    "distribution": {
        "type": "poisson",
        "lambda": 2.3      # expected storms per week
    },
    "n_paths": 20_000,
    "n_steps": 12,         # 12 weeks
    "seed": 99,
    "label": "storm_frequency"
}
result = json.loads(meteorium_engine.simulate(json.dumps(poisson_params)))
print("\n── Poisson Storm Frequency ───────────────────────────")
print(f"  Mean events / season : {result['terminal_mean']:.2f}")
print(f"  90th percentile      : {result['p90']:.2f}")

# ─────────────────────────────────────────────────────────────────────────────
# 4. Beta — Crop loss fraction (bounded [0, 1])
# ─────────────────────────────────────────────────────────────────────────────
beta_params = {
    "distribution": {
        "type": "beta",
        "alpha": 2.0,
        "beta": 5.0        # right-skewed toward low loss
    },
    "n_paths": 40_000,
    "n_steps": 1,          # single-period loss draw
    "seed": 13,
    "label": "crop_loss_fraction"
}
result = json.loads(meteorium_engine.simulate(json.dumps(beta_params)))
print("\n── Beta Crop Loss Fraction ───────────────────────────")
print(f"  Expected loss  : {result['terminal_mean']:.3%}")
print(f"  VaR 95% loss   : {result['var_95']:.3%}")
print(f"  CVaR 99% loss  : {result['cvar_99']:.3%}")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Batch — Multi-factor scenario (temp + precip + yield, parallel)
# ─────────────────────────────────────────────────────────────────────────────
batch = {
    "scenarios": [
        {
            "distribution": {"type": "normal", "mean": 1.2, "std_dev": 0.6},
            "n_paths": 25_000, "n_steps": 90, "seed": 1,
            "label": "temp_anomaly_q1"
        },
        {
            "distribution": {"type": "lognormal", "mu": 4.5, "sigma": 0.4},
            "n_paths": 25_000, "n_steps": 90, "seed": 2,
            "label": "precipitation_q1"
        },
        {
            "distribution": {"type": "beta", "alpha": 3.0, "beta": 4.0},
            "n_paths": 25_000, "n_steps": 1, "seed": 3,
            "label": "yield_loss_q1"
        }
    ]
}
batch_results = json.loads(meteorium_engine.simulate_batch(json.dumps(batch)))
print("\n── Batch Multi-Factor ────────────────────────────────")
for r in batch_results:
    if "error" in r:
        print(f"  {r['label']}: ERROR — {r['error']}")
    else:
        s = r["stats"]
        print(f"  {r['label']}: mean={s['terminal_mean']:.3f}  p95={s['p95']:.3f}  cvar99={s['cvar_99']:.3f}")

# ─────────────────────────────────────────────────────────────────────────────
# 6. Accessing the time-step envelope (for dashboard charting)
# ─────────────────────────────────────────────────────────────────────────────
result = json.loads(meteorium_engine.simulate(json.dumps(gbm_params)))
mean_path    = result["mean_path"]       # list[float], length == n_steps
lower_band   = result["lower_5_path"]
upper_band   = result["upper_95_path"]

# Feed directly into Meteorium dashboard chart data:
chart_data = {
    "labels": list(range(len(mean_path))),
    "mean":   mean_path,
    "lower":  lower_band,
    "upper":  upper_band,
}
print(f"\n── Envelope (first 5 steps) ──────────────────────────")
for t in range(5):
    print(f"  t={t:3d}  lower={lower_band[t]:.2f}  mean={mean_path[t]:.2f}  upper={upper_band[t]:.2f}")
