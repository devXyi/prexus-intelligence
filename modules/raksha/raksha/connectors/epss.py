"""FIRST EPSS daily CSV → {cve: (probability_30d, percentile)}. Enrichment only (applied as a new object version)."""
from __future__ import annotations

import csv
import io
import re
from typing import Dict, Iterable, Optional, Tuple

NAME = "first-epss"


def parse(text: str, wanted: Optional[Iterable[str]] = None) -> Tuple[Dict[str, Tuple[float, float]], str]:
    wanted = set(wanted) if wanted is not None else None
    score_date, body = "", []
    for line in text.splitlines():
        if line.startswith("#"):
            m = re.search(r"score_date:([0-9T:\-Z.]+)", line)
            if m:
                score_date = m.group(1)
        elif line.strip():
            body.append(line)
    out: Dict[str, Tuple[float, float]] = {}
    for row in csv.DictReader(io.StringIO("\n".join(body))):
        cve = (row.get("cve") or "").strip()
        if wanted is not None and cve not in wanted:
            continue
        try:
            s, p = float(row["epss"]), float(row["percentile"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0.0 <= s <= 1.0 and 0.0 <= p <= 1.0:
            out[cve] = (s, p)
    return out, score_date
