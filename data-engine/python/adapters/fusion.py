"""
adapters/fusion.py
Meteorium Engine — Multi-Signal Data Fusion
Prexus Intelligence · v2.0.0

Fusion pipeline:
  Raw signals (N sources, M variables)
      ↓
  Signal normalization (0-1 scale per variable)
      ↓
  Confidence weighting (freshness × source reliability)
      ↓
  Cross-signal correlation detection
      ↓
  Fused feature vector (single authoritative value per variable)
      ↓
  Anomaly detection (deviation from historical baseline)
      ↓
  Intelligence summary (structured narrative + scores)

Bug fixes applied (v2.0.0):
  [BUG-1] _detect_compound_events — FusedSignal("",0,0,[],0,0,"",False) default
           construction is fragile; breaks silently if FusedSignal signature changes.
           Fix: dict.get() with explicit 0.0 default.
  [BUG-2] _category_score — weighted sum of raw signal values, some of which exceed
           1.0 (e.g. precip_anomaly_pct in [-30, 80]). Result could exceed 1.0 before
           the clamp, masking the actual clamping. Fix: normalise each signal value to
           [0, 1] using its registry normal_range before weighting.
  [BUG-3] _detect_correlations — O(N²) full-scan on every call, even for known pairs.
           Fix: pre-build a lookup set; check membership in O(1).
"""

import logging
import statistics
from typing import Optional

from adapters.base import TelemetryRecord

logger = logging.getLogger("meteorium.fusion")


# ════════════════════════════════════════════════════════════════════════════
# SIGNAL REGISTRY
# ════════════════════════════════════════════════════════════════════════════

SIGNAL_REGISTRY = {

    # ── Weather signals ───────────────────────────────────────────────────
    "temp_anomaly_c": {
        "authoritative_sources": ["ECMWF ERA5 Reanalysis", "Open-Meteo / ECMWF"],
        "fallback_sources":      ["NOAA GFS"],
        "normal_range":          (-2.0, 2.0),
        "critical_threshold":    3.5,
        "fusion_method":         "confidence_weighted_mean",
        "category":              "physical_hazard",
        "weight":                0.18,
    },
    "precip_anomaly_pct": {
        "authoritative_sources": ["Open-Meteo / ECMWF", "ECMWF ERA5 Reanalysis"],
        "normal_range":          (-30.0, 30.0),
        "critical_threshold":    80.0,
        "fusion_method":         "confidence_weighted_mean",
        "category":              "physical_hazard",
        "weight":                0.15,
    },
    "drought_index": {
        "authoritative_sources": ["Open-Meteo / ECMWF"],
        "normal_range":          (0.0, 0.3),
        "critical_threshold":    0.75,
        "fusion_method":         "max_confidence",
        "category":              "physical_hazard",
        "weight":                0.14,
    },
    "heat_stress_prob_7d": {
        "authoritative_sources": ["Open-Meteo / ECMWF"],
        "normal_range":          (0.0, 0.2),
        "critical_threshold":    0.7,
        "fusion_method":         "max_confidence",
        "category":              "physical_hazard",
        "weight":                0.12,
    },

    # ── Fire signals ──────────────────────────────────────────────────────
    "fire_prob_100km": {
        "authoritative_sources": ["NASA FIRMS VIIRS 375m"],
        "fallback_sources":      ["NASA FIRMS MODIS 1km"],
        "normal_range":          (0.0, 0.1),
        "critical_threshold":    0.5,
        "fusion_method":         "max_value",
        "category":              "physical_hazard",
        "weight":                0.13,
    },
    "fire_hazard_score": {
        "authoritative_sources": ["NASA FIRMS VIIRS 375m"],
        "normal_range":          (0.0, 0.15),
        "critical_threshold":    0.6,
        "fusion_method":         "max_value",
        "category":              "physical_hazard",
        "weight":                0.08,
    },

    # ── Vegetation / land cover signals (satellite-derived) ───────────────
    "ndvi": {
        "authoritative_sources": ["Sentinel Hub / ESA Copernicus", "Microsoft Planetary Computer"],
        "fallback_sources":      ["NASA FIRMS VIIRS 375m"],
        "normal_range":          (0.2, 0.8),
        "critical_threshold":    0.1,
        "fusion_method":         "confidence_weighted_mean",
        "category":              "satellite_intelligence",
        "weight":                0.06,
        "invert":                True,
    },
    "vegetation_stress": {
        "authoritative_sources": ["Sentinel Hub / ESA Copernicus"],
        "normal_range":          (0.0, 0.2),
        "critical_threshold":    0.6,
        "fusion_method":         "max_confidence",
        "category":              "satellite_intelligence",
        "weight":                0.07,
    },
    "flood_signal": {
        "authoritative_sources": ["Sentinel Hub / ESA Copernicus"],
        "normal_range":          (0.0, 0.1),
        "critical_threshold":    0.5,
        "fusion_method":         "max_value",
        "category":              "satellite_intelligence",
        "weight":                0.09,
    },
    "burn_scar_signal": {
        "authoritative_sources": ["Sentinel Hub / ESA Copernicus"],
        "normal_range":          (0.0, 0.05),
        "critical_threshold":    0.4,
        "fusion_method":         "max_value",
        "category":              "satellite_intelligence",
        "weight":                0.06,
    },

    # ── Transition risk signals ───────────────────────────────────────────
    "co2_intensity_norm": {
        "authoritative_sources": ["Carbon Monitor"],
        "normal_range":          (0.0, 0.6),
        "critical_threshold":    0.85,
        "fusion_method":         "confidence_weighted_mean",
        "category":              "transition_risk",
        "weight":                0.10,
    },
    "carbon_policy_risk": {
        "authoritative_sources": ["Carbon Monitor"],
        "normal_range":          (0.0, 0.5),
        "critical_threshold":    0.80,
        "fusion_method":         "confidence_weighted_mean",
        "category":              "transition_risk",
        "weight":                0.08,
    },
}

