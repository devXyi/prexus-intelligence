import json
import shutil
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from prexus_core.bundle import build_bundle
from prexus_core.ledger import Signer
from raksha import builder, ingest
from raksha.api import Settings, create_app
from raksha.connectors import epss, firms, gdelt, kev
from raksha.store import Store
from conftest import FIX, NOW, SUBJECTS, TOKENS

H = lambda who: {"Authorization": f"Bearer {TOKENS[who]}"}
CLOCK = lambda: datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


@pytest.fixture()
def env(tmp_path, loaded_store):
    (tmp_path / "subjects.json").write_text(json.dumps(SUBJECTS))
    signer = Signer.generate()
    trust = tmp_path / "trust"; trust.mkdir(); (trust / "k.pem").write_text(signer.public_pem)
    st = Settings(str(tmp_path / "data"), str(tmp_path / "subjects.json"), str(tmp_path / "import"), str(trust))
    app = create_app(st, clock=CLOCK)
    # load the fixture store content into the service store
    for o in loaded_store.query(limit=1_000_000):
        pass
    svc: Store = app.state.store
    svc.db.executescript("")  # no-op; keep API symmetrical
    from raksha.model import Labels
    for o in loaded_store.query(limit=1_000_000):
        for v in loaded_store.versions(o.id):
            svc.put_body(v.body, Labels(v.source, v.classification, tuple(v.compartments), v.tlp, v.owner_org, tuple(v.share_orgs), v.license_redistribute),
                         h3=v.h3, event_time=v.event_time, fetched_at=v.added_at)
    app.state.load_dependencies(str(FIX / "dependencies.json"))
    return TestClient(app), app, signer, tmp_path


