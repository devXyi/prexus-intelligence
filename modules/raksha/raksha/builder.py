"""Connected-side Data Package Builder: raw feeds → validated → signed bundle for the enclave.

  python -m raksha.builder --kev kev.json --epss epss.csv --gdelt events.tsv --firms firms.csv \\
         --key signer.key.pem --out ./outbox --name raksha-feeds --version 12

Feeds are supplied as FILES you downloaded (see docs/RAKSHA_DESIGN.md for the URLs and licences):
this module deliberately contains no network code, so the same code path is used in tests, on the
connected side, and in review. Each file is dry-run through its parser; a feed that yields no valid
records is refused rather than shipped.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Optional

from prexus_core.bundle import build_bundle
from prexus_core.ledger import Signer

from .connectors import PARSERS, epss

FILES = {"kev": ("feeds/cisa-kev.json", "cisa-kev", "CC0-1.0 / US Gov"), "epss": ("feeds/epss.csv", "first-epss", "FIRST EPSS terms"),
         "gdelt": ("feeds/gdelt-events.tsv", "gdelt", "GDELT terms — redistribution not assumed"), "firms": ("feeds/firms-viirs.csv", "nasa-firms", "NASA open data")}


def build_package(out_root: str | Path, name: str, version: int, signer: Signer, *, created_at: Optional[str] = None, **feeds: Optional[str]) -> Path:
    files: Dict[str, bytes] = {}
    meta: Dict[str, dict] = {}
    for key, text in feeds.items():
        if text is None:
            continue
        if key not in FILES:
            raise ValueError(f"unknown feed {key!r}")
        if key == "epss":
            scores, date = epss.parse(text, None)
            if not scores or not date:
                raise ValueError("EPSS feed has no valid rows or no score_date header")
        else:
            recs, errs = PARSERS[key](text, created_at or "")
            if not recs:
                raise ValueError(f"{key} feed produced no valid records ({len(errs)} errors, first: {errs[:1]})")
        path, source, lic = FILES[key]
        files[path] = text.encode("utf-8")
        meta[path] = {"connector": key, "source": source, "license": lic}
    if not files:
        raise ValueError("nothing to package")
    return build_bundle(out_root, name, version, files, signer, file_meta=meta, created_at=created_at)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in FILES:
        ap.add_argument(f"--{k}")
    ap.add_argument("--key", required=True, help="Ed25519 private key PEM (offline signing key)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--version", type=int, required=True)
    a = ap.parse_args(argv)
    feeds = {k: Path(getattr(a, k)).read_text("utf-8") for k in FILES if getattr(a, k)}
    try:
        root = build_package(a.out, a.name, a.version, Signer.load(a.key), **feeds)
    except ValueError as e:
        print(f"refusing to build: {e}", file=sys.stderr)
        return 1
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
