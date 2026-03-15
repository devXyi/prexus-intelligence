"""
layer5/intelligence.py
Meteorium Engine — Fused Intelligence Scoring
This is the brain. Takes the IntelligencePacket from fusion.py
and produces final risk scores with compound event amplification.

The key insight from your research:
  "Companies don't win because of satellites.
   They win because of data fusion."

This module operationalizes that thesis:
  - Compound events get amplified risk scores (not just additive)
  - Satellite signals provide ground-truth confirmation
  - Correlated anomalies increase confidence, not just severity
  - Cross-source validation catches signal noise
"""

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from adapters.fusion import (
    SignalFusion, IntelligenceSynthesizer,
    IntelligencePacket, FusedSignal,
)
from adapters.base import TelemetryRecord
from adapters.planet import SatelliteAdapters
from core.config import SCENARIO_MULTIPLIERS, ASSET_VULNERABILITY, MONTE_CARLO_DRAWS
from core.models import AssetRiskResult, PortfolioRiskResult, RiskAlert

logger = logging.getLogger("meteorium.intelligence")

# ─── Rust MC ──────────────────────────────────────────────────────────────────
try:
    import meteorium_engine as _rust
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False


class FusedRiskEngine:
    """
    The complete intelligence engine.
    Layer 1 telemetry → fusion → amplified risk scoring → structured result.

    Unlike layer5/engine.py which scores physical + transition independently,
    this engine:
      1. Fuses all signals including satellite
      2. Detects compound events
      3. Applies compound amplifiers to Monte Carlo
      4. Returns intelligence packet alongside risk scores
    """

    def __init__(self, n_draws: int = MONTE_CARLO_DRAWS):
        self.n_draws       = n_draws
        self.fusion        = SignalFusion()
        self.synthesizer   = IntelligenceSynthesizer()
        self.satellites    = SatelliteAdapters()

    async def score_with_satellites(
        self,
        asset_id:     str,
        lat:          float,
        lon:          float,
        base_records: list[TelemetryRecord],   # from Layer 1 workers
        asset_type:   str  = "infrastructure",
        value_mm:     float = 10.0,
        scenario:     str  = "baseline",
        horizon_days: int  = 365,
        country_code: str  = "IND",
    ) -> dict:
        """
        Full fused intelligence pipeline:
          1. Fetch satellite imagery signals
          2. Merge with base telemetry (weather + fire + carbon)
          3. Fuse all signals
          4. Detect compound events
          5. Score with amplification
          6. Return complete intelligence packet
        """

        # Step 1: Get satellite signals
        satellite_records = await self.satellites.fetch_all(lat, lon)
        all_records       = base_records + satellite_records

        logger.info(
            f"[Intelligence] {asset_id}: {len(base_records)} base + "
            f"{len(satellite_records)} satellite = {len(all_records)} total signals"
        )

        # Step 2: Fuse all signals
        fused_signals = self.fusion.fuse(all_records)

        # Step 3: Synthesize intelligence packet
        packet = self.synthesizer.synthesize(fused_signals, asset_type, country_code)

        # Step 4: Compute physical and transition risk from fused signals
        physical_risk   = self._compute_physical_risk(fused_signals, packet, asset_type)
        transition_risk = self._compute_transition_risk(fused_signals, scenario, horizon_days)

        # Step 5: Apply compound event amplification
        base_physical   = physical_risk
        base_transition = transition_risk

        if packet.has_compound_event:
            amp              = packet.max_compound_amplifier
            physical_risk    = min(1.0, physical_risk * amp)
            logger.info(
                f"[Intelligence] {asset_id}: compound amplifier {amp:.2f}× "
                f"applied → physical {base_physical:.3f} → {physical_risk:.3f}"
            )

        # Step 6: Monte Carlo with fused + amplified inputs
        if RUST_AVAILABLE:
            try:
                cr, var95, cvar95, loss_mm, confidence = _rust.monte_carlo_asset(
                    physical_risk   = physical_risk,
                    transition_risk = transition_risk,
                    asset_value_mm  = value_mm,
                    scenario        = scenario,
                    asset_type      = asset_type,
                    horizon_days    = horizon_days,
                    n_draws         = self.n_draws,
                )
                engine_tag = f"rust_fused_n{self.n_draws}"
            except Exception as e:
                logger.warning(f"Rust MC error: {e}")
                cr, var95, cvar95, loss_mm, confidence = self._python_mc(
                    physical_risk, transition_risk, value_mm, scenario, horizon_days
                )
                engine_tag = "python_fused_fallback"
        else:
            cr, var95, cvar95, loss_mm, confidence = self._python_mc(
                physical_risk, transition_risk, value_mm, scenario, horizon_days
            )
            engine_tag = "python_fused_fallback"

        # Step 7: Build alerts
        alerts = self._generate_alerts(asset_id, packet, cr, physical_risk, transition_risk)

        # Step 8: Stress test
        stress = []
        if RUST_AVAILABLE:
            try:
                raw = _rust.stress_test_scenarios(
                    physical_risk, transition_risk, value_mm,
                    asset_type, min(self.n_draws, 5000),
                )
                stress = [
                    {"label": l, "composite_risk": round(c, 4),
                     "var_95": round(v, 4), "expected_loss_mm": round(loss, 2)}
                    for l, c, v, loss in raw
                ]
            except Exception:
                pass

        return {
            "asset_id":          asset_id,
            "composite_risk":    round(cr,             4),
            "physical_risk":     round(physical_risk,  4),
            "transition_risk":   round(transition_risk,4),
            "var_95":            round(var95,           4),
            "cvar_95":           round(cvar95,          4),
            "loss_expected_mm":  round(loss_mm,         2),
            "confidence":        round(confidence,      4),
            "scenario":          scenario,
            "horizon_days":      horizon_days,

            # Intelligence layer
            "intelligence":      packet.to_dict(),
            "compound_events":   packet.compound_events,
            "compound_amplifier":round(packet.max_compound_amplifier, 3),
            "critical_signals":  packet.critical_signals,
            "satellite_signals": len(satellite_records),

            "stress_scenarios":  stress,
            "alerts":            [a.to_dict() for a in alerts],
            "engine":            engine_tag,
            "sources": {
                "base_telemetry":    len(base_records),
                "satellite":        len(satellite_records),
                "total_signals":    len(all_records),
                "fused_variables":  len(fused_signals),
                "active_sources":   packet.active_sources,
            },
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _compute_physical_risk(
        self,
        fused:      dict[str, FusedSignal],
        packet:     IntelligencePacket,
        asset_type: str,
    ) -> float:
        """
        Physical risk from fused signals.
        Satellite imagery CONFIRMS or CONTRADICTS weather-model signals.
        Confirmed signals get higher weight.
        """
        vuln = ASSET_VULNERABILITY.get(asset_type.lower(), 1.0)

        def get(var: str, default: float = 0.0) -> float:
            return fused[var].value if var in fused else default

        # Core hazard scores
        heat_score   = self._sigmoid(get("temp_anomaly_c"), center=1.5, steepness=0.8)
        heat_score   = max(heat_score, get("heat_stress_prob_7d"))
        drought      = min(1.0, get("drought_index") + max(0.0, -get("precip_anomaly_pct") / 100) * 0.3)
        fire         = min(1.0, get("fire_prob_100km") * 0.6 + get("fire_hazard_score") * 0.4)
        flood        = min(1.0, get("flood_signal") * 0.7 + max(0.0, get("precip_anomaly_pct") / 100) * 0.3)
        wind         = min(1.0, get("extreme_wind_prob_7d") * 0.7 + max(0.0, (get("wind_speed_ms") - 15) / 25) * 0.3)

        # Satellite confirmation multipliers
        # If satellite confirms a hazard, confidence increases and score is boosted
        sat_fire_confirm = 1.0 + get("burn_scar_signal") * 0.4    # burn scar confirms fire
        sat_flood_confirm = 1.0 + get("flood_signal") * 0.3       # NDWI confirms flood
        sat_drought_confirm = 1.0 + get("vegetation_stress") * 0.3  # NDVI loss confirms drought

        fire    = min(1.0, fire    * sat_fire_confirm)
        flood   = min(1.0, flood   * sat_flood_confirm)
        drought = min(1.0, drought * sat_drought_confirm)

        # Weighted composite
        composite = (
            heat_score * 0.22 +
            drought    * 0.20 +
            fire       * 0.18 +
            flood      * 0.18 +
            wind       * 0.12 +
            0.0        * 0.10   # sea level placeholder
        )

        return min(1.0, max(0.0, composite * vuln))

    def _compute_transition_risk(
        self,
        fused:        dict[str, FusedSignal],
        scenario:     str,
        horizon_days: int,
    ) -> float:
        def get(var: str, default: float = 0.0) -> float:
            return fused[var].value if var in fused else default

        carbon_price = {
            "ssp119": 250.0, "paris": 250.0, "ssp245": 100.0,
            "baseline": 80.0, "ssp370": 55.0, "ssp585": 20.0, "failed": 20.0,
        }.get(scenario, 80.0)

        price_norm  = min(1.0, carbon_price / 250.0)
        horizon_amp = min(1.3, 1.0 + (horizon_days / 365.0) * 0.15)

        composite = (
            get("co2_intensity_norm")    * 0.30 +
            get("carbon_policy_risk")    * 0.25 +
            get("transition_risk_score") * 0.25 +
            price_norm                   * 0.20
        ) * horizon_amp

        return min(1.0, max(0.0, composite))

    def _generate_alerts(
        self,
        asset_id:        str,
        packet:          IntelligencePacket,
        composite_risk:  float,
        physical_risk:   float,
        transition_risk: float,
    ) -> list[RiskAlert]:
        alerts = []
        now    = datetime.now(timezone.utc).isoformat()

        # Compound event alerts (highest priority)
        for event in packet.compound_events:
            alerts.append(RiskAlert(
                alert_id  = f"AL-{asset_id}-COMPOUND-{event['type'][:8].upper()}",
                asset_id  = asset_id,
                severity  = event["severity"],
                risk_type = "PHYSICAL",
                message   = event["description"] + f" Damage amplifier: {event['amplifier']:.1f}×",
                score     = composite_risk,
                source    = "Meteorium Fusion Engine · Compound Event Detection",
                timestamp = now,
            ))

        # Critical signal alerts
        for sig in packet.critical_signals:
            alerts.append(RiskAlert(
                alert_id  = f"AL-{asset_id}-SIG-{sig['variable'][:8].upper()}",
                asset_id  = asset_id,
                severity  = "CRITICAL" if sig["anomaly_score"] > 0.7 else "HIGH",
                risk_type = "PHYSICAL" if sig["category"] != "transition_risk" else "TRANSITION",
                message   = f"Critical signal: {sig['variable']} = {sig['value']:.3f} "
                             f"(anomaly score: {sig['anomaly_score']:.2f})",
                score     = float(sig["value"]),
                source    = ", ".join(sig["sources"]),
                timestamp = now,
            ))

        return alerts

    @staticmethod
    def _sigmoid(x: float, center: float = 0.0, steepness: float = 1.0) -> float:
        return 1.0 / (1.0 + math.exp(-steepness * (x - center)))

    def _python_mc(self, pr, tr, val, scen, days) -> tuple:
        import random, statistics as st
        s  = SCENARIO_MULTIPLIERS.get(scen, 1.0)
        h  = min(1.3, (days / 365.0) ** 0.5)
        n  = min(self.n_draws, 2000)
        losses = []
        for _ in range(n):
            p = max(0.0, min(1.0, random.gauss(pr, 0.12)))
            t = max(0.0, min(1.0, random.gauss(tr, 0.10)))
            c = (p * 0.6 + t * 0.4) * s * h
            sev = max(0.0, random.lognormvariate(-1.6, 0.65))
            losses.append(min(c * sev * val, val * 0.95))
        losses.sort()
        mean_l = st.mean(losses)
        v95    = losses[int(n * 0.95)]
        cv95   = st.mean(losses[int(n * 0.95):]) if losses[int(n * 0.95):] else v95
        cr     = min(1.0, (pr * 0.6 + tr * 0.4) * s)
        return cr, v95 / val, cv95 / val, mean_l, 0.80

