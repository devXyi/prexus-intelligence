"""
data-engine/python/adapters/base.py
Prexus Intelligence — Base Adapter Interface
All data source adapters implement this contract.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger("prexus.adapters")


@dataclass
class TelemetryRecord:
    """Single environmental measurement from any data source."""
    source:           str
    variable:         str            # 'temp_anomaly_c', 'fire_prob', etc.
    lat:              float
    lon:              float
    value:            float
    unit:             str
    timestamp:        datetime
    confidence:       float          # 0–1
    freshness_hours:  float          # age of underlying data
    metadata:         dict = field(default_factory=dict)

    @property
    def is_fresh(self) -> bool:
        return self.freshness_hours < 24.0

    @property
    def age_hours(self) -> float:
        delta = datetime.now(timezone.utc) - self.timestamp.replace(tzinfo=timezone.utc)
        return delta.total_seconds() / 3600


@dataclass
class AdapterHealth:
    status:       str              # 'nominal' | 'degraded' | 'offline'
    source:       str
    last_fetch:   Optional[datetime]
    latency_ms:   Optional[float]
    error:        Optional[str]    = None
    coverage_pct: float            = 100.0


class BaseAdapter(ABC):
    """
    Base class for all Meteorium data source adapters.
    Each adapter owns exactly one external data source.
    Adapters NEVER raise exceptions to callers — they return empty lists
    and set their health status to degraded/offline.
    """

    SOURCE_NAME:              str   = "unknown"
    REFRESH_INTERVAL_HOURS:   float = 6.0
    TIMEOUT_SECONDS:          int   = 30
    MAX_RETRIES:              int   = 3

    def __init__(self):
        self._last_fetch:    Optional[datetime] = None
        self._last_latency:  Optional[float]    = None
        self._error:         Optional[str]      = None
        self._status:        str                = "nominal"
        self._fetch_count:   int                = 0
        self._fail_count:    int                = 0

    @abstractmethod
    async def fetch(
        self,
        lat: float,
        lon: float,
        **kwargs
    ) -> list[TelemetryRecord]:
        """
        Fetch environmental records for a coordinate.
        Must always return a list — empty on failure, never raises.
        """
        ...

    @abstractmethod
    async def _fetch_raw(self, lat: float, lon: float, **kwargs) -> dict:
        """Internal fetch — may raise, will be caught by fetch()."""
        ...

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(
            status       = self._status,
            source       = self.SOURCE_NAME,
            last_fetch   = self._last_fetch,
            latency_ms   = self._last_latency,
            error        = self._error,
            coverage_pct = max(0.0, 100.0 - (self._fail_count / max(self._fetch_count, 1)) * 100),
        )

    def _mark_success(self, latency_ms: float):
        self._last_fetch   = datetime.now(timezone.utc)
        self._last_latency = latency_ms
        self._error        = None
        self._status       = "nominal"
        self._fetch_count += 1

    def _mark_failure(self, error: str):
        self._error      = error
        self._fail_count += 1
        self._fetch_count += 1
        fail_rate = self._fail_count / self._fetch_count
        self._status = "offline" if fail_rate > 0.8 else "degraded"
        logger.warning(f"[{self.SOURCE_NAME}] fetch failed: {error}")

    def _null_record(self, lat: float, lon: float, variable: str, unit: str = "") -> TelemetryRecord:
        """Placeholder record when data is unavailable."""
        return TelemetryRecord(
            source          = self.SOURCE_NAME,
            variable        = variable,
            lat             = lat,
            lon             = lon,
            value           = 0.0,
            unit            = unit,
            timestamp       = datetime.now(timezone.utc),
            confidence      = 0.0,
            freshness_hours = 999.0,
            metadata        = {"status": "unavailable"},
        )
