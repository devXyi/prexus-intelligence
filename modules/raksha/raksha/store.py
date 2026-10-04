"""SQLite object store with STIX versioning, ABAC attributes and provenance.

Idempotent: re-ingesting identical content is a no-op; changed content becomes a NEW VERSION
(`modified` strictly increases) — STIX-native, never an in-place edit.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prexus_core.abac import Resource

from .model import Labels, Record, norm_ts, parse_ts

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
  id TEXT NOT NULL, modified TEXT NOT NULL, type TEXT NOT NULL,
  classification INTEGER NOT NULL, compartments TEXT NOT NULL, tlp TEXT NOT NULL, owner_org TEXT NOT NULL,
  share_orgs TEXT NOT NULL, license_redistribute INTEGER NOT NULL, source TEXT NOT NULL,
  h3_r7 TEXT, event_time TEXT, added_at TEXT NOT NULL, body TEXT NOT NULL, content_sha256 TEXT NOT NULL,
  PRIMARY KEY (id, modified));
CREATE INDEX IF NOT EXISTS idx_obj_type ON objects(type);
CREATE INDEX IF NOT EXISTS idx_obj_h3 ON objects(h3_r7);
CREATE INDEX IF NOT EXISTS idx_obj_time ON objects(event_time);
CREATE INDEX IF NOT EXISTS idx_obj_added ON objects(added_at, id, modified);
CREATE TABLE IF NOT EXISTS provenance (
  object_id TEXT NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL, bundle_name TEXT NOT NULL,
  bundle_version INTEGER NOT NULL, raw_sha256 TEXT NOT NULL, PRIMARY KEY (object_id, bundle_name, bundle_version));
CREATE TABLE IF NOT EXISTS bundles (
  name TEXT PRIMARY KEY, version INTEGER NOT NULL, signer_key_id TEXT NOT NULL, accepted_at TEXT NOT NULL);
"""


def content_hash(body: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in body.items() if k != "modified"}, sort_keys=True).encode()).hexdigest()


@dataclass
class StoredObject:
    body: Dict[str, Any]
    classification: int
    compartments: frozenset
    tlp: str
    owner_org: str
    share_orgs: frozenset
    license_redistribute: bool
    source: str
    h3: Optional[str]
    event_time: Optional[str]
    added_at: str

    @property
    def id(self) -> str:
        return self.body["id"]

    @property
    def modified(self) -> str:
        return self.body["modified"]

    def resource(self) -> Resource:
        return Resource(classification=self.classification, compartments=self.compartments, tlp=self.tlp, owner_org=self.owner_org,
                        share_orgs=self.share_orgs, license_redistribute=self.license_redistribute)


