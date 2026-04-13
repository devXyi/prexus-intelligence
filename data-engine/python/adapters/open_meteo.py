"""
data-engine/python/adapters/open_meteo.py
Meteorium Engine — Open-Meteo / ECMWF Weather Adapter
Prexus Intelligence · v2.0.0

Source       : Open-Meteo API  https://api.open-meteo.com
Model        : ECMWF IFS 0.25° — authoritative global NWP
No API key required. Fair-use limit: ~10,000 req/day.

Variables produced
──────────────────
  temp_anomaly_c          Signed deviation from ERA5 30-yr mean (°C)
  precip_anomaly_pct      Precipitation anomaly vs baseline (%)
  heat_stress_prob_7d     P(Tmax > 35°C) in 7-day window [0, 1]
  drought_index           Aggregated soil-moisture / ET0 deficit [0, 1]
  extreme_wind_prob_7d    P(wind gust > 25 m/s) in 7-day window [0, 1]
  wind_speed_ms           Current mean 10 m wind speed (m/s)

Architecture notes
──────────────────
  - ERA5 30-year climatological baselines embedded as a 5°-bucket lookup
    table (1991–2020 Copernicus CDS). Avoids a second API call per request.
  - Drought index fuses: normalised soil moisture deficit + VPD elevation
    + cumulative ET0 surplus relative to precipitation.
  - All probabilities computed as empirical frequency over the 7-day
    hourly forecast window (168 hours), not parametric estimates.
  - _fetch_raw() uses aiohttp with per-request timeout + semaphore for
    client-side rate limiting.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp

from adapters.base import BaseAdapter, TelemetryRecord

logger = logging.getLogger("meteorium.adapter.open_meteo")

# ── API endpoints ─────────────────────────────────────────────────────────────

_BASE_URL = "https://api.open-meteo.com/v1/forecast"

_HOURLY_VARS = [
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
    "soil_moisture_0_to_10cm",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
]

_DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "et0_fao_evapotranspiration",
]

# ── ERA5 30-year climatological baselines (1991–2020) ─────────────────────────
# Key   : (lat_5deg_bucket, lon_5deg_bucket)
# Value : (mean_temp_c, std_temp_c, mean_precip_mm_day)
# Coverage is intentionally dense for Prexus primary markets.
_ERA5_BASELINES: dict[tuple[int, int], tuple[float, float, float]] = {
    # India subcontinent
    (30, 75): (22.1, 8.2, 1.8),  (25, 75): (25.4, 7.1, 2.1),
    (25, 80): (26.3, 6.1, 2.4),  (20, 75): (28.1, 4.8, 3.1),
    (20, 80): (27.6, 4.2, 3.4),  (15, 75): (27.9, 3.9, 3.8),
    (15, 80): (28.2, 3.2, 4.1),  (10, 75): (28.0, 2.8, 4.5),
    (10, 80): (28.4, 2.1, 4.2),  (25, 85): (26.8, 5.4, 3.2),
    # SE Asia
    (5,  100): (27.8, 1.5, 6.2), (10, 100): (27.4, 1.8, 5.8),
    (10, 105): (27.2, 2.1, 5.4), (15, 105): (26.8, 3.4, 4.1),
    (20, 105): (24.1, 4.9, 2.8), (0,   110): (27.0, 1.2, 7.1),
    # Sub-Saharan Africa
    (5,   20): (26.1, 3.2, 3.9), (0,   25): (25.4, 2.8, 4.8),
    (-5,  25): (23.6, 3.4, 3.8), (-5,  30): (22.8, 4.1, 3.6),
    (5,   35): (27.2, 4.8, 2.1), (10,  40): (28.4, 5.2, 1.8),
    # Middle East / North Africa
    (25,  45): (30.4, 9.4, 0.5), (25,  50): (30.2, 9.8, 0.4),
    (30,  40): (25.6, 10.2, 0.6),(30,  50): (28.1, 10.8, 0.3),
    # Europe
    (50,  10): (9.8,  6.2, 2.1), (45,  15): (12.4,  5.8, 2.8),
    (55,  10): (7.2,  5.4, 1.9), (40,  20): (15.8,  7.1, 2.4),
    # North America
    (40, -75): (11.8,  9.4, 3.1),(35,  -90): (16.8,  8.4, 3.2),
    (40, -100): (11.2, 9.8, 1.9),(45, -100): (5.8,  10.2, 1.6),
    # Brazil / South America
    (-15, -50): (24.8, 3.1, 4.9),(-5,  -45): (27.2, 2.8, 5.8),
    (-25, -50): (19.4, 5.6, 3.8),
    # Australia
    (-25, 130): (26.8, 7.2, 1.2),(-30, 150): (18.2, 6.4, 2.8),
    (-35, 145): (14.8, 6.2, 2.2),
    # Global fallback
    (0, 0): (20.0, 8.0, 2.5),
}

def _baseline(lat: float, lon: float) -> tuple[float, float, float]:
    """Nearest-bucket ERA5 baseline lookup."""
    lb = round(lat / 5) * 5
    lo = round(lon / 5) * 5
    for r in range(0, 35, 5):
        for dlat in range(-r, r + 5, 5):
            for dlon in range(-r, r + 5, 5):
                k = (lb + dlat, lo + dlon)
                if k in _ERA5_BASELINES:
                    return _ERA5_BASELINES[k]
    return _ERA5_BASELINES[(0, 0)]


class OpenMeteoAdapter(BaseAdapter):

    SOURCE_NAME            = "Open-Meteo / ECMWF"
    REFRESH_INTERVAL_HOURS = 3.0
    TIMEOUT_SECONDS        = 15
    MAX_RETRIES            = 3

    # Client-side rate limit: max 8 concurrent requests
    _semaphore = asyncio.Semaphore(8)

    async def fetch(
        self,
        lat: float,
        lon: float,
        **kwargs,
    ) -> list[TelemetryRecord]:
        t0 = time.monotonic()
        try:
            raw     = await self._fetch_raw(lat, lon)
            records = self._parse(lat, lon, raw)
            self._mark_success((time.monotonic() - t0) * 1000)
            logger.info("[OpenMeteo] %.4f,%.4f → %d records", lat, lon, len(records))
            return records
        except Exception as e:
            self._mark_failure(str(e))
            return []

    async def _fetch_raw(self, lat: float, lon: float, **kwargs) -> dict:
        params = {
            "latitude":       round(lat, 4),
            "longitude":      round(lon, 4),
            "hourly":         ",".join(_HOURLY_VARS),
            "daily":          ",".join(_DAILY_VARS),
            "forecast_days":  7,
            "models":         "ecmwf_ifs025",
            "timezone":       "UTC",
            "wind_speed_unit":"ms",
        }
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                async with self._semaphore:
                    timeout = aiohttp.ClientTimeout(total=self.TIMEOUT_SECONDS)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(_BASE_URL, params=params) as resp:
                            if resp.status == 429:
                                raise RuntimeError("Rate limited (429)")
                            if resp.status >= 500:
                                raise RuntimeError(f"Server error {resp.status}")
                            if resp.status != 200:
                                text = await resp.text()
                                raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")
                            payload = await resp.json()
                            if "error" in payload and payload["error"]:
                                raise RuntimeError(
                                    f"API error: {payload.get('reason', 'unknown')}"
                                )
                            return payload
            except Exception as e:
                last_exc = e
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))
        raise RuntimeError(
            f"OpenMeteo failed after {self.MAX_RETRIES} attempts: {last_exc}"
        )

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse(self, lat: float, lon: float, data: dict) -> list[TelemetryRecord]:
        records: list[TelemetryRecord] = []
        now     = datetime.now(timezone.utc)
        daily   = data.get("daily",  {})
        hourly  = data.get("hourly", {})

        t_max   = self._safe_list(daily.get("temperature_2m_max"))
        t_min   = self._safe_list(daily.get("temperature_2m_min"))
        precip  = self._safe_list(daily.get("precipitation_sum"))
        w_max   = self._safe_list(daily.get("wind_speed_10m_max"))
        gust    = self._safe_list(daily.get("wind_gusts_10m_max"))
        et0_d   = self._safe_list(daily.get("et0_fao_evapotranspiration"))

        h_temp  = self._safe_list(hourly.get("temperature_2m"))
        h_wind  = self._safe_list(hourly.get("wind_speed_10m"))
        h_gust  = self._safe_list(hourly.get("wind_gusts_10m"))
        h_soil  = self._safe_list(hourly.get("soil_moisture_0_to_10cm"))
        h_vpd   = self._safe_list(hourly.get("vapour_pressure_deficit"))
        h_et0   = self._safe_list(hourly.get("et0_fao_evapotranspiration"))
        h_prcp  = self._safe_list(hourly.get("precipitation"))

        mean_t, std_t, mean_p = _baseline(lat, lon)

        # ── 1. Temperature anomaly ────────────────────────────────────────
        if t_max and t_min:
            today_mean = (t_max[0] + t_min[0]) / 2.0
            anomaly    = today_mean - mean_t
            records.append(TelemetryRecord(
                source          = self.SOURCE_NAME,
                variable        = "temp_anomaly_c",
                lat=lat, lon=lon,
                value           = round(anomaly, 3),
                unit            = "°C",
                timestamp       = now,
                confidence      = 0.88,
                freshness_hours = 0.0,
                metadata        = {
                    "today_mean_c":  round(today_mean, 2),
                    "baseline_c":    round(mean_t, 2),
                    "model":         "ecmwf_ifs025",
                },
            ))

        # ── 2. Precipitation anomaly ──────────────────────────────────────
        if precip and mean_p > 0:
            today_p   = precip[0]
            anom_pct  = ((today_p - mean_p) / mean_p) * 100.0
            # 7-day cumulative for better signal
            week_p    = sum(v for v in precip if v is not None)
            week_base = mean_p * 7
            week_anom = ((week_p - week_base) / week_base) * 100.0 if week_base > 0 else 0.0
            records.append(TelemetryRecord(
                source          = self.SOURCE_NAME,
                variable        = "precip_anomaly_pct",
                lat=lat, lon=lon,
                value           = round(week_anom, 2),
                unit            = "%",
                timestamp       = now,
                confidence      = 0.82,
                freshness_hours = 0.0,
                metadata        = {
                    "today_mm":    round(today_p, 2),
                    "week_mm":     round(week_p, 2),
                    "baseline_mm": round(week_base, 2),
                },
            ))

        # ── 3. Heat stress probability (7-day, hourly window) ─────────────
        if h_temp:
            hot_hours   = sum(1 for t in h_temp if t is not None and t > 35.0)
            heat_prob   = hot_hours / max(len(h_temp), 1)
            # Boost confidence when multiple hours exceed threshold
            conf        = 0.85 if hot_hours > 12 else 0.78
            records.append(TelemetryRecord(
                source          = self.SOURCE_NAME,
                variable        = "heat_stress_prob_7d",
                lat=lat, lon=lon,
                value           = round(heat_prob, 4),
                unit            = "probability",
                timestamp       = now,
                confidence      = conf,
                freshness_hours = 0.0,
                metadata        = {
                    "hot_hours_7d":  hot_hours,
                    "total_hours":   len(h_temp),
                    "threshold_c":   35.0,
                },
            ))

        # ── 4. Drought index ──────────────────────────────────────────────
        # Fuses: soil moisture deficit + VPD elevation + ET0 > precip
        drought_components: list[float] = []

        if h_soil:
            valid_soil = [s for s in h_soil if s is not None]
            if valid_soil:
                mean_soil    = sum(valid_soil) / len(valid_soil)
                # Field capacity ~0.35 m³/m³; below 0.15 = stress
                soil_deficit = max(0.0, (0.35 - mean_soil) / 0.35)
                drought_components.append(min(1.0, soil_deficit * 1.5))

        if h_vpd:
            valid_vpd = [v for v in h_vpd if v is not None]
            if valid_vpd:
                mean_vpd = sum(valid_vpd) / len(valid_vpd)
                # VPD > 3.0 kPa = severe crop stress
                vpd_score = min(1.0, mean_vpd / 3.0)
                drought_components.append(vpd_score)

        if h_et0 and h_prcp:
            et0_sum   = sum(v for v in h_et0  if v is not None)
            prcp_sum  = sum(v for v in h_prcp if v is not None)
            et0_daily = et0_sum  / 24.0
            pr_daily  = prcp_sum / 24.0
            if et0_daily > 0:
                deficit_ratio = max(0.0, (et0_daily - pr_daily) / et0_daily)
                drought_components.append(min(1.0, deficit_ratio))

        if drought_components:
            drought_idx = sum(drought_components) / len(drought_components)
            records.append(TelemetryRecord(
                source          = self.SOURCE_NAME,
                variable        = "drought_index",
                lat=lat, lon=lon,
                value           = round(drought_idx, 4),
                unit            = "index [0–1]",
                timestamp       = now,
                confidence      = 0.80,
                freshness_hours = 0.0,
                metadata        = {
                    "components":    len(drought_components),
                    "soil_moisture": round(drought_components[0], 3) if drought_components else None,
                    "model":         "ecmwf_ifs025",
                },
            ))

        # ── 5. Extreme wind probability (7-day hourly) ────────────────────
        if h_gust:
            gust_events = sum(1 for g in h_gust if g is not None and g > 25.0)
            wind_prob   = gust_events / max(len(h_gust), 1)
            records.append(TelemetryRecord(
                source          = self.SOURCE_NAME,
                variable        = "extreme_wind_prob_7d",
                lat=lat, lon=lon,
                value           = round(wind_prob, 4),
                unit            = "probability",
                timestamp       = now,
                confidence      = 0.82,
                freshness_hours = 0.0,
                metadata        = {
                    "gust_events_7d": gust_events,
                    "threshold_ms":   25.0,
                },
            ))

        # ── 6. Current wind speed (today mean) ────────────────────────────
        if h_wind:
            today_wind = [v for v in h_wind[:24] if v is not None]
            if today_wind:
                mean_wind = sum(today_wind) / len(today_wind)
                records.append(TelemetryRecord(
                    source          = self.SOURCE_NAME,
                    variable        = "wind_speed_ms",
                    lat=lat, lon=lon,
                    value           = round(mean_wind, 2),
                    unit            = "m/s",
                    timestamp       = now,
                    confidence      = 0.85,
                    freshness_hours = 0.0,
                    metadata        = {"hours_averaged": len(today_wind)},
                ))

        return records

    @staticmethod
    def _safe_list(val) -> list:
        if val is None:
            return []
        return [v for v in val]
