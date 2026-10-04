import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "packages" / "prexus_core"))
FIX = HERE.parent / "fixtures"
NOW = "2026-09-30T12:00:00Z"

from raksha import ingest                                   # noqa: E402
from raksha.connectors import epss, firms, gdelt, kev      # noqa: E402
from raksha.store import Store                              # noqa: E402


def sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


TOKENS = {"analyst": "tok-analyst-0123456789abcdef0123456789", "outsider": "tok-outsider-0123456789abcdef0123456789",
          "admin": "tok-admin-0123456789abcdef0123456789", "cleared": "tok-cleared-0123456789abcdef0123456789"}
SUBJECTS = [
    {"id": "analyst-1", "org": "operator-1", "clearance": 2, "roles": ["analyst"], "token_sha256": sha(TOKENS["analyst"])},
    {"id": "outsider-1", "org": "other-org", "clearance": 1, "roles": ["analyst"], "token_sha256": sha(TOKENS["outsider"])},
    {"id": "admin-1", "org": "operator-1", "clearance": 2, "roles": ["admin", "analyst"], "token_sha256": sha(TOKENS["admin"])},
    {"id": "cleared-1", "org": "operator-1", "clearance": 4, "roles": ["analyst"], "token_sha256": sha(TOKENS["cleared"])},
]


@pytest.fixture()
def loaded_store():
    s = Store()
    for conn, f in (("kev", "kev.json"), ("gdelt", "gdelt_events.tsv"), ("firms", "firms_viirs.csv")):
        recs, _ = {"kev": kev, "gdelt": gdelt, "firms": firms}[conn].parse((FIX / f).read_text())
        ingest.ingest_records(s, recs, fetched_at=NOW)
    scores, d = epss.parse((FIX / "epss.csv").read_text())
    ingest.apply_epss(s, scores, d, fetched_at=NOW)
    ingest.ingest_records(s, ingest.asset_records(json.loads((FIX / "assets.json").read_text())), fetched_at=NOW)
    return s
