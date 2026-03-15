"""
data-engine/python/adapters/openmeteo.py
Prexus Intelligence — Open-Meteo Adapter
Wraps Open-Meteo ECMWF forecast + ERA5 historical reanalysis.
Free, no API key required. Updates every 1–6 hours.

Provides:
  - Current weather conditions (temperature, wind, humidity, precipitation)
  - 7-day forecast
  - ERA5 historical 10-year baseline for anomaly calculation
  - Extreme event probability (heat waves, heavy rain)
"""

import asyncio
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from .base import BaseAdapter, TelemetryRecord

logger = logging.getLogger("prexus.adapters.openmeteo")


class OpenMeteoAdapter(BaseAdapter):

    SOURCE_NAME            = "Open-Meteo / ECMWF"
    REFRESH_INTERVAL_HOURS = 1.0

    FORECAST_URL  = "https://api.open-meteo.com/v1/forecast"
    ERA5_URL      = "https://archive-api.open-meteo.com/v1/archive"

    # Variables to fetch from the current forecast
    HOURLY_VARS = [
        "temperature_2m",
        "precipitation",
        "wind_speed_10m",
        "relative_humidity_2m",
        "surface_pressure",
        "soil_moisture_0_1cm",
        "et0_fao_evapotranspiration",
    ]

    # Daily aggregate variables
    DAILY_VARS = [
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_sum",
        "wind_speed_10m_max",
        "wind_gusts_10m_max",
        "precipitation_hours",
        "et0_fao_evapotranspiration",
    ]

    def __init__(self, era5_baseline_years: int = 10):
        super().__init__()
        self._era5_baseline_years = era5_baseline_years
        self._baseline_cache: dict = {}  # keyed by (lat_r, lon_r)

    async def fetch(
        self,
        lat: float,
        lon: float,
        include_baseline: bool = True,
        **kwargs
    ) -> list[TelemetryRecord]:
        """
        Fetch current conditions and compute anomalies vs ERA5 baseline.
        Returns list of TelemetryRecord, one per variable.
        """
        start = time.perf_counter()
        try:
            raw = await self._fetch_raw(lat, lon, include_baseline=include_baseline)
            records = self._parse(lat, lon, raw)
            self._mark_success((time.perf_counter() - start) * 1000)
            return records
        except Exception as e:
            self._mark_failure(str(e))
            return []

    async def _fetch_raw(
        self,
        lat: float,
        lon: float,
        include_baseline: bool = True,
        **kwargs
    ) -> dict:
        async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
            # ── Current forecast ──────────────────────────────────────────────
            forecast_params = {
                "latitude":         lat,
                "longitude":        lon,
                "hourly":           ",".join(self.HOURLY_VARS),
                "daily":            ",".join(self.DAILY_VARS),
                "timezone":         "UTC",
                "forecast_days":    7,
                "wind_speed_unit":  "ms",
                "models":           "best_match",
            }
            resp = await client.get(self.FORECAST_URL, params=forecast_params)
            resp.raise_for_status()
            forecast = resp.json()

            result = {"forecast": forecast, "baseline": None}

            # ── ERA5 historical baseline ──────────────────────────────────────
            if include_baseline:
                cache_key = (round(lat, 1), round(lon, 1))
                if cache_key in self._baseline_cache:
                    result["baseline"] = self._baseline_cache[cache_key]
                else:
                    today     = datetime.now(timezone.utc).date()
                    start_dt  = today - timedelta(days=365 * self._era5_baseline_years)
                    end_dt    = today - timedelta(days=5)  # ERA5 has ~5d lag

                    era5_params = {
                        "latitude":       lat,
                        "longitude":      lon,
                        "start_date":     start_dt.isoformat(),
                        "end_date":       end_dt.isoformat(),
                        "daily":          ",".join([
                            "temperature_2m_max",
                            "temperature_2m_min",
                            "precipitation_sum",
                            "wind_speed_10m_max",
                        ]),
                        "timezone":       "UTC",
                        "wind_speed_unit": "ms",
                    }
                    era5_resp = await client.get(self.ERA5_URL, params=era5_params)
                    era5_resp.raise_for_status()
                    baseline = era5_resp.json()
                    self._baseline_cache[cache_key] = baseline
                    result["baseline"] = baseline

            return result

    def _parse(self, lat: float, lon: float, raw: dict) -> list[TelemetryRecord]:
        records = []
        now     = datetime.now(timezone.utc)
        fc      = raw.get("forecast", {})

        # ── Extract latest hourly values ──────────────────────────────────────
        hourly  = fc.get("hourly", {})
        times   = hourly.get("time", [])
        current_idx = 0  # most recent hour

        temp     = self._safe_latest(hourly, "temperature_2m",     current_idx)
        precip   = self._safe_latest(hourly, "precipitation",       current_idx)
        wind     = self._safe_latest(hourly, "wind_speed_10m",      current_idx)
        humidity = self._safe_latest(hourly, "relative_humidity_2m",current_idx)
        soil     = self._safe_latest(hourly, "soil_moisture_0_1cm", current_idx)

        # ── Daily aggregates (next 7 days) ────────────────────────────────────
        daily       = fc.get("daily", {})
        temp_max_7d = self._safe_list(daily, "temperature_2m_max")
        precip_7d   = self._safe_list(daily, "precipitation_sum")
        wind_max_7d = self._safe_list(daily, "wind_speed_10m_max")

        # ── Anomaly calculation vs ERA5 baseline ──────────────────────────────
        temp_anomaly  = 0.0
        precip_anomaly_pct = 0.0
        wind_anomaly  = 0.0
        baseline_conf = 0.0

        baseline = raw.get("baseline")
        if baseline:
            bl_daily  = baseline.get("daily", {})
            bl_temps  = self._safe_list(bl_daily, "temperature_2m_max")
            bl_precip = self._safe_list(bl_daily, "precipitation_sum")
            bl_wind   = self._safe_list(bl_daily, "wind_speed_10m_max")

            if bl_temps and temp is not None:
                bl_mean_temp   = sum(bl_temps) / len(bl_temps)
                temp_anomaly   = temp - bl_mean_temp

            if bl_precip:
                bl_mean_precip = sum(bl_precip) / len(bl_precip)
                recent_precip  = sum(precip_7d) / max(len(precip_7d), 1) if precip_7d else 0
                if bl_mean_precip > 0:
                    precip_anomaly_pct = ((recent_precip - bl_mean_precip) / bl_mean_precip) * 100

            if bl_wind and wind is not None:
                bl_mean_wind = sum(bl_wind) / len(bl_wind)
                wind_anomaly = wind - bl_mean_wind

            baseline_conf = 0.92

        # ── Derived risk indicators ────────────────────────────────────────────
        # Heat stress probability (days > 35°C in next 7 days)
        heat_days_7d = sum(1 for t in temp_max_7d if t is not None and t > 35.0)
        heat_prob    = min(heat_days_7d / 7.0, 1.0)

        # Drought index: soil moisture + precipitation anomaly
        drought_idx  = 0.0
        if soil is not None:
            drought_idx = max(0.0, (0.3 - soil) / 0.3)          # 0 at normal, 1 at extreme drought
        if precip_anomaly_pct < -30:
            drought_idx = min(1.0, drought_idx + abs(precip_anomaly_pct) / 200.0)

        # Extreme wind probability (next 7 days with gusts > 20 m/s)
        wind_gusts  = self._safe_list(daily, "wind_gusts_10m_max")
        extreme_wind = sum(1 for w in wind_gusts if w is not None and w > 20.0) / max(len(wind_gusts), 1)

        # ── Build records ─────────────────────────────────────────────────────
        def rec(variable, value, unit, confidence=0.92, meta=None):
            return TelemetryRecord(
                source          = self.SOURCE_NAME,
                variable        = variable,
                lat             = lat,
                lon             = lon,
                value           = round(value, 4) if value is not None else 0.0,
                unit            = unit,
                timestamp       = now,
                confidence      = confidence,
                freshness_hours = 1.0,
                metadata        = meta or {},
            )

        records = [
            rec("temperature_c",          temp or 0.0,         "°C"),
            rec("precipitation_mm",        precip or 0.0,       "mm/hr"),
            rec("wind_speed_ms",           wind or 0.0,         "m/s"),
            rec("humidity_pct",            humidity or 50.0,    "%"),
            rec("soil_moisture",           soil or 0.25,        "m³/m³"),
            rec("temp_anomaly_c",          temp_anomaly,        "°C",
                confidence=baseline_conf, meta={"baseline_years": self._era5_baseline_years}),
            rec("precip_anomaly_pct",      precip_anomaly_pct,  "%",
                confidence=baseline_conf),
            rec("wind_anomaly_ms",         wind_anomaly,        "m/s",
                confidence=baseline_conf),
            rec("heat_stress_prob_7d",     heat_prob,           "probability"),
            rec("drought_index",           drought_idx,         "0-1"),
            rec("extreme_wind_prob_7d",    extreme_wind,        "probability"),
            rec("precip_sum_7d_mm",        sum(p for p in precip_7d if p), "mm"),
            rec("temp_max_7d_c",           max((t for t in temp_max_7d if t), default=0.0), "°C"),
        ]

        return [r for r in records if r is not None]

    @staticmethod
    def _safe_latest(d: dict, key: str, idx: int) -> Optional[float]:
        vals = d.get(key, [])
        if vals and idx < len(vals):
            v = vals[idx]
            return float(v) if v is not None else None
        return None

    @staticmethod
    def _safe_list(d: dict, key: str) -> list:
        return [v for v in d.get(key, []) if v is not None]