def test_auth_required_everywhere_except_health(env):
    c, *_ = env
    assert c.get("/v1/health").status_code == 200
    for path in ("/v1/objects", "/v1/ledger/head", "/taxii2/", "/raksha/", "/raksha/collections/"):
        assert c.get(path).status_code == 401, path
        assert c.get(path, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post("/v1/risk/asset", json={"asset_id": "x"}).status_code == 401
    assert c.post("/v1/cascade", json={}).status_code == 401
    assert c.post("/v1/ingest/bundle", json={"path": "x"}).status_code == 401


def test_abac_hides_other_orgs_assets_but_not_public_feeds(env):
    c, *_ = env
    mine = c.get("/v1/objects?type=x-prexus-asset", headers=H("analyst")).json()["objects"]
    theirs = c.get("/v1/objects?type=x-prexus-asset", headers=H("outsider")).json()["objects"]
    assert len(mine) == 5 and theirs == []                                       # AMBER + other org ⇒ invisible
    assert len(c.get("/v1/objects?type=vulnerability", headers=H("outsider")).json()["objects"]) == 8   # TLP:CLEAR is open
    assert c.get("/v1/risk/asset", headers=H("outsider")).status_code == 405
    assert c.post("/v1/risk/asset", json={"asset_id": "port-alpha"}, headers=H("outsider")).status_code == 404   # cannot even confirm it exists


def test_risk_endpoint_is_computed_only_from_visible_data(env):
    c, app, *_ = env
    r = c.post("/v1/risk/asset", json={"asset_id": "port-alpha"}, headers=H("analyst"))
    assert r.status_code == 200
    body = r.json()
    assert body["calibrated"] is False and body["components"]["cyber"]["matched"]
    assert c.post("/v1/risk/asset", json={"asset_id": "nope"}, headers=H("analyst")).status_code == 404
    assert c.post("/v1/risk/asset", json={"asset_id": "port-alpha", "horizon_weeks": 0}, headers=H("analyst")).status_code == 422
    patched = c.post("/v1/risk/asset", json={"asset_id": "port-alpha", "patched_cves": [m["cve"] for m in body["components"]["cyber"]["matched"]]}, headers=H("analyst")).json()
    assert patched["components"]["cyber"]["p"] == 0.0 and patched["risk"] < body["risk"]


def test_clearance_gates_classified_objects(env):
    c, app, *_ = env
    from raksha.model import Labels
    from raksha import ingest as ing
    import stix2
    store: Store = app.state.store
    obj = json.loads(stix2.Vulnerability(name="CVE-2030-0001", created="2026-09-01T00:00:00Z", modified="2026-09-01T00:00:00Z").serialize())
    store.put_body(obj, Labels("operator-assets", classification=4, compartments=("SIGINT",), tlp="CLEAR"))
    seen = lambda who: [o["name"] for o in c.get("/v1/objects?type=vulnerability&limit=1000", headers=H(who)).json()["objects"]]
    assert "CVE-2030-0001" not in seen("analyst") and "CVE-2030-0001" not in seen("cleared")   # cleared lacks the SIGINT compartment
    store.put_body({**obj, "id": obj["id"].replace("0", "1", 1)}, Labels("operator-assets", classification=4, tlp="CLEAR"))
    assert "CVE-2030-0001" in seen("cleared") and "CVE-2030-0001" not in seen("analyst")


def test_every_query_is_audited_and_ledger_stays_valid(env):
    c, app, *_ = env
    c.get("/v1/objects?type=vulnerability", headers=H("analyst"))
    c.get("/v1/objects?type=x-prexus-asset", headers=H("outsider"))
    ev = [e for e in app.state.ledger.events if e["action"] == "raksha.query"]
    assert ev[-2]["actor"] == "analyst-1" and ev[-2]["metadata"]["returned"] == 8
    assert ev[-1]["actor"] == "outsider-1" and ev[-1]["metadata"] == {"returned": 0, "denied": 5}
    assert c.get("/v1/health").json()["ledger_valid"] is True
    head = c.get("/v1/ledger/head", headers=H("analyst")).json()
    assert head["signed"] and head["sequence"] == app.state.ledger.seq


def test_cascade_endpoint(env):
    c, *_ = env
    r = c.post("/v1/cascade", json={"trials": 20000, "seed": 5, "target": "refinery-delta"}, headers=H("analyst"))
    assert r.status_code == 200
    b = r.json()
    assert set(b["p_fail"]) == {"port-alpha", "grid-beta", "telecom-gamma", "refinery-delta", "depot-epsilon"}
    assert b["p_fail"]["refinery-delta"] >= b["initial_failure_probability"]["refinery-delta"] - 0.01     # dependencies can only add failure
    assert b["edge_criticality"][0]["reduction"] >= b["edge_criticality"][-1]["reduction"]
    assert c.post("/v1/cascade", json={"trials": 20000, "seed": 5, "target": "refinery-delta"}, headers=H("analyst")).json()["p_fail"] == b["p_fail"]   # reproducible
    assert c.post("/v1/cascade", json={"trials": 10}, headers=H("analyst")).status_code == 422
    assert c.post("/v1/cascade", json={"dependencies": [{"from": "a", "to": "zzz", "p": 0.5}]}, headers=H("analyst")).status_code == 422
    assert c.post("/v1/cascade", json={}, headers=H("outsider")).status_code == 404       # sees no assets


# ── TAXII 2.1 ────────────────────────────────────────────────────────────────
def test_taxii_discovery_collections_and_envelope(env):
    c, *_ = env
    h = {**H("analyst"), "Accept": "application/taxii+json;version=2.1"}
    d = c.get("/taxii2/", headers=h)
    assert d.headers["content-type"].startswith("application/taxii+json;version=2.1") and d.json()["api_roots"] == ["/raksha/"]
    assert c.get("/raksha/", headers=h).json()["versions"] == ["application/taxii+json;version=2.1"]
    cols = c.get("/raksha/collections/", headers=h).json()["collections"]
    assert {x["title"] for x in cols} == {"cyber", "events", "assets"} and all(x["can_read"] and not x["can_write"] for x in cols)
    cyber = next(x["id"] for x in cols if x["title"] == "cyber")
    env_ = c.get(f"/raksha/collections/{cyber}/objects/", headers=h)
    j = env_.json()
    assert j["more"] is False and len(j["objects"]) == 8 and "X-TAXII-Date-Added-First" in env_.headers
    assert c.get(f"/raksha/collections/{cyber}/objects/?match[type]=x-prexus-event", headers=h).status_code == 400
    assert c.get("/raksha/collections/nope/", headers=h).status_code == 404
    assert c.get("/taxii2/", headers={**H("analyst"), "Accept": "text/html"}).status_code == 406


def test_taxii_pagination_manifest_single_object_and_stix_roundtrip(env):
    import stix2
    c, app, *_ = env
    h = H("analyst")
    events = next(x["id"] for x in c.get("/raksha/collections/", headers=h).json()["collections"] if x["title"] == "events")
    got, nxt, pages = [], None, 0
    while True:
        r = c.get(f"/raksha/collections/{events}/objects/?limit=60&match[type]=x-prexus-event" + (f"&next={nxt}" if nxt else ""), headers=h).json()
        got += r["objects"]; pages += 1
        if not r["more"]: break
        nxt = r["next"]
    assert pages > 2 and len({o["id"] for o in got}) == len(got) == app.state.store.count("x-prexus-event")
    man = c.get(f"/raksha/collections/{events}/manifest/?limit=5&match[type]=x-prexus-event", headers=h).json()
    assert {"id", "date_added", "version", "media_type"} <= set(man["objects"][0])
    one = c.get(f"/raksha/collections/{events}/objects/{got[0]['id']}/", headers=h)
    assert one.status_code == 200 and one.json()["objects"][0]["id"] == got[0]["id"]
    assert c.get(f"/raksha/collections/{events}/objects/x-prexus-event--00000000-0000-5000-8000-000000000000/", headers=h).status_code == 404
    for o in got[:25]:                                    # every served object is valid STIX 2.1
        stix2.parse(json.dumps(o), allow_custom=True, version="2.1")


def test_taxii_respects_abac(env):
    c, *_ = env
    assets = next(x["id"] for x in c.get("/raksha/collections/", headers=H("outsider")).json()["collections"] if x["title"] == "assets")
    assert c.get(f"/raksha/collections/{assets}/objects/?match[type]=x-prexus-asset", headers=H("outsider")).json()["objects"] == []
    assert len(c.get(f"/raksha/collections/{assets}/objects/?match[type]=x-prexus-asset", headers=H("analyst")).json()["objects"]) == 5


# ── signed-bundle pipeline (connected builder → enclave import) ─────────────
def test_builder_to_enclave_end_to_end(env):
    c, app, signer, tmp = env
    pkg = builder.build_package(tmp / "import", "raksha-feeds", 1, signer, created_at="2026-10-01T00:00:00Z",
                                kev=(FIX / "kev.json").read_text(), epss=(FIX / "epss.csv").read_text(),
                                gdelt=(FIX / "gdelt_events.tsv").read_text(), firms=(FIX / "firms_viirs.csv").read_text())
    assert c.post("/v1/ingest/bundle", json={"path": pkg.name}, headers=H("analyst")).status_code == 403     # not admin
    r = c.post("/v1/ingest/bundle", json={"path": pkg.name}, headers=H("admin"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["version"] == 1 and j["parse_errors"] == 1 and j["duplicate"] > 0                              # fixtures already loaded → idempotent
    assert c.post("/v1/ingest/bundle", json={"path": pkg.name}, headers=H("admin")).status_code == 409     # replay refused
    tampered = builder.build_package(tmp / "import", "raksha-feeds", 2, signer, created_at="2026-10-02T00:00:00Z", kev=(FIX / "kev.json").read_text())
    (tampered / "files" / "feeds" / "cisa-kev.json").write_text("{}")
    assert c.post("/v1/ingest/bundle", json={"path": tampered.name}, headers=H("admin")).status_code == 422
    rogue = Signer.generate()
    bad = builder.build_package(tmp / "import", "raksha-feeds", 3, rogue, created_at="2026-10-03T00:00:00Z", kev=(FIX / "kev.json").read_text())
    assert c.post("/v1/ingest/bundle", json={"path": bad.name}, headers=H("admin")).status_code == 403
    assert c.post("/v1/ingest/bundle", json={"path": "../../etc"}, headers=H("admin")).status_code in (403, 404)
    acts = [e["action"] for e in app.state.ledger.events]
    assert "raksha.bundle.import" in acts and acts.count("raksha.bundle.rejected") >= 3


def test_builder_refuses_empty_or_garbage_feeds(tmp_path):
    s = Signer.generate()
    with pytest.raises(ValueError, match="no valid records"):
        builder.build_package(tmp_path, "raksha-feeds", 1, s, kev='{"vulnerabilities": []}')
    with pytest.raises(ValueError, match="nothing to package"):
        builder.build_package(tmp_path, "raksha-feeds", 1, s)
    with pytest.raises(ValueError, match="EPSS"):
        builder.build_package(tmp_path, "raksha-feeds", 1, s, epss="cve,epss,percentile\n")