# [FIX-BUG-3] Pre-build correlation pair set for O(1) lookup
_CORRELATION_PAIRS: dict[tuple[str, str], str] = {
    ("drought_index",      "fire_prob_100km"):    "drought amplifies fire risk",
    ("temp_anomaly_c",     "heat_stress_prob_7d"):"heat anomaly drives stress events",
    ("vegetation_stress",  "drought_index"):      "vegetation stress confirms drought",
    ("flood_signal",       "precip_anomaly_pct"): "satellite flood confirms precip excess",
    ("co2_intensity_norm", "carbon_policy_risk"): "emissions intensity drives policy exposure",
}


# ════════════════════════════════════════════════════════════════════════════
# FUSION ENGINE
# ════════════════════════════════════════════════════════════════════════════

class SignalFusion:
    """
    Fuses TelemetryRecords from multiple sources into a single
    authoritative feature vector per variable.
    """

    def __init__(self, staleness_hours: float = 48.0):
        self.staleness_hours = staleness_hours

    def fuse(self, records: list[TelemetryRecord]) -> dict[str, "FusedSignal"]:
        by_variable: dict[str, list[TelemetryRecord]] = {}
        for rec in records:
            by_variable.setdefault(rec.variable, []).append(rec)

        return {
            variable: signal
            for variable, recs in by_variable.items()
            if (signal := self._fuse_variable(variable, recs)) is not None
        }

    def _fuse_variable(
        self,
        variable: str,
        records:  list[TelemetryRecord],
    ) -> Optional["FusedSignal"]:

        fresh = [
            r for r in records
            if r.freshness_hours <= self.staleness_hours and r.confidence > 0.0
        ]
        if not fresh:
            # Degrade gracefully: use least-stale record at reduced confidence
            fresh = sorted(records, key=lambda r: r.freshness_hours)[:1]
            if not fresh:
                return None

        reg    = SIGNAL_REGISTRY.get(variable, {})
        method = reg.get("fusion_method", "confidence_weighted_mean")

        if method == "max_value":
            best    = max(fresh, key=lambda r: r.value)
            value   = best.value
            conf    = best.confidence
            sources = [best.source]

        elif method == "max_confidence":
            best    = max(fresh, key=lambda r: r.confidence)
            value   = best.value
            conf    = best.confidence
            sources = [best.source]

        else:  # confidence_weighted_mean
            total_weight = sum(r.confidence for r in fresh)
            if total_weight == 0:
                value = fresh[0].value
                conf  = 0.0
            else:
                value = sum(r.value * r.confidence for r in fresh) / total_weight
                conf  = total_weight / len(fresh)
            sources = list({r.source for r in fresh})

        # Freshness decay — max 70% penalty so even stale data contributes
        avg_freshness    = sum(r.freshness_hours for r in fresh) / len(fresh)
        freshness_factor = max(0.30, 1.0 - avg_freshness / self.staleness_hours)
        conf             = min(1.0, conf * freshness_factor)

        normal_range  = reg.get("normal_range")
        anomaly_score = self._anomaly_score(value, normal_range) if normal_range else 0.0

        invert     = reg.get("invert", False)
        threshold  = reg.get("critical_threshold")
        if threshold is None:
            is_critical = False
        elif invert:
            is_critical = value <= threshold
        else:
            is_critical = value >= threshold

        return FusedSignal(
            variable      = variable,
            value         = value,
            confidence    = conf,
            sources       = sources,
            source_count  = len(fresh),
            anomaly_score = anomaly_score,
            category      = reg.get("category", "unknown"),
            is_critical   = is_critical,
        )

    @staticmethod
    def _anomaly_score(value: float, normal_range: tuple) -> float:
        low, high = normal_range
        if low <= value <= high:
            return 0.0
        width = max(high - low, 0.001)
        if value > high:
            return min(1.0, (value - high) / width)
        return min(1.0, (low - value) / width)


