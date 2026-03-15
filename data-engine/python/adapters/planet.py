"""
adapters/planet.py
Meteorium Engine — Commercial Satellite Adapters
Planet Labs · Maxar Intelligence · Sentinel Hub · STAC catalog

These are the commercial orbital sensor networks.
Each adapter follows the same pattern as our free-tier adapters
but unlocks higher resolution, faster revisit, and tasking capability.

API pattern across all three:
  1. Authenticate (API key in header)
  2. Spatial query (geometry + time range)
  3. Download imagery metadata
  4. Request thumbnail or processed analytics
  5. Parse into TelemetryRecords

Cost reality:
  Planet Labs:   ~$5,000/month for commercial tier
  Maxar:         ~$15,000/month enterprise
  Sentinel Hub:  Free tier (2,500 req/mo) → $100–500/month commercial
  → Start with Sentinel Hub free tier, move to Planet when funded
"""

import asyncio
import base64
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from adapters.base import BaseAdapter, TelemetryRecord

logger = logging.getLogger("meteorium.adapters.satellite")


# ════════════════════════════════════════════════════════════════════════════
# SENTINEL HUB ADAPTER
# Free tier: 2,500 requests/month. No credit card for signup.
# Register: https://www.sentinel-hub.com/create_account
# Docs:     https://docs.sentinel-hub.com/api/latest/
#
# What it provides:
#   - Sentinel-2 multispectral (10m, 5-day revisit)
#   - Sentinel-1 SAR (10m, floods through clouds)
#   - MODIS, Landsat, DEM via same API
#   - Statistical API: pre-computed NDVI/NDWI without downloading images
# ════════════════════════════════════════════════════════════════════════════

