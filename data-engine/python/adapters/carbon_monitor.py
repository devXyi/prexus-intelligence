"""
data-engine/python/adapters/carbon_monitor.py
Prexus Intelligence — Carbon Monitor Adapter
Near-real-time CO₂ emissions by country and sector.
Source: carbonmonitor.org — daily updates, ~5-day lag.
Free API, no key required.

Provides:
  - CO₂ emissions intensity by country
  - Sector breakdown (power, industry, ground transport, residential, aviation)
  - Year-over-year emissions trend
  - Transition risk proxy score
"""

import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from .base import BaseAdapter, TelemetryRecord

logger = logging.getLogger("prexus.adapters.carbon_monitor")


# Country-level carbon intensity benchmarks (tCO2 per MWh electricity)
# Used as fallback when API is unavailable
CARBON_INTENSITY_FALLBACK = {
    "IND": 0.71, "CHN": 0.62, "USA": 0.38, "GBR": 0.23,
    "DEU": 0.35, "FRA": 0.07, "JPN": 0.47, "AUS": 0.65,
    "BRA": 0.09, "ZAF": 0.91, "RUS": 0.37, "CAN": 0.15,
    "KOR": 0.46, "MEX": 0.44, "IDN": 0.73, "SAU": 0.68,
    "TUR": 0.47, "ARG": 0.30, "POL": 0.74, "NGA": 0.41,
}

# Sector transition risk weights (how exposed is each sector to carbon pricing)
SECTOR_TRANSITION_WEIGHTS = {
    "Power Industry":      0.92,
    "Industry":            0.78,
    "Ground Transport":    0.65,
    "Residential":         0.42,
    "Aviation":            0.70,
    "International Aviation": 0.75,
    "Shipping":            0.68,
}

# Country → ISO2 mapping for API
COUNTRY_ISO2 = {
    "IND": "IN", "CHN": "CN", "USA": "US", "GBR": "GB",
    "DEU": "DE", "FRA": "FR", "JPN": "JP", "AUS": "AU",
    "BRA": "BR", "ZAF": "ZA", "RUS": "RU", "CAN": "CA",
    "KOR": "KR", "MEX": "MX", "IDN": "ID", "SAU": "SA",
    "TUR": "TR", "ARG": "AR", "POL": "PL", "NGA": "NG",
    "PAK": "PK", "BGD": "BD", "VNM": "VN", "THA": "TH",
    "EGY": "EG", "IRN": "IR", "IRQ": "IQ", "ARE": "AE",
}