def _row(r) -> StoredObject:
    return StoredObject(json.loads(r["body"]), r["classification"], frozenset(json.loads(r["compartments"])), r["tlp"], r["owner_org"],
                        frozenset(json.loads(r["share_orgs"])), bool(r["license_redistribute"]), r["source"], r["h3_r7"], r["event_time"], r["added_at"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()

    # ── write ────────────────────────────────────────────────────────────────
    def put_body(self, body: Dict[str, Any], labels: Labels, *, h3: Optional[str] = None, event_time: Optional[str] = None,
                 fetched_at: Optional[str] = None) -> str:
        with self._lock:
            body = dict(body)
            latest = self.latest(body["id"])
            now = norm_ts(fetched_at) if fetched_at else _now()
            if latest is not None:
                if content_hash(latest.body) == content_hash(body):
                    return "duplicate"
                floor = parse_ts(latest.modified) + timedelta(milliseconds=1)
                bumped = max(parse_ts(now), floor)
                body["modified"] = bumped.strftime("%Y-%m-%dT%H:%M:%S.") + f"{bumped.microsecond // 1000:03d}Z"
                outcome = "updated"
            else:
                outcome = "inserted"
            self.db.execute(
                "INSERT INTO objects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (body["id"], norm_ts(body["modified"]), body["type"], labels.classification, json.dumps(sorted(labels.compartments)), labels.tlp,
                 labels.owner_org, json.dumps(sorted(labels.share_orgs)), int(labels.license_redistribute), labels.source, h3,
                 norm_ts(event_time) if event_time else None, now, json.dumps(body, sort_keys=True), content_hash(body)))
            self.db.commit()
            return outcome

    def put(self, rec: Record, *, fetched_at: Optional[str] = None) -> str:
        return self.put_body(json.loads(rec.obj.serialize()), rec.labels, h3=rec.h3, event_time=rec.event_time, fetched_at=fetched_at)

    def add_provenance(self, object_id: str, source: str, fetched_at: str, bundle_name: str, bundle_version: int, raw_sha256: str) -> None:
        with self._lock:
            self.db.execute("INSERT OR IGNORE INTO provenance VALUES (?,?,?,?,?,?)", (object_id, source, fetched_at, bundle_name, bundle_version, raw_sha256))
            self.db.commit()

    def record_bundle(self, name: str, version: int, signer_key_id: str) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO bundles VALUES (?,?,?,?)", (name, version, signer_key_id, _now()))
            self.db.commit()

    def bundle_versions(self) -> Dict[str, int]:
        return {r["name"]: r["version"] for r in self.db.execute("SELECT name, version FROM bundles")}

    # ── read ─────────────────────────────────────────────────────────────────
    def latest(self, stix_id: str) -> Optional[StoredObject]:
        r = self.db.execute("SELECT * FROM objects WHERE id=? ORDER BY modified DESC LIMIT 1", (stix_id,)).fetchone()
        return _row(r) if r else None

    def versions(self, stix_id: str) -> List[StoredObject]:
        return [_row(r) for r in self.db.execute("SELECT * FROM objects WHERE id=? ORDER BY modified", (stix_id,))]

    def count(self, type_: Optional[str] = None) -> int:
        q, a = ("SELECT COUNT(DISTINCT id) FROM objects WHERE type=?", (type_,)) if type_ else ("SELECT COUNT(DISTINCT id) FROM objects", ())
        return self.db.execute(q, a).fetchone()[0]

    def provenance(self, object_id: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM provenance WHERE object_id=?", (object_id,))]

    def query(self, *, types: Optional[Sequence[str]] = None, ids: Optional[Sequence[str]] = None, h3_cells: Optional[Iterable[str]] = None,
              since: Optional[str] = None, until: Optional[str] = None, added_after: Optional[str] = None, limit: int = 1000,
              cursor: Optional[str] = None) -> List[StoredObject]:
        """Latest version of each matching object, ordered by (added_at, id, modified) for stable pagination."""
        where, args = ["(o.id, o.modified) IN (SELECT id, MAX(modified) FROM objects GROUP BY id)"], []
        def in_clause(col, vals):
            vals = list(vals)
            where.append(f"o.{col} IN ({','.join('?' * len(vals))})" if vals else "0")
            args.extend(vals)
        if types: in_clause("type", types)
        if ids: in_clause("id", ids)
        if h3_cells is not None: in_clause("h3_r7", h3_cells)
        if since: where.append("o.event_time >= ?"); args.append(norm_ts(since))
        if until: where.append("o.event_time < ?"); args.append(norm_ts(until))
        if added_after: where.append("o.added_at > ?"); args.append(norm_ts(added_after))
        if cursor:
            a, i, m = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            where.append("(o.added_at, o.id, o.modified) > (?,?,?)"); args += [a, i, m]
        sql = f"SELECT o.* FROM objects o WHERE {' AND '.join(where)} ORDER BY o.added_at, o.id, o.modified LIMIT ?"
        with self._lock:
            return [_row(r) for r in self.db.execute(sql, (*args, int(limit)))]

    @staticmethod
    def cursor_for(o: StoredObject) -> str:
        return base64.urlsafe_b64encode(json.dumps([o.added_at, o.id, norm_ts(o.modified)]).encode()).decode()
