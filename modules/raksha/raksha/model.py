"""STIX 2.1 canonical model: standard SDOs where STIX has them, two custom SDOs where it does not.

* Vulnerability            — CVEs (CISA KEV)
* Location                 — geocoded points (deterministic ids, 3-decimal grid ≈ 110 m)
* x-prexus-event           — geo-referenced events (conflict/protest/thermal anomaly …)
* x-prexus-asset           — protected assets (ports, substations, telecom hubs …)
Every object carries: TLP marking (+ TLP 2.0 string), Admiralty source reliability (A–F) and
information credibility (1–6), `confidence`, and an H3 cell for geo indexing.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import stix2
from stix2 import properties as P

RAKSHA_NS = uuid.UUID("0b0f4c7e-6a0e-5d3e-9f7b-52a1c6e1a9d4")
EPOCH = "2020-01-01T00:00:00.000Z"
CONFIDENCE = {"1": 95, "2": 75, "3": 55, "4": 35, "5": 15}          # Admiralty credibility → STIX confidence
CATEGORIES = ("protest", "military-posture", "coercion", "assault", "armed-conflict", "mass-violence", "thermal-anomaly")


def det_id(stix_type: str, *key: Any) -> str:
    """Deterministic ids ⇒ re-ingesting the same fact never duplicates it."""
    return f"{stix_type}--{uuid.uuid5(RAKSHA_NS, '|'.join(str(k) for k in key))}"


@stix2.CustomObject("x-prexus-event", [
    ("name", P.StringProperty(required=True)),
    ("category", P.StringProperty(required=True)),
    ("event_time", P.TimestampProperty(required=True, precision="millisecond")),
    ("location_ref", P.ReferenceProperty(valid_types="location", spec_version="2.1")),
    ("h3_r7", P.StringProperty()),
])
class PrexusEvent:
    pass


@stix2.CustomObject("x-prexus-asset", [
    ("name", P.StringProperty(required=True)),
    ("asset_type", P.StringProperty(required=True)),
    ("criticality", P.IntegerProperty(min=1, max=5)),
    ("location_ref", P.ReferenceProperty(valid_types="location", spec_version="2.1")),
    ("h3_r7", P.StringProperty()),
    ("technologies", P.ListProperty(P.StringProperty)),
    ("owner_org", P.StringProperty()),
])
class PrexusAsset:
    pass


TLP_MARKING = {"CLEAR": stix2.TLP_WHITE, "GREEN": stix2.TLP_GREEN, "AMBER": stix2.TLP_AMBER,
               "AMBER+STRICT": stix2.TLP_AMBER, "RED": stix2.TLP_RED}


@dataclass(frozen=True)
class Labels:
    """Handling attributes carried with every record (they become ABAC resource attributes)."""
    source: str
    classification: int = 1
    compartments: tuple = ()
    tlp: str = "AMBER"
    owner_org: str = "prexus"
    share_orgs: tuple = ()
    license_redistribute: bool = False
    reliability: str = "C"
    credibility: str = "3"

    def props(self) -> dict:
        return {"x_prexus_tlp": self.tlp, "x_prexus_reliability": self.reliability, "x_prexus_credibility": self.credibility,
                "x_prexus_source": self.source}


@dataclass
class Record:
    obj: Any                       # a stix2 object
    labels: Labels
    h3: Optional[str] = None
    event_time: Optional[str] = None


def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def norm_ts(s: str) -> str:
    """Fixed-width UTC string (µs) so lexicographic order == chronological order in SQLite."""
    return parse_ts(s).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def confidence_of(credibility: str) -> Optional[int]:
    return CONFIDENCE.get(credibility)


def make_location(lat: float, lon: float, name: Optional[str] = None) -> stix2.Location:
    lat, lon = round(float(lat), 3), round(float(lon), 3)
    kw = {"name": name} if name else {}
    return stix2.Location(id=det_id("location", lat, lon), latitude=lat, longitude=lon, created=EPOCH, modified=EPOCH, **kw)


def marking(tlp: str):
    return TLP_MARKING[tlp]