class SentinelHubAdapter(BaseAdapter):

    SOURCE_NAME            = "Sentinel Hub / ESA Copernicus"
    REFRESH_INTERVAL_HOURS = 5.0     # S2 5-day revisit

    AUTH_URL      = "https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token"
    STATS_URL     = "https://services.sentinel-hub.com/api/v1/statistics"
    PROCESS_URL   = "https://services.sentinel-hub.com/api/v1/process"

    # Evalscript: computes NDVI, NDWI, NBR, NDBI from S2 bands
    # This runs server-side — we get back numbers, not raw imagery
    EVALSCRIPT_INDICES = """
    //VERSION=3
    function setup() {
        return {
            input: [{ bands: ["B03","B04","B08","B11","B12","SCL"], units:"REFLECTANCE" }],
            output: [{ id:"indices", bands:5, sampleType:"FLOAT32" }]
        };
    }
    function evaluatePixel(s) {
        let ndvi  = (s.B08 - s.B04) / (s.B08 + s.B04 + 0.0001);
        let ndwi  = (s.B03 - s.B08) / (s.B03 + s.B08 + 0.0001);
        let nbr   = (s.B08 - s.B12) / (s.B08 + s.B12 + 0.0001);
        let ndbi  = (s.B11 - s.B08) / (s.B11 + s.B08 + 0.0001);
        let cloud = (s.SCL === 8 || s.SCL === 9 || s.SCL === 10) ? 1.0 : 0.0;
        return { indices: [ndvi, ndwi, nbr, ndbi, cloud] };
    }
    """

    def __init__(
        self,
        client_id:     Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        super().__init__()
        self._client_id     = client_id     or os.environ.get("SENTINEL_HUB_CLIENT_ID",     "")
        self._client_secret = client_secret or os.environ.get("SENTINEL_HUB_CLIENT_SECRET", "")
        self._access_token: Optional[str]      = None
        self._token_expires: Optional[float]   = None

    @property
    def available(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def _ensure_token(self) -> Optional[str]:
        """OAuth2 client credentials flow for Sentinel Hub."""
        if self._access_token and self._token_expires and time.time() < self._token_expires - 60:
            return self._access_token

        if not self.available:
            return None

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                self.AUTH_URL,
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            resp.raise_for_status()
            data               = resp.json()
            self._access_token = data["access_token"]
            self._token_expires = time.time() + data.get("expires_in", 3600)
            return self._access_token

    async def fetch(
        self,
        lat: float,
        lon: float,
        **kwargs,
    ) -> list[TelemetryRecord]:
        if not self.available:
            logger.debug("[SentinelHub] No credentials — skipping")
            return []

        start = time.perf_counter()
        try:
            raw     = await self._fetch_raw(lat, lon)
            records = self._parse(lat, lon, raw)
            self._mark_success((time.perf_counter() - start) * 1000)
            return records
        except Exception as e:
            self._mark_failure(str(e))
            return []

    async def _fetch_raw(self, lat: float, lon: float, **kwargs) -> dict:
        token = await self._ensure_token()
        if not token:
            raise RuntimeError("No Sentinel Hub token")

        # 0.05° bounding box around the asset (~5.5km)
        delta = 0.025
        bbox  = [lon - delta, lat - delta, lon + delta, lat + delta]

        # Use the Statistical API — returns band statistics, not raw pixels
        # Much cheaper quota-wise than the Process API
        now        = datetime.now(timezone.utc)
        date_to    = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        date_from  = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        payload = {
            "input": {
                "bounds": {
                    "bbox":             bbox,
                    "properties":       {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [{
                    "type":            "sentinel-2-l2a",
                    "dataFilter":      {"maxCloudCoverage": 30},
                    "timeRange":       {"from": date_from, "to": date_to},
                }],
            },
            "aggregation": {
                "timeRange":   {"from": date_from, "to": date_to},
                "aggregationInterval": {"of": "P30D"},
                "evalscript":  self.EVALSCRIPT_INDICES,
                "resx":        0.0001,
                "resy":        0.0001,
            },
            "calculations": {
                "indices": {
                    "statistics": {
                        "default": {"percentiles": {"k": [10, 25, 50, 75, 90]}}
                    }
                }
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.STATS_URL,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def _parse(self, lat: float, lon: float, raw: dict) -> list[TelemetryRecord]:
        now    = datetime.now(timezone.utc)
        data   = raw.get("data", [{}])
        latest = data[-1] if data else {}
        stats  = latest.get("outputs", {}).get("indices", {}).get("bands", {})

        def band_mean(band_key: str) -> float:
            band = stats.get(band_key, {}).get("stats", {})
            return float(band.get("mean", 0.0))

        ndvi = band_mean("B0")   # band index 0 = NDVI
        ndwi = band_mean("B1")   # band index 1 = NDWI
        nbr  = band_mean("B2")   # band index 2 = NBR
        ndbi = band_mean("B3")   # band index 3 = NDBI
        cloud_frac = band_mean("B4")

        # Derived risk signals
        # NDVI < 0.2 = bare soil / severe stress
        veg_stress   = max(0.0, min(1.0, (0.5 - ndvi) / 0.5)) if ndvi < 0.5 else 0.0
        # NDWI > 0.3 = water / flood inundation
        flood_signal = max(0.0, min(1.0, (ndwi - 0.1) / 0.4)) if ndwi > 0.1 else 0.0
        # NBR < -0.1 = burn scar
        burn_signal  = max(0.0, min(1.0, (-nbr - 0.1) / 0.5)) if nbr < -0.1 else 0.0
        # NDBI > 0.1 = built-up / urban heat
        urban_heat   = max(0.0, min(1.0, (ndbi - 0.1) / 0.4)) if ndbi > 0.1 else 0.0

        conf = max(0.0, 1.0 - cloud_frac) * 0.90
        if not data:
            conf = 0.0

        def rec(var, val, unit):
            return TelemetryRecord(
                source=self.SOURCE_NAME, variable=var,
                lat=lat, lon=lon, value=round(float(val), 5),
                unit=unit, timestamp=now,
                confidence=conf, freshness_hours=120.0,  # 5-day revisit
            )

        return [
            rec("ndvi",               ndvi,        "index -1 to 1"),
            rec("ndwi",               ndwi,        "index -1 to 1"),
            rec("nbr",                nbr,         "index -1 to 1"),
            rec("ndbi",               ndbi,        "index -1 to 1"),
            rec("vegetation_stress",  veg_stress,  "0-1"),
            rec("flood_signal",       flood_signal,"0-1"),
            rec("burn_scar_signal",   burn_signal, "0-1"),
            rec("urban_heat_signal",  urban_heat,  "0-1"),
            rec("cloud_fraction",     cloud_frac,  "0-1"),
        ]


# ════════════════════════════════════════════════════════════════════════════
# PLANET LABS ADAPTER
# Commercial: ~$5,000/month for PlanetScope (3m daily global)
# Free research access via Education/Research program
# Register: https://developers.planet.com
# Docs:     https://developers.planet.com/docs/apis/data/
#
# What it provides:
#   - PlanetScope: 3m resolution, daily global revisit
#   - SkySat: 0.5m resolution, near-real-time tasking
#   - NICFI: free monthly composites of tropical forests
#   - Analytics Feed: pre-computed vessel/aircraft/building detection
# ════════════════════════════════════════════════════════════════════════════

class PlanetLabsAdapter(BaseAdapter):

    SOURCE_NAME            = "Planet Labs PlanetScope"
    REFRESH_INTERVAL_HOURS = 24.0   # daily

    SEARCH_URL    = "https://api.planet.com/data/v1/quick-search"
    ANALYTICS_URL = "https://api.planet.com/v0/analytics/collections"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__()
        self._api_key = api_key or os.environ.get("PLANET_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @property
    def _auth(self) -> tuple:
        return (self._api_key, "")   # Planet uses Basic auth: key as username, empty password

    async def fetch(self, lat: float, lon: float, **kwargs) -> list[TelemetryRecord]:
        if not self.available:
            return []

        start = time.perf_counter()
        try:
            raw     = await self._fetch_raw(lat, lon)
            records = self._parse(lat, lon, raw)
            self._mark_success((time.perf_counter() - start) * 1000)
            return records
        except Exception as e:
            self._mark_failure(str(e))
            return []

    async def _fetch_raw(self, lat: float, lon: float, **kwargs) -> dict:
        """
        Quick-search for recent imagery at this location.
        Returns scene metadata — we extract cloud cover, acquisition time,
        and any analytics that don't require downloading full imagery.
        """
        delta   = 0.05   # ~5.5km bounding box
        now     = datetime.now(timezone.utc)
        date_from = (now - timedelta(days=30)).isoformat().replace("+00:00", "Z")

        payload = {
            "item_types": ["PSScene"],
            "filter": {
                "type": "AndFilter",
                "config": [
                    {
                        "type": "GeometryFilter",
                        "field_name": "geometry",
                        "config": {
                            "type": "Polygon",
                            "coordinates": [[
                                [lon - delta, lat - delta],
                                [lon + delta, lat - delta],
                                [lon + delta, lat + delta],
                                [lon - delta, lat + delta],
                                [lon - delta, lat - delta],
                            ]],
                        },
                    },
                    {
                        "type": "DateRangeFilter",
                        "field_name": "acquired",
                        "config": {"gte": date_from},
                    },
                    {
                        "type":       "RangeFilter",
                        "field_name": "cloud_cover",
                        "config":     {"lte": 0.3},
                    },
                ],
            },
        }

        async with httpx.AsyncClient(timeout=30, auth=self._auth) as client:
            resp = await client.post(self.SEARCH_URL, json=payload)
            resp.raise_for_status()
            return resp.json()

    def _parse(self, lat: float, lon: float, raw: dict) -> list[TelemetryRecord]:
        now      = datetime.now(timezone.utc)
        features = raw.get("features", [])

        if not features:
            return []

        # Sort by acquisition date — most recent first
        features.sort(
            key=lambda f: f.get("properties", {}).get("acquired", ""),
            reverse=True
        )
        latest = features[0]
        props  = latest.get("properties", {})

        cloud_cover   = float(props.get("cloud_cover",  0.5))
        sun_elevation = float(props.get("sun_elevation", 45.0))
        gsd           = float(props.get("gsd",           3.0))   # ground sample distance meters
        item_count    = len(features)

        # Scene count over 30 days = data richness signal
        # Higher revisit rate = better temporal coverage
        coverage_score = min(1.0, item_count / 30.0)   # 30 scenes/month = max coverage

        # Parse acquisition time
        acq_str = props.get("acquired", "")
        try:
            acq_time = datetime.fromisoformat(acq_str.replace("Z", "+00:00"))
            age_hours = (now - acq_time).total_seconds() / 3600
        except Exception:
            age_hours = 24.0

        conf = (1.0 - cloud_cover) * 0.85

        def rec(var, val, unit):
            return TelemetryRecord(
                source=self.SOURCE_NAME, variable=var,
                lat=lat, lon=lon, value=round(float(val), 5),
                unit=unit, timestamp=now,
                confidence=conf, freshness_hours=age_hours,
            )

        return [
            rec("planet_scene_count_30d",   float(item_count),   "count"),
            rec("planet_cloud_cover",        cloud_cover,         "0-1"),
            rec("planet_coverage_score",     coverage_score,      "0-1"),
            rec("planet_latest_age_hours",   age_hours,           "hours"),
            rec("planet_gsd_m",              gsd,                 "meters"),
        ]

    async def search_analytics(
        self,
        lat: float,
        lon: float,
        feed: str = "vessel-detection",
    ) -> list[TelemetryRecord]:
        """
        Planet Analytics Feed — pre-computed AI detections.
        Feeds: vessel-detection, aircraft-detection, building-detection.
        Requires Analytics subscription (~$2,000/month extra).
        """
        if not self.available:
            return []

        now   = datetime.now(timezone.utc)
        delta = 0.05

        try:
            async with httpx.AsyncClient(timeout=30, auth=self._auth) as client:
                resp = await client.get(
                    f"{self.ANALYTICS_URL}/{feed}/items",
                    params={
                        "bbox":    f"{lon-delta},{lat-delta},{lon+delta},{lat+delta}",
                        "limit":   100,
                    }
                )
                if resp.status_code != 200:
                    return []

                data     = resp.json()
                features = data.get("features", [])
                count    = len(features)

                return [TelemetryRecord(
                    source   = f"Planet Analytics ({feed})",
                    variable = f"planet_{feed.replace('-','_')}_count",
                    lat=lat, lon=lon,
                    value    = float(count),
                    unit     = "detections",
                    timestamp = now,
                    confidence = 0.85,
                    freshness_hours = 24.0,
                )]
        except Exception as e:
            logger.debug(f"[Planet Analytics] {feed}: {e}")
            return []


# ════════════════════════════════════════════════════════════════════════════
# MAXAR INTELLIGENCE ADAPTER
# Enterprise: ~$15,000/month. 30cm resolution (best commercial available)
# Free trial available for qualified organizations
# Register: https://developer.maxar.com
# Docs:     https://developers.maxar.com/docs/
#
# What it provides:
#   - WorldView-3: 0.3m panchromatic, 1.24m multispectral
#   - WorldView-Legion: rapid revisit (up to 15x/day over major cities)
#   - SecureWatch: cloud-based imagery subscription
#   - Vivid Basemaps: pre-processed mosaic tiles
# ════════════════════════════════════════════════════════════════════════════

class MaxarAdapter(BaseAdapter):

    SOURCE_NAME            = "Maxar Intelligence WorldView"
    REFRESH_INTERVAL_HOURS = 24.0

    STAC_URL    = "https://api.maxar.com/discovery/v1/stac/search"
    BASEMAP_URL = "https://api.maxar.com/basemaps/v1/mosaics"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__()
        self._api_key = api_key or os.environ.get("MAXAR_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def fetch(self, lat: float, lon: float, **kwargs) -> list[TelemetryRecord]:
        if not self.available:
            return []

        start = time.perf_counter()
        try:
            raw     = await self._fetch_raw(lat, lon)
            records = self._parse(lat, lon, raw)
            self._mark_success((time.perf_counter() - start) * 1000)
            return records
        except Exception as e:
            self._mark_failure(str(e))
            return []

    async def _fetch_raw(self, lat: float, lon: float, **kwargs) -> dict:
        """STAC catalog search for recent Maxar imagery."""
        delta   = 0.05
        now     = datetime.now(timezone.utc)
        date_from = (now - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00Z")
        date_to   = now.strftime("%Y-%m-%dT23:59:59Z")

        payload = {
            "bbox":         [lon-delta, lat-delta, lon+delta, lat+delta],
            "datetime":     f"{date_from}/{date_to}",
            "collections":  ["wv03-ms"],   # WorldView-3 multispectral
            "limit":        10,
            "query": {
                "eo:cloud_cover": {"lt": 25},
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.STAC_URL,
                headers={
                    "Authorization":  f"Bearer {self._api_key}",
                    "Content-Type":   "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def _parse(self, lat: float, lon: float, raw: dict) -> list[TelemetryRecord]:
        now      = datetime.now(timezone.utc)
        features = raw.get("features", [])

        if not features:
            return []

        latest = features[0]
        props  = latest.get("properties", {})

        cloud    = float(props.get("eo:cloud_cover",    0.0)) / 100.0
        gsd      = float(props.get("gsd",               1.24))
        off_nadir = float(props.get("view:off_nadir",   10.0))
        count    = len(features)

        acq_str = props.get("datetime", "")
        try:
            acq = datetime.fromisoformat(acq_str.replace("Z", "+00:00"))
            age_h = (now - acq).total_seconds() / 3600
        except Exception:
            age_h = 48.0

        conf = (1.0 - cloud) * 0.90

        def rec(var, val, unit):
            return TelemetryRecord(
                source=self.SOURCE_NAME, variable=var,
                lat=lat, lon=lon, value=round(float(val), 5),
                unit=unit, timestamp=now,
                confidence=conf, freshness_hours=age_h,
            )

        return [
            rec("maxar_scene_count_60d",  float(count),  "count"),
            rec("maxar_cloud_cover",       cloud,         "0-1"),
            rec("maxar_gsd_m",             gsd,           "meters"),
            rec("maxar_off_nadir_deg",     off_nadir,     "degrees"),
            rec("maxar_latest_age_hours",  age_h,         "hours"),
        ]


# ════════════════════════════════════════════════════════════════════════════
# STAC ADAPTER (Universal — works with any STAC-compliant catalog)
# STAC = SpatioTemporal Asset Catalog — open standard
# Used by: AWS Earth on AWS, Microsoft Planetary Computer,
#          USGS Landsat, JAXA, and dozens more
# No auth needed for most public STAC catalogs
# ════════════════════════════════════════════════════════════════════════════

class STACAdapter(BaseAdapter):

    SOURCE_NAME            = "STAC Catalog (Microsoft Planetary Computer)"
    REFRESH_INTERVAL_HOURS = 24.0

    # Microsoft Planetary Computer — free, massive archive
    # Landsat, Sentinel, MODIS, NAIP, weather
    CATALOG_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"

    async def fetch(self, lat: float, lon: float, **kwargs) -> list[TelemetryRecord]:
        start = time.perf_counter()
        try:
            raw     = await self._fetch_raw(lat, lon)
            records = self._parse(lat, lon, raw)
            self._mark_success((time.perf_counter() - start) * 1000)
            return records
        except Exception as e:
            self._mark_failure(str(e))
            return []

    async def _fetch_raw(self, lat: float, lon: float, **kwargs) -> dict:
        delta   = 0.1
        now     = datetime.now(timezone.utc)
        date_from = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
        date_to   = now.strftime("%Y-%m-%dT23:59:59Z")

        payload = {
            "bbox":        [lon-delta, lat-delta, lon+delta, lat+delta],
            "datetime":    f"{date_from}/{date_to}",
            "collections": ["sentinel-2-l2a"],
            "limit":       5,
            "query":       {"eo:cloud_cover": {"lt": 30}},
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.CATALOG_URL, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def _fetch_raw(self, lat: float, lon: float, **kwargs) -> dict:
        delta   = 0.1
        now     = datetime.now(timezone.utc)
        date_from = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
        date_to   = now.strftime("%Y-%m-%dT23:59:59Z")

        payload = {
            "bbox":        [lon-delta, lat-delta, lon+delta, lat+delta],
            "datetime":    f"{date_from}/{date_to}",
            "collections": ["sentinel-2-l2a"],
            "limit":       5,
            "query":       {"eo:cloud_cover": {"lt": 30}},
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.CATALOG_URL, json=payload)
            resp.raise_for_status()
            return resp.json()

    def _parse(self, lat: float, lon: float, raw: dict) -> list[TelemetryRecord]:
        now      = datetime.now(timezone.utc)
        features = raw.get("features", [])

        scene_count  = len(features)
        avg_cloud    = 0.0
        if features:
            clouds = [
                float(f.get("properties", {}).get("eo:cloud_cover", 50))
                for f in features
            ]
            avg_cloud = sum(clouds) / len(clouds) / 100.0

        return [
            TelemetryRecord(
                source=self.SOURCE_NAME, variable="stac_scene_availability",
                lat=lat, lon=lon,
                value=float(scene_count), unit="scenes",
                timestamp=now, confidence=0.80, freshness_hours=24.0,
            ),
            TelemetryRecord(
                source=self.SOURCE_NAME, variable="stac_avg_cloud_cover",
                lat=lat, lon=lon,
                value=round(avg_cloud, 4), unit="0-1",
                timestamp=now, confidence=0.80, freshness_hours=24.0,
            ),
        ]


# ════════════════════════════════════════════════════════════════════════════
# SATELLITE ADAPTER REGISTRY
# Add new providers here without touching other code
# ════════════════════════════════════════════════════════════════════════════

class SatelliteAdapters:
    """Manages all commercial and free-tier satellite adapters."""

    def __init__(self):
        self.sentinel_hub = SentinelHubAdapter()
        self.planet       = PlanetLabsAdapter()
        self.maxar        = MaxarAdapter()
        self.stac         = STACAdapter()

    async def fetch_all(self, lat: float, lon: float) -> list[TelemetryRecord]:
        """Parallel fetch from all available satellite sources."""
        tasks = [
            self.stac.fetch(lat, lon),              # always free
            self.sentinel_hub.fetch(lat, lon),      # free tier 2,500/mo
        ]

        # Commercial providers — only if keys present
        if self.planet.available:
            tasks.append(self.planet.fetch(lat, lon))
        if self.maxar.available:
            tasks.append(self.maxar.fetch(lat, lon))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        records = []
        for r in results:
            if isinstance(r, list):
                records.extend(r)
        return records

    def health_report(self) -> dict:
        return {
            "sentinel_hub": {
                "available": self.sentinel_hub.available,
                **self.sentinel_hub.health_check().__dict__,
            },
            "planet": {
                "available": self.planet.available,
                **self.planet.health_check().__dict__,
            },
            "maxar": {
                "available": self.maxar.available,
                **self.maxar.health_check().__dict__,
            },
            "stac": {
                "available": True,
                **self.stac.health_check().__dict__,
            },
        }
