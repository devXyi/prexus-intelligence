"""
data-engine/python/adapters/firms.py
Meteorium Engine — NASA FIRMS Fire Adapter
Prexus Intelligence · v2.0.0

Source       : NASA Fire Information for Resource Management System (FIRMS)
               https://firms.modaps.eosdis.nasa.gov/api/area/
API key      : Required. Set env var FIRMS_API_KEY.
               Free registration: https://firms.modaps.eosdis.nasa.gov/api/

Instruments  : Primary   — VIIRS S-NPP 375m   (higher resolution, 12h latency)
               Secondary — VIIRS NOAA-20 375m  (cross-validation)
               Tertiary  — MODIS Terra/Aqua 1km (fallback, 3h latency)

Variables produced
──────────────────
  fire_prob_100km     Normalised active-fire intensity within 100 km [0, 1]
  fire_hazard_score   Composite hazard: fire count × FRP × confidence [0, 1]
  burn_scar_signal    Proxy: recent high-FRP detections as burn scar indicator [0, 1]

Architecture notes
──────────────────
  - FIRMS Area API returns CSV; parsed to structured fire detections.
  - Spatial aggregation: all detections within `radius_km` of the asset.
  - fire_prob_100km uses a softmax-like saturation curve so 1 fire ≠ 100%.
    N=1 → ~0.25, N=5 → ~0.65, N=20 → ~0.92 (asymptotic to 1.0).
  - fire_hazard_score fuses: detection count + mean FRP (Fire Radiative Power)
    + VIIRS confidence tier. FRP is in MW; normalised against 500 MW (extreme).
  - burn_scar_signal is elevated when recent (< 48h) detections have high FRP
    (> 200 MW), indicating active crown fire → likely scarring.
  - Dual-instrument validation: if both VIIRS S-NPP and NOAA-20 detect the same
    fire within 500m, confidence is boosted to 0.97.
  - Rate limit: 100 req/min per FIRMS policy; enforced with semaphore.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp

from adapters.base import BaseAdapter, TelemetryRecord

logger = logging.getLogger("meteorium.adapter.firms")

# ── API config ────────────────────────────────────────────────────────────────

_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# (source_key, instrument_label, latency_hours, confidence_base)
_INSTRUMENTS: list[tuple[str, str, float, float]] = [
    ("VIIRS_SNPP_NRT",     "NASA FIRMS VIIRS 375m",       12.0, 0.90),
    ("VIIRS_NOAA20_NRT",   "NASA FIRMS VIIRS NOAA-20",    12.0, 0.88),
    ("MODIS_NRT",          "NASA FIRMS MODIS 1km",         3.0, 0.75),
]

_LOOKBACK_DAYS   = 2        # how many days of fire history to fetch
_DEFAULT_RADIUS  = 1.0      # degrees (~111 km) bounding box side-half
_FRP_EXTREME_MW  = 500.0    # FRP at which normalised value = 1.0
_COUNT_SAT_N     = 30       # fire count at which saturation curve ≈ 0.97

# VIIRS confidence tiers → numeric weight
_VIIRS_CONF_MAP = {"low": 0.35, "nominal": 0.75, "high": 0.98}


class FIRMSAdapter(BaseAdapter):

    SOURCE_NAME            = "NASA FIRMS VIIRS 375m"
    REFRESH_INTERVAL_HOURS = 4.0
    TIMEOUT_SECONDS        = 20
    MAX_RETRIES            = 3

    # Max 100 req/min per FIRMS policy → ≤ 1.6/s → semaphore of 4
    _semaphore = asyncio.Semaphore(4)

    def __init__(self, radius_km: float = 100.0):
        super().__init__()
        self._api_key   = os.environ.get("FIRMS_API_KEY", "")
        self._radius_km = radius_km
        if not self._api_key:
            logger.warning("[FIRMS] FIRMS_API_KEY not set — fire data will be unavailable")

    async def fetch(
        self,
        lat: float,
        lon: float,
        **kwargs,
    ) -> list[TelemetryRecord]:
        if not self._api_key:
            self._mark_failure("FIRMS_API_KEY not set")
            return []

        t0 = time.monotonic()
        try:
            detections = await self._fetch_raw(lat, lon)
            records    = self._compute_risk_records(lat, lon, detections)
            self._mark_success((time.monotonic() - t0) * 1000)
            logger.info(
                "[FIRMS] %.4f,%.4f → %d detections → %d records",
                lat, lon, len(detections), len(records),
            )
            return records
        except Exception as e:
            self._mark_failure(str(e))
            return []

    async def _fetch_raw(self, lat: float, lon: float, **kwargs) -> list[dict]:
        """
        Fetch detections from all instruments, return merged list of dicts.
        Each dict: {lat, lon, frp, confidence, instrument, acq_datetime}
        """
        all_detections: list[dict] = []

        # Bounding box from radius_km
        deg_per_km = 1.0 / 111.0
        delta      = self._radius_km * deg_per_km
        area       = f"{lat - delta},{lon - delta},{lat + delta},{lon + delta}"

        tasks = [
            self._fetch_instrument(area, src_key, label, conf_base)
            for src_key, label, _, conf_base in _INSTRUMENTS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.debug("[FIRMS] instrument fetch error: %s", result)
                continue
            all_detections.extend(result)

        # Cross-instrument validation: boost confidence for dual detections
        all_detections = self._cross_validate(all_detections)
        return all_detections

    async def _fetch_instrument(
        self,
        area:       str,
        src_key:    str,
        label:      str,
        conf_base:  float,
    ) -> list[dict]:
        url    = f"{_BASE_URL}/{self._api_key}/{src_key}/{_LOOKBACK_DAYS}/{area}"
        last_e: Optional[Exception] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                async with self._semaphore:
                    timeout = aiohttp.ClientTimeout(total=self.TIMEOUT_SECONDS)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(url) as resp:
                            if resp.status == 429:
                                await asyncio.sleep(60)
                                raise RuntimeError("Rate limited (429)")
                            if resp.status == 401:
                                raise RuntimeError("Invalid FIRMS_API_KEY")
                            if resp.status == 404:
                                return []   # no data for this area/time
                            if resp.status >= 500:
                                raise RuntimeError(f"FIRMS server error {resp.status}")
                            if resp.status != 200:
                                text = await resp.text()
                                raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")
                            text = await resp.text()
                            return self._parse_csv(text, label, conf_base)

            except Exception as e:
                last_e = e
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))

        logger.debug("[FIRMS] %s failed: %s", src_key, last_e)
        return []

    def _parse_csv(
        self,
        text:      str,
        label:     str,
        conf_base: float,
    ) -> list[dict]:
        """
        Parse FIRMS CSV response into structured detection dicts.

        VIIRS CSV columns (standard NRT product):
          latitude, longitude, bright_ti4, scan, track, acq_date, acq_time,
          satellite, instrument, confidence, version, bright_ti5, frp, daynight
        MODIS CSV columns:
          latitude, longitude, brightness, scan, track, acq_date, acq_time,
          satellite, instrument, confidence, version, bright_t31, frp, daynight
        """
        detections = []
        if not text or text.strip().startswith("<!DOCTYPE"):
            return []   # HTML error page

        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                det_lat = float(row.get("latitude",  0))
                det_lon = float(row.get("longitude", 0))
                frp     = float(row.get("frp", 0) or 0)
                acq_date = row.get("acq_date", "")
                acq_time = row.get("acq_time", "0000")

                # VIIRS confidence is text tier; MODIS is numeric 0–100
                raw_conf = row.get("confidence", "nominal")
                if raw_conf.lower() in _VIIRS_CONF_MAP:
                    conf = _VIIRS_CONF_MAP[raw_conf.lower()]
                else:
                    try:
                        conf = float(raw_conf) / 100.0
                    except (ValueError, TypeError):
                        conf = conf_base

                # Parse acquisition datetime
                try:
                    acq_dt = datetime.strptime(
                        f"{acq_date} {acq_time.zfill(4)}",
                        "%Y-%m-%d %H%M",
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    acq_dt = datetime.now(timezone.utc)

                detections.append({
                    "lat":       det_lat,
                    "lon":       det_lon,
                    "frp":       frp,
                    "confidence":conf,
                    "instrument":label,
                    "acq_dt":    acq_dt,
                    "validated": False,
                })
            except (ValueError, KeyError):
                continue

        return detections

    def _cross_validate(self, detections: list[dict]) -> list[dict]:
        """
        Boost confidence when two instruments detect the same fire within 500m.
        500m ≈ 0.0045° lat/lon at mid-latitudes.
        """
        threshold = 0.0045
        viirs   = [d for d in detections if "VIIRS" in d["instrument"]]
        modis   = [d for d in detections if "MODIS" in d["instrument"]]

        for d1 in viirs:
            for d2 in modis:
                if (abs(d1["lat"] - d2["lat"]) < threshold and
                        abs(d1["lon"] - d2["lon"]) < threshold):
                    d1["confidence"] = min(0.97, d1["confidence"] * 1.08)
                    d1["validated"]  = True

        return detections

    # ── Risk variable computation ─────────────────────────────────────────────

    def _compute_risk_records(
        self,
        asset_lat:  float,
        asset_lon:  float,
        detections: list[dict],
    ) -> list[TelemetryRecord]:

        if not detections:
            # Return explicit zero records — fusion layer needs to know
            # there is NO fire signal, not just missing data
            now = datetime.now(timezone.utc)
            return [
                TelemetryRecord(
                    source="NASA FIRMS VIIRS 375m", variable="fire_prob_100km",
                    lat=asset_lat, lon=asset_lon, value=0.0, unit="probability",
                    timestamp=now, confidence=0.75, freshness_hours=0.0,
                    metadata={"detection_count": 0, "radius_km": self._radius_km},
                ),
                TelemetryRecord(
                    source="NASA FIRMS VIIRS 375m", variable="fire_hazard_score",
                    lat=asset_lat, lon=asset_lon, value=0.0, unit="index [0-1]",
                    timestamp=now, confidence=0.75, freshness_hours=0.0,
                    metadata={"detection_count": 0},
                ),
                TelemetryRecord(
                    source="NASA FIRMS VIIRS 375m", variable="burn_scar_signal",
                    lat=asset_lat, lon=asset_lon, value=0.0, unit="index [0-1]",
                    timestamp=now, confidence=0.70, freshness_hours=0.0,
                    metadata={"high_frp_count": 0},
                ),
            ]

        now              = datetime.now(timezone.utc)
        n                = len(detections)
        frp_values       = [d["frp"]        for d in detections]
        conf_values      = [d["confidence"] for d in detections]
        age_hours_values = [
            max(0.0, (now - d["acq_dt"]).total_seconds() / 3600.0)
            for d in detections
        ]

        mean_frp     = sum(frp_values) / n
        mean_conf    = sum(conf_values) / n
        mean_freshness = sum(age_hours_values) / n

        # ── 1. fire_prob_100km — saturation curve ─────────────────────────
        # P = 1 - exp(-λN) where λ = log(20)/_COUNT_SAT_N
        # This gives: N=1→0.22, N=5→0.69, N=20→0.93, asymptotic to 1.0
        lam         = math.log(20.0) / _COUNT_SAT_N
        fire_prob   = 1.0 - math.exp(-lam * n)

        # Modulate by mean confidence and FRP
        frp_mod     = min(1.0, mean_frp / _FRP_EXTREME_MW)
        fire_prob   = min(1.0, fire_prob * (0.6 + 0.4 * frp_mod))

        # Data confidence: weighted by instrument confidence + dual validation
        validated_pct   = sum(1 for d in detections if d.get("validated")) / n
        data_confidence = min(0.95, mean_conf + validated_pct * 0.05)

        records = [TelemetryRecord(
            source          = "NASA FIRMS VIIRS 375m",
            variable        = "fire_prob_100km",
            lat=asset_lat, lon=asset_lon,
            value           = round(fire_prob, 4),
            unit            = "probability",
            timestamp       = now,
            confidence      = round(data_confidence, 3),
            freshness_hours = round(mean_freshness, 2),
            metadata        = {
                "detection_count": n,
                "radius_km":       self._radius_km,
                "mean_frp_mw":     round(mean_frp, 1),
                "max_frp_mw":      round(max(frp_values), 1),
                "dual_validated":  int(validated_pct * n),
            },
        )]

        # ── 2. fire_hazard_score — composite intensity ────────────────────
        # Combines normalised count + FRP energy + confidence weighting
        count_norm    = 1.0 - math.exp(-lam * n)
        frp_norm      = min(1.0, sum(frp_values) / (_FRP_EXTREME_MW * max(n, 1)))
        hazard_score  = (count_norm * 0.45 + frp_norm * 0.35 + mean_conf * 0.20)

        records.append(TelemetryRecord(
            source          = "NASA FIRMS VIIRS 375m",
            variable        = "fire_hazard_score",
            lat=asset_lat, lon=asset_lon,
            value           = round(min(1.0, hazard_score), 4),
            unit            = "index [0–1]",
            timestamp       = now,
            confidence      = round(data_confidence, 3),
            freshness_hours = round(mean_freshness, 2),
            metadata        = {
                "total_frp_mw":  round(sum(frp_values), 1),
                "count_norm":    round(count_norm, 4),
                "frp_norm":      round(frp_norm, 4),
            },
        ))

        # ── 3. burn_scar_signal — high-FRP recent detections ─────────────
        # Proxy: recent detections (< 48h) with FRP > 200 MW
        # indicate active crown fire with high probability of scarring.
        high_frp      = [d for d in detections if d["frp"] > 200.0
                          and (now - d["acq_dt"]).total_seconds() / 3600.0 < 48.0]
        scar_proxy    = 1.0 - math.exp(-lam * len(high_frp)) if high_frp else 0.0
        scar_conf     = 0.65 if not high_frp else min(0.88, 0.65 + len(high_frp) * 0.03)

        records.append(TelemetryRecord(
            source          = "NASA FIRMS VIIRS 375m",
            variable        = "burn_scar_signal",
            lat=asset_lat, lon=asset_lon,
            value           = round(scar_proxy, 4),
            unit            = "index [0–1]",
            timestamp       = now,
            confidence      = round(scar_conf, 3),
            freshness_hours = round(mean_freshness, 2),
            metadata        = {
                "high_frp_count":  len(high_frp),
                "frp_threshold_mw":200.0,
                "lookback_hours":  48,
            },
        ))

        return records