# ════════════════════════════════════════════════════════════════════════════
# FUSED SIGNAL
# ════════════════════════════════════════════════════════════════════════════

class FusedSignal:
    """Single fused variable with provenance and anomaly metadata."""

    __slots__ = (
        "variable", "value", "confidence", "sources",
        "source_count", "anomaly_score", "category", "is_critical",
    )

    def __init__(
        self,
        variable:      str,
        value:         float,
        confidence:    float,
        sources:       list[str],
        source_count:  int,
        anomaly_score: float,
        category:      str,
        is_critical:   bool,
    ):
        self.variable      = variable
        self.value         = value
        self.confidence    = confidence
        self.sources       = sources
        self.source_count  = source_count
        self.anomaly_score = anomaly_score
        self.category      = category
        self.is_critical   = is_critical

    def to_dict(self) -> dict:
        return {
            "variable":      self.variable,
            "value":         round(self.value, 5),
            "confidence":    round(self.confidence, 4),
            "sources":       self.sources,
            "source_count":  self.source_count,
            "anomaly_score": round(self.anomaly_score, 4),
            "category":      self.category,
            "is_critical":   self.is_critical,
        }


# ════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE SYNTHESIZER
# ════════════════════════════════════════════════════════════════════════════

class IntelligenceSynthesizer:

    def synthesize(
        self,
        fused:        dict[str, FusedSignal],
        asset_type:   str = "infrastructure",
        country_code: str = "IND",
    ) -> "IntelligencePacket":

        physical   = {k: v for k, v in fused.items() if v.category == "physical_hazard"}
        satellite  = {k: v for k, v in fused.items() if v.category == "satellite_intelligence"}
        transition = {k: v for k, v in fused.items() if v.category == "transition_risk"}

        phys_score = self._category_score(physical)
        sat_score  = self._category_score(satellite)
        tr_score   = self._category_score(transition)

        compounds    = self._detect_compound_events(fused)
        criticals    = [s for s in fused.values() if s.is_critical]
        correlations = self._detect_correlations(fused)

        avg_conf   = statistics.mean(s.confidence for s in fused.values()) if fused else 0.0
        source_set = set()
        for s in fused.values():
            source_set.update(s.sources)

        return IntelligencePacket(
            physical_score       = phys_score,
            satellite_score      = sat_score,
            transition_score     = tr_score,
            compound_events      = compounds,
            critical_signals     = [s.to_dict() for s in criticals],
            correlations         = correlations,
            overall_confidence   = avg_conf,
            active_sources       = list(source_set),
            signal_count         = len(fused),
            fused_signals        = {k: v.to_dict() for k, v in fused.items()},
        )

    def _category_score(self, signals: dict[str, "FusedSignal"]) -> float:
        """
        Confidence-weighted mean of normalised signal values.

        [FIX-BUG-2] Raw values like precip_anomaly_pct can be in [-30, 80].
        We normalise each to [0, 1] using its registry normal_range before
        applying the registry weight. Without this, the weighted sum can
        silently exceed 1.0 before the clamp, making the clamp lossy.
        """
        if not signals:
            return 0.0

        total_w   = 0.0
        score_sum = 0.0

        for k, sig in signals.items():
            reg    = SIGNAL_REGISTRY.get(k, {})
            w      = reg.get("weight", 0.05)
            lo, hi = reg.get("normal_range", (0.0, 1.0))

            span = hi - lo
            if span <= 0:
                norm_val = 0.0
            else:
                # Clamp to [0, 1]: 0 = bottom of normal range, 1 = top
                norm_val = min(1.0, max(0.0, (sig.value - lo) / span))

            score_sum += norm_val * w
            total_w   += w

        if total_w == 0:
            return 0.0

        return min(1.0, score_sum / total_w)

    def _detect_compound_events(self, fused: dict[str, "FusedSignal"]) -> list[dict]:
        """
        Detect co-occurring hazards that amplify each other.

        [FIX-BUG-1] Previously used FusedSignal("",0,0,[],0,0,"",False) as a default
        which silently breaks if FusedSignal's __init__ signature changes.
        Now uses explicit dict.get() with 0.0 default on the value.
        """
        def v(key: str) -> float:
            sig = fused.get(key)
            return sig.value if sig is not None else 0.0

        drought = v("drought_index")
        fire    = v("fire_prob_100km")
        heat    = v("heat_stress_prob_7d")
        flood   = v("flood_signal")
        veg     = v("vegetation_stress")
        wind    = v("extreme_wind_prob_7d")

        events = []

        if fire >= 0.30 and drought >= 0.35 and heat >= 0.30:
            events.append({
                "type":        "fire_climate_compound",
                "severity":    "CRITICAL",
                "description": "Co-occurring fire risk, drought, and heat stress. "
                               "Compound damage multiplier: 2.5–3.5×.",
                "signals":     {"fire": round(fire,3), "drought": round(drought,3), "heat": round(heat,3)},
                "amplifier":   round(1.0 + fire * 0.8 + drought * 0.7 + heat * 0.5, 3),
            })
        elif drought >= 0.50 and heat >= 0.40:
            events.append({
                "type":        "drought_heat_nexus",
                "severity":    "HIGH",
                "description": "Simultaneous drought and heat stress. "
                               "Critical for agriculture and water-dependent infrastructure.",
                "signals":     {"drought": round(drought,3), "heat": round(heat,3)},
                "amplifier":   round(1.0 + drought * 0.6 + heat * 0.5, 3),
            })

        if flood >= 0.35 and wind >= 0.35:
            events.append({
                "type":        "flood_wind_compound",
                "severity":    "HIGH",
                "description": "Co-occurring flood signal and extreme wind. "
                               "Storm surge / cyclone signature.",
                "signals":     {"flood": round(flood,3), "wind": round(wind,3)},
                "amplifier":   round(1.0 + flood * 0.7 + wind * 0.5, 3),
            })

        if veg >= 0.55 and drought >= 0.40:
            events.append({
                "type":        "vegetation_collapse",
                "severity":    "ELEVATED",
                "description": "Satellite-confirmed vegetation stress coincides with drought. "
                               "Land degradation / desertification signature.",
                "signals":     {"vegetation_stress": round(veg,3), "drought": round(drought,3)},
                "amplifier":   round(1.0 + veg * 0.5 + drought * 0.4, 3),
            })

        return events

    def _detect_correlations(self, fused: dict[str, "FusedSignal"]) -> list[dict]:
        """
        [FIX-BUG-3] O(1) pair lookup via pre-built dict, not O(N²) scan.
        """
        correlations = []
        for (a, b), description in _CORRELATION_PAIRS.items():
            if a in fused and b in fused:
                av = fused[a].value
                bv = fused[b].value
                if av >= 0.30 and bv >= 0.30:
                    correlations.append({
                        "signal_a":    a,
                        "signal_b":    b,
                        "values":      [round(av, 3), round(bv, 3)],
                        "description": description,
                        "strength":    round(min(1.0, av * bv * 3), 3),
                    })
        return correlations


