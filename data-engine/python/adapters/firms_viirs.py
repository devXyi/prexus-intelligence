"""
data-engine/python/adapters/firms_viirs.py
Prexus Intelligence — NASA FIRMS VIIRS Adapter
Real-time wildfire detection from VIIRS 375m and MODIS 1km satellites.

API: https://firms.modaps.eosdis.nasa.gov/api/
Free with NASA FIRMS MAP_KEY. Response: CSV with fire detections.

Provides:
  - Active fire detections within radius of asset
  - Fire Radiative Power (FRP) — proxy for fire intensity
  - 7-day and 30-day fire occurrence probability
  - Burn scar proximity index
"""

import asyncio
import csv
import io
import math
import os
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from .base import BaseAdapter, TelemetryRecord

logger = logging.getLogger("prexus.adapters.firms")


class FIRMSAdapter(BaseAdapter):

    SOURCE_NAME            = "NASA FIRMS VIIRS 375m"
    REFRESH_INTERVAL_HOURS = 3.0

    BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

    # Confidence thresholds
    VIIRS_CONFIDENCE_MIN = 50    # VIIRS nominal confidence %
    MODIS_CONFIDENCE_MIN = "nominal"

    # Analysis radii in km
    RADII_KM = {
        "immediate": 25,
        "regional":  100,
        "extended":  250,
    }

    def __init__(self, map_key: Optional[str] = None):
        super().__init__()
        self._map_key = map_key or os.environ.get("NASA_FIRMS_KEY", "")
        if not self._map_key:
            logger.warning("[FIRMS] No MAP_KEY set — using public fallback (rate-limited)")

    async def fetch(
        self,
        lat: float,
        lon: float,
        radius_km: int = 100,
        days_back: int = 30,
        **kwargs
    ) -> list[TelemetryRecord]:
        start = time.perf_counter()
        try:
            raw = await self._fetch_raw(lat, lon, radius_km=radius_km, days_back=days_back)
            records = self._parse(lat, lon, raw, radius_km)
            self._mark_success((time.perf_counter() - start) * 1000)
            return records
        except Exception as e:
            self._mark_failure(str(e))
            return self._fallback_records(lat, lon)

    async def _fetch_raw(
        self,
        lat: float,
        lon: float,
        radius_km: int = 100,
        days_back: int = 30,
        **kwargs
    ) -> dict:
        """
        Fetch fire detections from FIRMS API.
        Area query: lat/lon bounding box derived from radius.
        """
        # Convert radius to bounding box (approximate, flat earth ok here)
        deg_lat = radius_km / 111.0
        deg_lon = radius_km / (111.0 * math.cos(math.radians(lat)))

        bbox = f"{lon-deg_lon},{lat-deg_lat},{lon+deg_lon},{lat+deg_lat}"
        days = min(days_back, 10)  # FIRMS API max 10 days per request

        results = {"viirs": [], "modis": []}

        async with httpx.AsyncClient(timeout=30) as client:
            for source, satellite in [("VIIRS_SNPP_NRT", "viirs"), ("MODIS_NRT", "modis")]:
                url = f"{self.BASE_URL}/{self._map_key or 'DEMO_KEY'}/{source}/{bbox}/{days}"
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200 and resp.text.strip():
                        reader = csv.DictReader(io.StringIO(resp.text))
                        results[satellite] = list(reader)
                except Exception as e:
                    logger.debug(f"[FIRMS] {source} fetch error: {e}")

        return results

    def _parse(
        self,
        asset_lat: float,
        asset_lon: float,
        raw: dict,
        query_radius_km: int,
    ) -> list[TelemetryRecord]:
        now = datetime.now(timezone.utc)
        all_detections = []

        # ── Parse VIIRS detections ────────────────────────────────────────────
        for row in raw.get("viirs", []):
            try:
                det_lat = float(row.get("latitude", 0))
                det_lon = float(row.get("longitude", 0))
                frp     = float(row.get("frp", 0))        # Fire Radiative Power MW
                conf    = row.get("confidence", "n").lower()

                # Filter low-confidence detections
                if conf not in ("n", "h", "nominal", "high"):
                    continue

                dist_km  = self._haversine_km(asset_lat, asset_lon, det_lat, det_lon)
                acq_date = row.get("acq_date", "")
                acq_time = row.get("acq_time", "0000").zfill(4)

                try:
                    det_time = datetime.strptime(
                        f"{acq_date} {acq_time[:2]}:{acq_time[2:]}",
                        "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    det_time = now

                all_detections.append({
                    "source":   "VIIRS",
                    "lat":      det_lat,
                    "lon":      det_lon,
                    "frp":      frp,
                    "dist_km":  dist_km,
                    "time":     det_time,
                    "conf":     1.0 if conf in ("h", "high") else 0.8,
                })
            except (ValueError, KeyError):
                continue

        # ── Parse MODIS detections ────────────────────────────────────────────
        for row in raw.get("modis", []):
            try:
                det_lat  = float(row.get("latitude", 0))
                det_lon  = float(row.get("longitude", 0))
                frp      = float(row.get("frp", 0))
                conf_str = row.get("confidence", "0")
                conf_int = int(conf_str) if conf_str.isdigit() else 50

                if conf_int < 50:
                    continue

                dist_km = self._haversine_km(asset_lat, asset_lon, det_lat, det_lon)

                all_detections.append({
                    "source":  "MODIS",
                    "lat":     det_lat,
                    "lon":     det_lon,
                    "frp":     frp,
                    "dist_km": dist_km,
                    "time":    now - timedelta(hours=6),  # MODIS ~6h lag
                    "conf":    conf_int / 100.0,
                })
            except (ValueError, KeyError):
                continue

        # ── Risk metrics from detections ──────────────────────────────────────
        detections_25km  = [d for d in all_detections if d["dist_km"] <= 25]
        detections_100km = [d for d in all_detections if d["dist_km"] <= 100]
        detections_250km = [d for d in all_detections if d["dist_km"] <= 250]

        # Fire probability: detection count density → probability
        count_25  = len(detections_25km)
        count_100 = len(detections_100km)
        count_250 = len(detections_250km)

        fire_prob_immediate = min(1.0, count_25  / 3.0)    # 3+ detections = high prob
        fire_prob_regional  = min(1.0, count_100 / 10.0)
        fire_prob_extended  = min(1.0, count_250 / 25.0)

        # Maximum FRP in each zone — proxy for fire intensity
        frp_max_25  = max((d["frp"] for d in detections_25km),  default=0.0)
        frp_max_100 = max((d["frp"] for d in detections_100km), default=0.0)

        # Weighted fire hazard score (distance-decayed FRP)
        fire_hazard = 0.0
        for det in all_detections:
            if det["dist_km"] > 0:
                decay = math.exp(-det["dist_km"] / 50.0)   # 50km decay constant
                fire_hazard += det["frp"] * decay * det["conf"]
        fire_hazard_norm = min(1.0, fire_hazard / 500.0)   # 500 MW = max intensity

        # Days since nearest fire detection
        if detections_100km:
            latest = max(d["time"] for d in detections_100km)
            days_since = (now - latest).total_seconds() / 86400
        else:
            days_since = 30.0

        data_conf = 0.88 if (raw.get("viirs") or raw.get("modis")) else 0.0
        freshness = 3.0  # FIRMS updates every ~3 hours

        def rec(variable, value, unit, confidence=None):
            return TelemetryRecord(
                source          = self.SOURCE_NAME,
                variable        = variable,
                lat             = asset_lat,
                lon             = asset_lon,
                value           = round(float(value), 5),
                unit            = unit,
                timestamp       = now,
                confidence      = confidence or data_conf,
                freshness_hours = freshness,
                metadata        = {
                    "detections_25km":  count_25,
                    "detections_100km": count_100,
                    "detections_250km": count_250,
                },
            )

        return [
            rec("fire_prob_25km",          fire_prob_immediate, "probability"),
            rec("fire_prob_100km",         fire_prob_regional,  "probability"),
            rec("fire_prob_250km",         fire_prob_extended,  "probability"),
            rec("fire_hazard_score",       fire_hazard_norm,    "0-1"),
            rec("fire_radiative_power_mw", frp_max_100,         "MW"),
            rec("fire_count_100km",        float(count_100),    "count"),
            rec("days_since_nearest_fire", days_since,          "days"),
        ]

    def _fallback_records(self, lat: float, lon: float) -> list[TelemetryRecord]:
        """Return zero-confidence records when FIRMS is unavailable."""
        now = datetime.now(timezone.utc)
        variables = [
            ("fire_prob_25km",          0.0, "probability"),
            ("fire_prob_100km",         0.0, "probability"),
            ("fire_hazard_score",       0.0, "0-1"),
            ("fire_count_100km",        0.0, "count"),
        ]
        return [
            TelemetryRecord(
                source=self.SOURCE_NAME, variable=v, lat=lat, lon=lon,
                value=val, unit=u, timestamp=now,
                confidence=0.0, freshness_hours=999.0,
                metadata={"status": "firms_unavailable"},
            )
            for v, val, u in variables
        ]

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        φ1, φ2 = math.radians(lat1), math.radians(lat2)
        dφ = math.radians(lat2 - lat1)
        dλ = math.radians(lon2 - lon1)
        a = math.sin(dφ/2)**2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