class CarbonMonitorAdapter(BaseAdapter):

    SOURCE_NAME            = "Carbon Monitor"
    REFRESH_INTERVAL_HOURS = 24.0

    BASE_URL = "https://carbonmonitor-gracedb.larc.nasa.gov/api/data"
    ALT_URL  = "https://api.carbonmonitor.org/v1"

    def __init__(self):
        super().__init__()
        self._country_cache: dict = {}   # ISO3 → last API response

    async def fetch(
        self,
        lat:          float,
        lon:          float,
        country_code: str = "IND",
        **kwargs
    ) -> list[TelemetryRecord]:
        start = time.perf_counter()
        try:
            raw = await self._fetch_raw(lat, lon, country_code=country_code)
            records = self._parse(lat, lon, raw, country_code)
            self._mark_success((time.perf_counter() - start) * 1000)
            return records
        except Exception as e:
            self._mark_failure(str(e))
            return self._fallback_records(lat, lon, country_code)

    async def _fetch_raw(
        self,
        lat:          float,
        lon:          float,
        country_code: str = "IND",
        **kwargs
    ) -> dict:
        if country_code in self._country_cache:
            cached = self._country_cache[country_code]
            age_h  = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
            if age_h < self.REFRESH_INTERVAL_HOURS:
                return cached["data"]

        iso2     = COUNTRY_ISO2.get(country_code, country_code[:2])
        end_date = datetime.now(timezone.utc).date() - timedelta(days=5)
        start_date = end_date - timedelta(days=365)

        async with httpx.AsyncClient(timeout=20) as client:
            # Try primary Carbon Monitor API
            try:
                url    = f"https://carbonmonitor.org/api/data"
                params = {
                    "country": iso2,
                    "startDate": start_date.isoformat(),
                    "endDate":   end_date.isoformat(),
                }
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    self._country_cache[country_code] = {
                        "data": data,
                        "fetched_at": datetime.now(timezone.utc),
                    }
                    return data
            except Exception:
                pass

            # Try alternative Carbon Monitor endpoint
            try:
                url  = f"https://api.carbonmonitor.org/v2/data/{iso2}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    self._country_cache[country_code] = {
                        "data": data,
                        "fetched_at": datetime.now(timezone.utc),
                    }
                    return data
            except Exception:
                pass

        # Both failed — return metadata-only response
        raise ConnectionError(f"Carbon Monitor API unavailable for {country_code}")

    def _parse(
        self,
        lat:          float,
        lon:          float,
        raw:          dict,
        country_code: str,
    ) -> list[TelemetryRecord]:
        now = datetime.now(timezone.utc)

        # Parse emissions data
        emissions_by_sector = {}
        total_recent        = 0.0
        total_prior_year    = 0.0
        data_points         = raw.get("data", raw.get("values", []))

        for point in data_points[-365:]:   # last year
            date_str = point.get("date", point.get("timestamp", ""))
            sectors  = point.get("sectors", point.get("sector_data", {}))
            if isinstance(sectors, dict):
                for sector, value in sectors.items():
                    try:
                        v = float(value)
                        emissions_by_sector[sector] = emissions_by_sector.get(sector, 0) + v
                        total_recent += v
                    except (ValueError, TypeError):
                        pass

        for point in data_points[-730:-365]:  # prior year
            sectors = point.get("sectors", point.get("sector_data", {}))
            if isinstance(sectors, dict):
                for _, value in sectors.items():
                    try:
                        total_prior_year += float(value)
                    except (ValueError, TypeError):
                        pass

        # Year-over-year trend
        yoy_change_pct = 0.0
        if total_prior_year > 0:
            yoy_change_pct = ((total_recent - total_prior_year) / total_prior_year) * 100

        # Carbon intensity score (0-1, where 1 = highest emitting)
        fallback_intensity = CARBON_INTENSITY_FALLBACK.get(country_code, 0.5)
        # Normalize: 0.91 (ZAF) = 1.0, 0.07 (FRA) = 0.0
        co2_intensity_norm = min(1.0, fallback_intensity / 0.91)

        # Transition risk: carbon intensity × sector concentration in high-risk sectors
        high_risk_share = 0.0
        total_emissions = max(sum(emissions_by_sector.values()), 1.0)
        for sector, amount in emissions_by_sector.items():
            weight = SECTOR_TRANSITION_WEIGHTS.get(sector, 0.5)
            high_risk_share += (amount / total_emissions) * weight

        transition_risk_score = min(1.0, co2_intensity_norm * 0.5 + high_risk_share * 0.5)

        # Carbon price trajectory risk (policy tightening signal)
        # Trend: if emissions rising → higher regulatory risk
        policy_risk = min(1.0, max(0.0, transition_risk_score + (yoy_change_pct / 100.0) * 0.15))

        confidence  = 0.85 if data_points else 0.40
        freshness   = 24.0  # Carbon Monitor has ~24h update cycle after 5d lag

        def rec(variable, value, unit, conf=None):
            return TelemetryRecord(
                source          = self.SOURCE_NAME,
                variable        = variable,
                lat             = lat,
                lon             = lon,
                value           = round(float(value), 6),
                unit            = unit,
                timestamp       = now,
                confidence      = conf or confidence,
                freshness_hours = freshness,
                metadata        = {"country": country_code, "iso2": COUNTRY_ISO2.get(country_code, "")},
            )

        records = [
            rec("co2_intensity_norm",      co2_intensity_norm,     "0-1"),
            rec("co2_intensity_tco2_mwh",  fallback_intensity,     "tCO2/MWh"),
            rec("transition_risk_score",   transition_risk_score,  "0-1"),
            rec("carbon_policy_risk",      policy_risk,            "0-1"),
            rec("emissions_yoy_change_pct",yoy_change_pct,         "%"),
            rec("high_risk_sector_share",  high_risk_share,        "0-1"),
        ]

        # Per-sector records
        for sector, amount in emissions_by_sector.items():
            safe_name = sector.lower().replace(" ", "_")
            records.append(rec(
                f"emissions_{safe_name}_mtco2",
                amount / 1000.0,   # kt → Mt
                "MtCO2",
            ))

        return records

    def _fallback_records(
        self,
        lat:          float,
        lon:          float,
        country_code: str,
    ) -> list[TelemetryRecord]:
        """Fallback using static carbon intensity benchmarks."""
        now       = datetime.now(timezone.utc)
        intensity = CARBON_INTENSITY_FALLBACK.get(country_code, 0.5)
        intensity_norm = min(1.0, intensity / 0.91)
        transition_risk = intensity_norm * 0.65  # conservative estimate

        return [
            TelemetryRecord(
                source=self.SOURCE_NAME, variable="co2_intensity_norm",
                lat=lat, lon=lon, value=intensity_norm, unit="0-1",
                timestamp=now, confidence=0.55, freshness_hours=168.0,  # 1-week stale
                metadata={"country": country_code, "source": "static_benchmark"},
            ),
            TelemetryRecord(
                source=self.SOURCE_NAME, variable="transition_risk_score",
                lat=lat, lon=lon, value=transition_risk, unit="0-1",
                timestamp=now, confidence=0.55, freshness_hours=168.0,
                metadata={"country": country_code, "source": "static_benchmark"},
            ),
            TelemetryRecord(
                source=self.SOURCE_NAME, variable="co2_intensity_tco2_mwh",
                lat=lat, lon=lon, value=intensity, unit="tCO2/MWh",
                timestamp=now, confidence=0.55, freshness_hours=168.0,
                metadata={"country": country_code, "source": "static_benchmark"},
            ),
        ]
