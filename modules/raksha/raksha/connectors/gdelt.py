"""GDELT 2.0 Events export (tab-separated, 61 columns, no header) → x-prexus-event.

Column indices follow the GDELT 2.0 event codebook (reproduced from the published schema:
0 GLOBALEVENTID … 28 EventRootCode, 30 GoldsteinScale, 31 NumMentions, 32 NumSources, 34 AvgTone,
52 ActionGeo_FullName, 53 ActionGeo_CountryCode, 56/57 ActionGeo_Lat/Long, 59 DATEADDED, 60 SOURCEURL).
Verify against a live sample on the connected side before relying on it (the builder runs a schema check).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

import stix2

from .. import geo
from ..model import PrexusEvent, Record, confidence_of, det_id, make_location, marking, ts
from ..sources import labels_for

NAME = "gdelt"
N_COLS = 61
I = dict(id=0, a1=6, a2=16, root=28, goldstein=30, mentions=31, sources=32, tone=34, place=52, country=53, lat=56, lon=57, added=59, url=60)
CAMEO_ROOT = {"14": "protest", "15": "military-posture", "17": "coercion", "18": "assault", "19": "armed-conflict", "20": "mass-violence"}


def _credibility(num_sources: int) -> str:
    return "2" if num_sources >= 5 else "3" if num_sources >= 2 else "4"      # corroboration heuristic (tunable)


def parse(text: str, fetched_at: str = "") -> Tuple[List[Record], List[str]]:
    recs, errs = [], []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        c = line.split("\t")
        if len(c) < N_COLS:
            errs.append(f"line {n}: expected {N_COLS} columns, got {len(c)}")
            continue
        cat = CAMEO_ROOT.get(c[I["root"]].strip())
        if cat is None:
            continue                                                         # not a category Raksha tracks
        try:
            lat, lon = float(c[I["lat"]]), float(c[I["lon"]])
            when = datetime.strptime(c[I["added"]].strip(), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            nsrc = int(c[I["sources"]] or 0)
            nment = int(c[I["mentions"]] or 0)
        except ValueError:
            errs.append(f"line {n}: unparseable lat/lon/time")
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            errs.append(f"line {n}: invalid coordinates")
            continue
        lab = labels_for(NAME, credibility=_credibility(nsrc))
        loc = make_location(lat, lon, c[I["place"]][:120] or None)
        cell = geo.cell(lat, lon)
        a1, a2 = c[I["a1"]].strip() or "unknown", c[I["a2"]].strip() or "unknown"
        kw = {}
        url = c[I["url"]].strip()
        if url.startswith(("http://", "https://")) and len(url) <= 500:
            kw["external_references"] = [stix2.ExternalReference(source_name="gdelt-source", url=url)]
        props = {**lab.props(), "x_prexus_cameo_root": c[I["root"]].strip(), "x_prexus_num_sources": nsrc,
                 "x_prexus_num_mentions": nment, "x_prexus_goldstein": c[I["goldstein"]].strip(),
                 "x_prexus_avg_tone": c[I["tone"]].strip(), "x_prexus_country": c[I["country"]].strip(), "x_prexus_gdelt_id": c[I["id"]].strip()}
        ev = PrexusEvent(id=det_id("x-prexus-event", "gdelt", c[I["id"]].strip()), name=f"{cat}: {a1} / {a2}"[:200],
                         category=cat, event_time=ts(when), location_ref=loc.id, h3_r7=cell, created=ts(when), modified=ts(when),
                         confidence=confidence_of(lab.credibility), object_marking_refs=[marking(lab.tlp)],
                         custom_properties=props, allow_custom=True, **kw)
        recs.append(Record(loc, lab, cell, None))
        recs.append(Record(ev, lab, cell, ts(when)))
    return recs, errs
