"""The engine must fail closed: no secret → no boot; every route but /health needs the secret."""
import importlib

import pytest
from fastapi.testclient import TestClient

SECRET = "s" * 40


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("ENGINE_SECRET", SECRET)
    monkeypatch.delenv("ENGINE_ALLOW_INSECURE", raising=False)
    import layer6.api as mod
    importlib.reload(mod)
    return mod


def _client(mod):
    return TestClient(mod.app, raise_server_exceptions=False)


def _all_operations(api):
    """(METHOD, path) for every route. Uses the generated OpenAPI schema because newer
    FastAPI nests included routers (app.routes no longer lists them flat)."""
    spec = api.app.openapi()
    return [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops
            if m.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}]


def test_every_route_except_health_requires_auth(api):
    c = _client(api)
    ops = _all_operations(api)
    assert len(ops) >= 10, ops
    for method, path in ops:
        if path == "/health":
            continue
        resp = c.request(method, path, json={})
        assert resp.status_code == 401, f"{method} {path} reachable without auth: {resp.status_code}"
        bad = c.request(method, path, json={}, headers={"Authorization": "Bearer wrong"})
        assert bad.status_code == 401, f"{method} {path} accepts a wrong token"


def test_health_is_open_and_minimal(api):
    r = _client(api).get("/health")
    assert r.status_code == 200
    assert set(r.json()) == {"status", "service", "version"}      # no rust/lake/worker internals


def test_valid_token_reaches_routes(api):
    with TestClient(api.app) as c:
        h = {"Authorization": f"Bearer {SECRET}"}
        assert c.get("/sources", headers=h).status_code == 200
        assert c.get("/risk/health", headers=h).status_code == 200
        assert c.post("/analyze", json={"prompt": "x"}, headers=h).status_code == 410   # LLM moved to gateway


def test_docs_and_openapi_disabled_by_default(api):
    c = _client(api)
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p).status_code == 404


def test_refuses_to_boot_without_secret(monkeypatch):
    monkeypatch.delenv("ENGINE_SECRET", raising=False)
    monkeypatch.delenv("ENGINE_ALLOW_INSECURE", raising=False)
    import layer6.api as mod
    importlib.reload(mod)
    with pytest.raises(RuntimeError, match="ENGINE_SECRET"):
        with TestClient(mod.app):
            pass


def test_refuses_short_secret(monkeypatch):
    monkeypatch.setenv("ENGINE_SECRET", "short")
    monkeypatch.delenv("ENGINE_ALLOW_INSECURE", raising=False)
    from core import security
    with pytest.raises(RuntimeError):
        security.assert_auth_configured()


def test_unset_secret_never_means_open(monkeypatch):
    """v1 bug: empty ENGINE_SECRET made every protected route public."""
    monkeypatch.delenv("ENGINE_SECRET", raising=False)
    monkeypatch.delenv("ENGINE_ALLOW_INSECURE", raising=False)
    import layer6.api as mod
    importlib.reload(mod)
    r = TestClient(mod.app, raise_server_exceptions=False).post("/risk/asset", json={})
    assert r.status_code in (401, 503)


def test_insecure_dev_switch_is_explicit(monkeypatch):
    monkeypatch.delenv("ENGINE_SECRET", raising=False)
    monkeypatch.setenv("ENGINE_ALLOW_INSECURE", "1")
    from core import security
    security.assert_auth_configured()
    assert security.require_engine_auth(None) is True


def test_token_compare_is_constant_time(monkeypatch):
    monkeypatch.setenv("ENGINE_SECRET", SECRET)
    from core import security
    calls = []
    real = security.hmac.compare_digest
    monkeypatch.setattr(security.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    assert security.require_engine_auth(f"Bearer {SECRET}") is True
    assert calls, "secret must be compared with hmac.compare_digest"


def test_engine_has_no_llm_credentials_or_urls():
    import inspect
    import layer6.api as mod
    src = inspect.getsource(mod)
    for needle in ("api.anthropic.com", "generativelanguage.googleapis.com", "api.openai.com", "GEMINI_API_KEY"):
        assert needle not in src, f"engine still contains LLM plumbing: {needle}"


def test_simulate_endpoint_contract(api):
    with TestClient(api.app) as c:
        h = {"Authorization": f"Bearer {SECRET}"}
        ok = c.post("/risk/simulate", headers=h, json={
            "asset_id": "A1", "asset_type": "infrastructure", "scenario": "flood", "intensity": 0.7,
            "duration_days": 7, "rcp_year": 2040, "rcp_scenario": "rcp85",
            "value_usd_mm": 100, "composite_risk": 0.6, "seed": 1})
        assert ok.status_code == 200
        d = ok.json()
        for k in ("cost_impact", "damage_label", "insurance_increase_pct", "probability_pct", "calibrated", "disclaimer"):
            assert k in d
        assert d["calibrated"] is False
        assert c.post("/risk/simulate", headers=h, json={"scenario": "meteor"}).status_code == 422
        assert c.post("/risk/simulate", headers=h, json={"intensity": 1.5}).status_code == 422


def test_engine_secret_can_come_from_a_file(monkeypatch, tmp_path):
    f = tmp_path / "engine_secret"; f.write_text(SECRET + "\n")
    monkeypatch.delenv("ENGINE_SECRET", raising=False)
    monkeypatch.setenv("ENGINE_SECRET_FILE", str(f))
    from core import security
    security.assert_auth_configured()
    assert security.require_engine_auth(f"Bearer {SECRET}") is True
    monkeypatch.setenv("ENGINE_SECRET_FILE", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError):
        security.assert_auth_configured()


def test_example_placeholder_secret_is_refused(monkeypatch):
    monkeypatch.setenv("ENGINE_SECRET", "dev-engine-secret-change-in-production")
    monkeypatch.delenv("ENGINE_ALLOW_INSECURE", raising=False)
    from core import security
    with pytest.raises(RuntimeError):
        security.assert_auth_configured()
