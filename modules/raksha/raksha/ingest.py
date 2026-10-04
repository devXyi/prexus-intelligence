"""Enclave-side ingestion: verified signed bundle → parsed STIX → store, with provenance and ledger entries."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import stix2
from prexus_core import bundle as pbundle
from prexus_core.ledger import Ledger

from . import geo
from .connectors import PARSERS, epss as epss_conn
from .model import PrexusAsset, Record, confidence_of, det_id, make_location, marking
from .sources import labels_for
from .store import Store


def ingest_records(store: Store, records: Iterable[Record], *, fetched_at: str, source: str = "", bundle_name: str = "", bundle_version: int = 0,
                   raw_sha256: str = "") -> Dict[str, int]:
    counts = {"inserted": 0, "updated": 0, "duplicate": 0}
    for rec in records:
        outcome = store.put(rec, fetched_at=fetched_at)
        counts[outcome] += 1
        if bundle_name:
            store.add_provenance(rec.obj.id, source or rec.labels.source, fetched_at, bundle_name, bundle_version, raw_sha256)
    return counts


def apply_epss(store: Store, scores: Dict[str, tuple], score_date: str, *, fetched_at: str) -> Dict[str, int]:
    """Enrich KEV vulnerabilities with EPSS as a new object version (never edits in place)."""
    counts = {"enriched": 0, "unchanged": 0, "missing": 0}
    lab = labels_for("first-epss")
    for cve, (s, p) in scores.items():
        existing = store.latest(det_id("vulnerability", cve))
        if existing is None:
            counts["missing"] += 1
            continue
        body = {**existing.body, "x_prexus_epss": round(s, 5), "x_prexus_epss_percentile": round(p, 5), "x_prexus_epss_date": score_date}
        stix2.parse(json.dumps(body), allow_custom=True, version="2.1")                      # still valid STIX?
        labels = labels_for(existing.source, **{}) if existing.source in ("cisa-kev",) else lab
        outcome = store.put_body(body, labels, h3=existing.h3, event_time=existing.event_time, fetched_at=fetched_at)
        counts["unchanged" if outcome == "duplicate" else "enriched"] += 1
    return counts


def asset_records(assets: List[Dict[str, Any]]) -> List[Record]:
    recs = []
    for a in assets:
        lab = labels_for("operator-assets", owner_org=a.get("owner_org", "operator"))
        loc = make_location(a["lat"], a["lon"])
        cell = geo.cell(a["lat"], a["lon"])
        obj = PrexusAsset(id=det_id("x-prexus-asset", a["id"]), name=a["name"], asset_type=a["asset_type"], criticality=int(a.get("criticality", 3)),
                          location_ref=loc.id, h3_r7=cell, technologies=list(a.get("technologies", [])), owner_org=a.get("owner_org", "operator"),
                          created="2026-01-01T00:00:00.000Z", modified="2026-01-01T00:00:00.000Z", confidence=confidence_of(lab.credibility),
                          object_marking_refs=[marking(lab.tlp)], custom_properties={**lab.props(), "x_prexus_asset_key": a["id"]}, allow_custom=True)
        recs += [Record(loc, lab, cell, None), Record(obj, lab, cell, None)]
    return recs


def import_bundle(store: Store, ledger: Ledger, import_dir: str, rel: str, trusted: Dict[str, str], *, actor: str) -> Dict[str, Any]:
    """Verify (signature, rollback, per-file hashes) THEN parse. Nothing unverified is ever parsed."""
    manifest, d = pbundle.verify_bundle_dir(import_dir, rel, trusted, store.bundle_versions())
    fetched_at = manifest["created_at"]
    totals = {"inserted": 0, "updated": 0, "duplicate": 0, "parse_errors": 0, "epss_enriched": 0}
    epss_files = []
    for f in sorted(manifest["files"], key=lambda x: x["path"]):
        conn = f.get("connector")
        if conn == "epss":
            epss_files.append(f)
            continue
        if conn not in PARSERS:
            continue                                                            # payload with no Raksha parser is ignored, not guessed at
        text = (d / "files" / f["path"]).read_text("utf-8")
        recs, errs = PARSERS[conn](text, fetched_at)
        totals["parse_errors"] += len(errs)
        c = ingest_records(store, recs, fetched_at=fetched_at, source=f.get("source", ""), bundle_name=manifest["name"],
                           bundle_version=manifest["version"], raw_sha256=f["sha256"])
        for k in ("inserted", "updated", "duplicate"):
            totals[k] += c[k]
    for f in epss_files:                                                        # after KEV so the CVEs exist
        scores, score_date = epss_conn.parse((d / "files" / f["path"]).read_text("utf-8"), None)
        totals["epss_enriched"] += apply_epss(store, scores, score_date, fetched_at=fetched_at)["enriched"]
    store.record_bundle(manifest["name"], manifest["version"], manifest["signer_key_id"])
    ledger.append(actor, "raksha.bundle.import", manifest["name"], {"version": manifest["version"], "signer": manifest["signer_key_id"], **totals})
    return {"bundle": manifest["name"], "version": manifest["version"], **totals}
