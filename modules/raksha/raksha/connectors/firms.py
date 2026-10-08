"""NASA FIRMS VIIRS active-fire CSV → thermal-anomaly events (low-confidence detections dropped)."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import List, Tuple

from .. import geo
from ..model import PrexusEvent, Record, confidence_of, det_id, make_location, marking, ts
from ..sources import labels_for

NAME = "nasa-firms"
KEEP = {"n", "nominal", "h", "high"}


def parse(text: str, fetched_at: str = "") -> Tuple[List[Record], List[str]]:
    lab, recs, errs = labels_for(NAME), [], []
    for n, row in enumerate(csv.DictReader(io.StringIO(text)), 2):
        conf = str(row.get("confidence", "")).strip().lower()
        if conf.isdigit():
            if int(conf) < 50:
                continue
        elif conf not in KEEP:
            continue
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            hhmm = str(row["acq_time"]).zfill(4)
            when = datetime.strptime(f"{row['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
            frp = row.get("frp", "")
        except (KeyError, ValueError):
            errs.append(f"row {n}: unparseable")
            continue
        loc = make_location(lat, lon)
        cell = geo.cell(lat, lon)
        key = (round(lat, 4), round(lon, 4), row["acq_date"], hhmm, row.get("satellite", ""))
        props = {**lab.props(), "x_prexus_satellite": row.get("satellite", ""), "x_prexus_frp": str(frp),
                 "x_prexus_daynight": row.get("daynight", ""), "x_prexus_detect_confidence": conf}
        ev = PrexusEvent(id=det_id("x-prexus-event", "firms", *key), name=f"thermal anomaly {row['acq_date']} {hhmm}Z",
                         category="thermal-anomaly", event_time=ts(when), location_ref=loc.id, h3_r7=cell,
                         created=ts(when), modified=ts(when), confidence=confidence_of(lab.credibility),
                         object_marking_refs=[marking(lab.tlp)], custom_properties=props, allow_custom=True)
        recs += [Record(loc, lab, cell, None), Record(ev, lab, cell, ts(when))]
    return recs, errs
