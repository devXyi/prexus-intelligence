"""
layer4/feature_store.py
Meteorium Engine — LAYER 4: Asset-Level Feature Store
Bridges raw geospatial tiles (Layer 3) to per-asset intelligence vectors.
For each registered asset: extract all environmental signals,
construct feature vector, compute confidence, cache for risk engine.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.config import STORE_DIR, H3_RESOLUTION_ASSET
from core.models import AssetFeatures, TelemetryRecord
from layer3.preprocessor import GeospatialPreprocessor

logger = logging.getLogger("meteorium.layer4")


class FeatureStore:
    """
    Layer 4: Per-asset intelligence vectors.

    Workflow:
      1. receive fresh TelemetryRecords from Layer 1 workers
      2. convert to H3-indexed tiles via Layer 3 preprocessor
      3. extract structured AssetFeatures vector
      4. cache in feature_cache table
      5. Layer 5 risk engine reads from here
    """

    FEATURE_DB = STORE_DIR / "features.db"

    def __init__(self, preprocessor: GeospatialPreprocessor):
        self.preprocessor = preprocessor
        self._init_cache()

    def _init_cache(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS asset_features (
                    asset_id      TEXT PRIMARY KEY,
                    h3_index      TEXT,
                    lat           REAL,
                    lon           REAL,
                    country_code  TEXT,
                    features_json TEXT NOT NULL,
                    sources_json  TEXT,
                    confidence    REAL,
                    computed_at   TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_af_computed
                ON asset_features(computed_at DESC);
            """)
            conn.commit()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.FEATURE_DB)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    # ── Main extraction ────────────────────────────────────────────────────────

    def extract(
        self,
        asset_id:     str,
        lat:          float,
        lon:          float,
        country_code: str,
        telemetry:    list[TelemetryRecord],
        scenario:     str = "baseline",
    ) -> AssetFeatures:
        """
        Extract a complete AssetFeatures vector from fresh TelemetryRecords.
        This is the bridge between raw telemetry and risk scoring.
        """
        now = datetime.now(timezone.utc)

        # Step 1: Push records into Layer 3 tiles
        self.preprocessor.process_telemetry(telemetry, lat, lon)

        # Step 2: Build flat feature dict from telemetry
        flat: dict[str, float] = {}
        sources: dict[str, str] = {}
        for rec in telemetry:
            flat[rec.variable]    = rec.value
            sources[rec.variable] = rec.source

        # Step 3: Also pull any cached tile features from Layer 3
        tile_feats = self.preprocessor.get_features_for_cell(lat, lon, scenario)
        for k, v in tile_feats.items():
            if k not in flat:   # telemetry is fresher than tiles
                flat[k] = v

        # Step 4: Construct AssetFeatures
        h3_idx = self.preprocessor.lat_lon_to_h3(lat, lon)

        features = AssetFeatures(
            asset_id     = asset_id,
            h3_index     = int(h3_idx.replace("grid_","").replace(".","").replace("-","")[:15]) if not h3_idx.startswith("0x") else int(h3_idx, 16) if False else 0,
            lat          = lat,
            lon          = lon,
            country_code = country_code,

            # Physical hazards
            temp_anomaly_c       = flat.get("temp_anomaly_c",        0.0),
            precip_anomaly_pct   = flat.get("precip_anomaly_pct",    0.0),
            heat_stress_prob     = flat.get("heat_stress_prob_7d",   0.0),
            drought_index        = flat.get("drought_index",         0.0),
            extreme_wind_prob    = flat.get("extreme_wind_prob_7d",  0.0),
            fire_prob_25km       = flat.get("fire_prob_25km",        0.0),
            fire_prob_100km      = flat.get("fire_prob_100km",       0.0),
            fire_hazard_score    = flat.get("fire_hazard_score",     0.0),
            flood_susceptibility = self._estimate_flood(flat),
            soil_moisture        = flat.get("soil_moisture",         0.25),
            wind_speed_ms        = flat.get("wind_speed_ms",         5.0),

            # Transition risk
            co2_intensity_norm    = flat.get("co2_intensity_norm",    0.5),
            transition_risk_score = flat.get("transition_risk_score", 0.4),
            carbon_policy_risk    = flat.get("carbon_policy_risk",    0.4),
            emissions_yoy_pct     = flat.get("emissions_yoy_change_pct", 0.0),

            # Scenario projections (from CMIP6 tiles if available)
            temp_delta_2050_c      = flat.get("temp_projection_2050", 0.0),
            extreme_heat_days_2050 = flat.get("extreme_heat_days_2050", 0.0),
            precip_change_2050_pct = flat.get("precip_projection_2050", 0.0),

            sources     = sources,
            computed_at = now,
            confidence  = self._calc_confidence(telemetry),
        )

        # Step 5: Cache it
        self._cache(features)
        return features

    def _estimate_flood(self, flat: dict) -> float:
        """Estimate flood susceptibility from available signals."""
        precip_anom = flat.get("precip_anomaly_pct", 0.0)
        soil        = flat.get("soil_moisture", 0.25)
        flood_from_precip = max(0.0, precip_anom / 100.0) * 0.7
        soil_sat          = max(0.0, (soil - 0.3) / 0.4)
        return min(1.0, flood_from_precip + soil_sat * 0.3)

    def _calc_confidence(self, telemetry: list[TelemetryRecord]) -> float:
        """Overall confidence from source freshness and coverage."""
        if not telemetry:
            return 0.1
        source_types = {rec.source for rec in telemetry}
        base_conf    = min(1.0, len(source_types) / 3.0)   # 3+ sources = full conf
        avg_rec_conf = sum(r.confidence for r in telemetry) / len(telemetry)
        freshness    = sum(1 for r in telemetry if r.freshness_hours < 24) / len(telemetry)
        return round(base_conf * 0.3 + avg_rec_conf * 0.4 + freshness * 0.3, 4)

    # ── Cache operations ──────────────────────────────────────────────────────

    def _cache(self, features: AssetFeatures):
        feat_dict = {
            "temp_anomaly_c":        features.temp_anomaly_c,
            "precip_anomaly_pct":    features.precip_anomaly_pct,
            "heat_stress_prob":      features.heat_stress_prob,
            "drought_index":         features.drought_index,
            "extreme_wind_prob":     features.extreme_wind_prob,
            "fire_prob_25km":        features.fire_prob_25km,
            "fire_prob_100km":       features.fire_prob_100km,
            "fire_hazard_score":     features.fire_hazard_score,
            "flood_susceptibility":  features.flood_susceptibility,
            "soil_moisture":         features.soil_moisture,
            "wind_speed_ms":         features.wind_speed_ms,
            "co2_intensity_norm":    features.co2_intensity_norm,
            "transition_risk_score": features.transition_risk_score,
            "carbon_policy_risk":    features.carbon_policy_risk,
            "emissions_yoy_pct":     features.emissions_yoy_pct,
            "temp_delta_2050_c":     features.temp_delta_2050_c,
        }
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO asset_features
                (asset_id, h3_index, lat, lon, country_code,
                 features_json, sources_json, confidence, computed_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                features.asset_id,
                str(features.h3_index),
                features.lat,
                features.lon,
                features.country_code,
                json.dumps(feat_dict),
                json.dumps(features.sources),
                features.confidence,
                features.computed_at.isoformat(),
            ))
            conn.commit()

    def get_cached(
        self,
        asset_id: str,
        max_age_hours: float = 6.0,
    ) -> Optional[AssetFeatures]:
        """Retrieve cached features if fresh enough."""
        since = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM asset_features
                WHERE asset_id = ? AND computed_at >= ?
            """, (asset_id, since)).fetchone()

        if not row:
            return None

        feat_dict = json.loads(row["features_json"])
        sources   = json.loads(row["sources_json"] or "{}")
        computed  = datetime.fromisoformat(row["computed_at"])

        f = AssetFeatures(
            asset_id             = row["asset_id"],
            h3_index             = 0,
            lat                  = row["lat"],
            lon                  = row["lon"],
            country_code         = row["country_code"],
            sources              = sources,
            computed_at          = computed,
            confidence           = row["confidence"],
            **{k: v for k, v in feat_dict.items() if hasattr(AssetFeatures, k)},
        )
        return f

    def get_feature_snapshot(self, features: AssetFeatures) -> dict:
        """Compact snapshot for API response."""
        return {
            "temp_anomaly_c":      round(features.temp_anomaly_c,       3),
            "fire_prob_100km":     round(features.fire_prob_100km,       3),
            "drought_index":       round(features.drought_index,         3),
            "heat_stress_prob":    round(features.heat_stress_prob,      3),
            "co2_intensity_norm":  round(features.co2_intensity_norm,    3),
            "carbon_policy_risk":  round(features.carbon_policy_risk,    3),
            "flood_susceptibility":round(features.flood_susceptibility,  3),
            "wind_speed_ms":       round(features.wind_speed_ms,         2),
        }

    def stats(self) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as n, MAX(computed_at) as latest FROM asset_features"
            ).fetchone()
        return {"cached_assets": row["n"], "latest_computed": row["latest"]}

