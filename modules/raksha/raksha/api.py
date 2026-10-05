"""Raksha service: ABAC-enforced query API + read-only TAXII 2.1 server.

Every request is authenticated (hashed bearer tokens → subject attributes), every object is
filtered through the ABAC engine, and every query writes a ledger event. Inference never leaks:
scores are computed ONLY from data the caller is allowed to read.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from prexus_core.abac import Environment, Subject, decide
from prexus_core.bundle import BundleError, load_trusted_keys
from prexus_core.ledger import Ledger, Signer

from . import METHOD, __version__, cascade as casc, scoring
from .ingest import import_bundle
from .model import norm_ts, parse_ts
from .store import StoredObject, Store

TAXII = "application/taxii+json;version=2.1"
STIX = "application/stix+json;version=2.1"
COLLECTIONS = {
    str(uuid.uuid5(uuid.NAMESPACE_URL, "raksha/cyber")): ("cyber", "Exploited vulnerabilities (CISA KEV + EPSS)", ["vulnerability"]),
    str(uuid.uuid5(uuid.NAMESPACE_URL, "raksha/events")): ("events", "Geo-referenced events (conflict, unrest, thermal anomalies)", ["x-prexus-event", "location"]),
    str(uuid.uuid5(uuid.NAMESPACE_URL, "raksha/assets")): ("assets", "Protected assets", ["x-prexus-asset", "location"]),
}


@dataclass
class Settings:
    data_dir: str
    subjects_file: str
    import_dir: str = ""
    trust_dir: str = ""
    ledger_key_file: str = ""
    network: str = "enclave"

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        return cls(e["RAKSHA_DATA_DIR"], e["RAKSHA_SUBJECTS_FILE"], e.get("RAKSHA_IMPORT_DIR", ""), e.get("RAKSHA_TRUST_DIR", ""),
                   e.get("RAKSHA_LEDGER_KEY_FILE", ""), e.get("RAKSHA_NETWORK", "enclave"))


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load_subjects(path: str) -> List[tuple[bytes, Subject]]:
    out = []
    for e in json.loads(Path(path).read_text()):
        s = Subject(id=e["id"], org=e["org"], clearance=int(e.get("clearance", 0)), compartments=frozenset(e.get("compartments", [])), roles=frozenset(e.get("roles", [])))
        out.append((bytes.fromhex(e["token_sha256"]), s))
    if not out:
        raise ValueError("no subjects configured")
    return out


class RiskReq(BaseModel):
    asset_id: str = Field(min_length=1, max_length=64)
    horizon_weeks: float = Field(4.0, gt=0, le=52)
    window_weeks: int = Field(26, ge=4, le=104)
    patched_cves: List[str] = Field(default_factory=list, max_length=200)


class CascadeReq(BaseModel):
    trials: int = Field(20_000, ge=100, le=casc.MAX_TRIALS)
    seed: Optional[int] = Field(None, ge=0, le=2**32 - 1)
    horizon_weeks: float = Field(4.0, gt=0, le=52)
    initial: Optional[Dict[str, float]] = None                       # override node failure probabilities
    dependencies: Optional[List[Dict[str, Any]]] = Field(None, max_length=casc.MAX_EDGES)
    target: Optional[str] = None


class IngestReq(BaseModel):
    path: str = Field(min_length=1, max_length=256)


def create_app(settings: Settings, *, clock=None) -> FastAPI:
    now = clock or (lambda: datetime.now(timezone.utc))
    data = Path(settings.data_dir)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    signer = Signer.load(settings.ledger_key_file) if settings.ledger_key_file else None
    if signer is None:
        if os.environ.get("RAKSHA_ENV") == "production":
            raise RuntimeError("production requires RAKSHA_LEDGER_KEY_FILE")
        kf = data / "ledger-signing-key.pem"
        signer = Signer.load(kf) if kf.exists() else (lambda s: (s.save(kf), s)[1])(Signer.generate())
    store = Store(data / "raksha.sqlite")
    ledger = Ledger(data / "ledger", signer)
    subjects = load_subjects(settings.subjects_file)
    trusted = load_trusted_keys(settings.trust_dir) if settings.trust_dir else {}
    env = Environment(network=settings.network)
    deps_default = {"edges": []}
    app = FastAPI(title="Raksha", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.ledger, app.state.signer = store, ledger, signer

    def subject_of(request: Request) -> Subject:
        h = request.headers.get("authorization", "")
        digest = bytes.fromhex(token_digest(h[7:])) if h.startswith("Bearer ") else b"\0" * 32
        found = None
        for d, s in subjects:                                      # compare against all entries: no early exit
            if hmac.compare_digest(d, digest) and found is None:
                found = s
        if found is None:
            raise HTTPException(401, "authentication required")
        return found

    def readable(subject: Subject, objs: List[StoredObject]) -> tuple[List[StoredObject], int]:
        ok = [o for o in objs if decide(subject, "read", o.resource(), env).allow]
        return ok, len(objs) - len(ok)

    def audit(subject: Subject, route: str, returned: int, denied: int, **extra) -> None:
        ledger.append(subject.id, "raksha.query", route, {"returned": returned, "denied": denied, **extra})

    def visible(subject: Subject, **q) -> List[StoredObject]:
        return readable(subject, store.query(**q))[0]

    # ── native API ───────────────────────────────────────────────────────────
    @app.get("/v1/health")
    def health():
        v = ledger.verify()
        return {"status": "ok" if v["valid"] else "degraded", "service": "raksha", "version": __version__, "method": METHOD,
                "calibrated": False, "ledger_valid": bool(v["valid"]), "objects": store.count()}

    @app.get("/v1/ledger/head")
    def ledger_head(subject: Subject = Depends(subject_of)):
        return ledger.signed_head()

    @app.get("/v1/objects")
    def objects(type: Optional[str] = None, h3: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None,
                limit: int = 100, subject: Subject = Depends(subject_of)):
        for ts_ in (since, until):
            if ts_:
                try: parse_ts(ts_)
                except ValueError: raise HTTPException(400, "bad timestamp")
        objs = store.query(types=[type] if type else None, h3_cells=[h3] if h3 else None, since=since, until=until, limit=min(max(limit, 1), 1000))
        ok, denied = readable(subject, objs)
        audit(subject, "/v1/objects", len(ok), denied)
        return {"objects": [o.body for o in ok]}

    def _asset(subject: Subject, key: str) -> Optional[Dict[str, Any]]:
        for o in visible(subject, types=["x-prexus-asset"]):
            if o.body.get("x_prexus_asset_key") == key:
                return {"id": key, "name": o.body["name"], "criticality": o.body.get("criticality"), "h3_r7": o.body["h3_r7"],
                        "technologies": o.body.get("technologies", [])}
        return None

    def _inputs(subject: Subject):
        events = [o.body for o in visible(subject, types=["x-prexus-event"], limit=200_000)]
        vulns = [o.body for o in visible(subject, types=["vulnerability"], limit=50_000)]
        return events, vulns

    @app.post("/v1/risk/asset")
    def risk_asset(req: RiskReq, subject: Subject = Depends(subject_of)):
        asset = _asset(subject, req.asset_id)
        if asset is None:
            audit(subject, "/v1/risk/asset", 0, 0)
            raise HTTPException(404, "asset not found")
        events, vulns = _inputs(subject)
        res = scoring.score_asset(asset, events, vulns, now=now(), weeks=req.window_weeks, horizon_weeks=req.horizon_weeks, patched=req.patched_cves)
        audit(subject, "/v1/risk/asset", 1, 0, asset=req.asset_id)
        return res

    @app.post("/v1/cascade")
    def cascade(req: CascadeReq, subject: Subject = Depends(subject_of)):
        events, vulns = _inputs(subject)
        assets = [{"id": o.body["x_prexus_asset_key"], "name": o.body["name"], "h3_r7": o.body["h3_r7"], "technologies": o.body.get("technologies", []),
                   "criticality": o.body.get("criticality")} for o in visible(subject, types=["x-prexus-asset"])]
        if not assets:
            raise HTTPException(404, "no assets visible")
        base = {a["id"]: scoring.score_asset(a, events, vulns, now=now(), horizon_weeks=req.horizon_weeks)["risk"] for a in assets}
        initial = {**base, **(req.initial or {})}
        deps = req.dependencies if req.dependencies is not None else deps_default["edges"]
        try:
            g = casc.graph_from_spec({k: v for k, v in initial.items() if k in base}, deps)
            seed = req.seed if req.seed is not None else int.from_bytes(os.urandom(4), "big")
            sim = casc.simulate(g, req.trials, np.random.default_rng(seed))
            crit = casc.edge_criticality(g, req.target, min(req.trials, 20_000), seed) if req.target and req.target in g.nodes else None
        except ValueError as e:
            raise HTTPException(422, str(e))
        audit(subject, "/v1/cascade", len(assets), 0, trials=req.trials, seed=seed)
        return {"method": "raksha-cascade-v0", "calibrated": False, "seed": seed, "initial_failure_probability": initial, **sim,
                "edge_criticality": crit, "disclaimer": "Edge propagation probabilities are operator-supplied priors, not measured."}

    @app.post("/v1/ingest/bundle")
    def ingest_bundle(req: IngestReq, subject: Subject = Depends(subject_of)):
        if "admin" not in subject.roles:
            ledger.append(subject.id, "raksha.ingest.denied", req.path[:64], {})
            raise HTTPException(403, "admin role required")
        if not settings.import_dir or not trusted:
            raise HTTPException(503, "bundle import not configured (RAKSHA_IMPORT_DIR / RAKSHA_TRUST_DIR)")
        try:
            return import_bundle(
                store,
                ledger,
                settings.import_dir,
                pbundle.resolve_trusted_path(settings.import_dir, req.path, strict=True).relative_to(
                    Path(settings.import_dir).resolve()
                ).as_posix(),
                trusted,
                actor=subject.id,
            )
        except FileNotFoundError:
            raise HTTPException(404, "bundle path not found")
        except BundleError as e:
            ledger.append(subject.id, "raksha.bundle.rejected", req.path[:64], {"status": e.status})
            raise HTTPException(e.status, str(e))

    def load_deps(path: str) -> None:
        deps_default["edges"] = json.loads(Path(path).read_text())["edges"]

    app.state.load_dependencies = load_deps

    # ── TAXII 2.1 (read-only) ────────────────────────────────────────────────
    def taxii(request: Request) -> None:
        a = request.headers.get("accept")
        if a and not any(x in a for x in (TAXII, "*/*", "application/*", "application/json")):
            raise HTTPException(406, f"Accept must include {TAXII}")

    def tj(data: Dict[str, Any], status: int = 200, headers: Optional[Dict[str, str]] = None) -> JSONResponse:
        return JSONResponse(data, status_code=status, media_type=TAXII, headers=headers)

    def coll(cid: str):
        if cid not in COLLECTIONS:
            raise HTTPException(404, "collection not found")
        return COLLECTIONS[cid]

    def taxii_objects(subject: Subject, cid: str, request: Request, manifest: bool = False, only_id: Optional[str] = None):
        _, _, types = coll(cid)
        q = request.query_params
        mtype = [t for t in q.get("match[type]", "").split(",") if t] or types
        if any(t not in types for t in mtype):
            raise HTTPException(400, "match[type] outside this collection")
        ids = [only_id] if only_id else [i for i in q.get("match[id]", "").split(",") if i] or None
        limit = min(max(int(q.get("limit", 100)), 1), 1000)
        try:
            raw = store.query(types=mtype, ids=ids, added_after=q.get("added_after"), limit=limit + 1, cursor=q.get("next"))
        except Exception:
            raise HTTPException(400, "bad query parameter")
        page, more = raw[:limit], len(raw) > limit
        ok, denied = readable(subject, page)
        audit(subject, f"/taxii2/collections/{cid}", len(ok), denied)
        out: Dict[str, Any] = {"more": more}
        if more:
            out["next"] = Store.cursor_for(page[-1])
        if manifest:
            out["objects"] = [{"id": o.id, "date_added": o.added_at, "version": o.modified, "media_type": STIX} for o in ok]
        else:
            out["objects"] = [o.body for o in ok]
        hdr = {}
        if ok:
            hdr = {"X-TAXII-Date-Added-First": ok[0].added_at, "X-TAXII-Date-Added-Last": ok[-1].added_at}
        if only_id and not ok:
            raise HTTPException(404, "object not found")
        return tj(out, headers=hdr)

    @app.get("/taxii2/")
    def discovery(request: Request, subject: Subject = Depends(subject_of)):
        taxii(request)
        return tj({"title": "Raksha TAXII server", "description": "Read-only STIX 2.1 feeds, ABAC-filtered per caller", "default": "/raksha/", "api_roots": ["/raksha/"]})

    @app.get("/raksha/")
    def api_root(request: Request, subject: Subject = Depends(subject_of)):
        taxii(request)
        return tj({"title": "Raksha", "description": "Threat & disruption intelligence", "versions": [TAXII], "max_content_length": 104857600})

    def coll_doc(cid: str) -> Dict[str, Any]:
        name, desc, _ = coll(cid)
        return {"id": cid, "title": name, "description": desc, "can_read": True, "can_write": False, "media_types": [STIX]}

    @app.get("/raksha/collections/")
    def collections(request: Request, subject: Subject = Depends(subject_of)):
        taxii(request)
        return tj({"collections": [coll_doc(c) for c in COLLECTIONS]})

    @app.get("/raksha/collections/{cid}/")
    def collection(cid: str, request: Request, subject: Subject = Depends(subject_of)):
        taxii(request)
        return tj(coll_doc(cid))

    @app.get("/raksha/collections/{cid}/objects/")
    def coll_objects(cid: str, request: Request, subject: Subject = Depends(subject_of)):
        taxii(request)
        return taxii_objects(subject, cid, request)

    @app.get("/raksha/collections/{cid}/manifest/")
    def coll_manifest(cid: str, request: Request, subject: Subject = Depends(subject_of)):
        taxii(request)
        return taxii_objects(subject, cid, request, manifest=True)

    @app.get("/raksha/collections/{cid}/objects/{oid}/")
    def coll_object(cid: str, oid: str, request: Request, subject: Subject = Depends(subject_of)):
        taxii(request)
        return taxii_objects(subject, cid, request, only_id=oid)

    return app