# ════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE PACKET
# ════════════════════════════════════════════════════════════════════════════

class IntelligencePacket:

    __slots__ = (
        "physical_score", "satellite_score", "transition_score",
        "compound_events", "critical_signals", "correlations",
        "overall_confidence", "active_sources", "signal_count", "fused_signals",
    )

    def __init__(
        self,
        physical_score:     float,
        satellite_score:    float,
        transition_score:   float,
        compound_events:    list,
        critical_signals:   list,
        correlations:       list,
        overall_confidence: float,
        active_sources:     list,
        signal_count:       int,
        fused_signals:      dict,
    ):
        self.physical_score     = physical_score
        self.satellite_score    = satellite_score
        self.transition_score   = transition_score
        self.compound_events    = compound_events
        self.critical_signals   = critical_signals
        self.correlations       = correlations
        self.overall_confidence = overall_confidence
        self.active_sources     = active_sources
        self.signal_count       = signal_count
        self.fused_signals      = fused_signals

    @property
    def has_compound_event(self) -> bool:
        return len(self.compound_events) > 0

    @property
    def max_compound_amplifier(self) -> float:
        if not self.compound_events:
            return 1.0
        return max(e.get("amplifier", 1.0) for e in self.compound_events)

    def to_dict(self) -> dict:
        return {
            "scores": {
                "physical":   round(self.physical_score,   4),
                "satellite":  round(self.satellite_score,  4),
                "transition": round(self.transition_score, 4),
            },
            "compound_events":    self.compound_events,
            "critical_signals":   self.critical_signals,
            "correlations":       self.correlations,
            "compound_amplifier": round(self.max_compound_amplifier, 3),
            "overall_confidence": round(self.overall_confidence, 4),
            "active_sources":     self.active_sources,
            "signal_count":       self.signal_count,
            "fused_signals":      self.fused_signals,
        }
