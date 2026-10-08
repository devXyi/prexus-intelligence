# Audit → fixes (v2). What changed, what proves it, what is still open

Baseline = the archive as received (`prexus-intelligence-main`). Every ✅ names the test that fails if the fix is reverted
(the `/apply` fix was mutation-checked: un-wiring the route turns 3 tests red).

**Test totals (all green in the authoring sandbox):** Go gateway 32 unit (race-clean) + 5 real-PostgreSQL-16 integration ·
Python engine 48 · `prexus_core` 30 · Raksha 31 · Node control plane 30 (28 + 2 that only run in a no-network namespace → 30/30 there) ·
Rust 23. Not run here: GitHub Actions, Docker, Render, `govulncheck`/`pip-audit`/`cargo audit`/gitleaks (no route to their databases).

## P0
| # | Finding | Status | Evidence / note |
|---|---|---|---|
| 1 | Pricing-page Apply buttons 404 (handler never routed) | ✅ | `apply_test.go`, `pg_integration_test.go`, **frontend↔route contract test** (scans every endpoint the UI calls). Also fixed while wiring: header injection (CR/LF), no SMTP timeout, hardcoded personal Gmail fallback, lead lost if SMTP down (now stored in Postgres first; `notified`/`notify_error` recorded). **Set `NOTIFY_EMAILS` + `SMTP_*` on Render** or no email is sent. |
| 2 | Engine open when `ENGINE_SECRET` unset; `/analyze`,`/chat` unauthenticated; spends LLM keys | ✅ code · ⚠ infra | `test_engine_security.py` (every OpenAPI route except `/health` → 401; refuses to boot without ≥16-char non-placeholder secret; constant-time compare; `ENGINE_SECRET_FILE`). LLM code removed from the engine. `render.yaml` makes the engine a **private service** — apply the blueprint, set provider spend caps, rotate any key that ever sat in a public repo. |
| 3 | Production ran Python fallback + grid pseudo-index (no Rust, no H3) | ✅ code · ⚠ Docker | `data-engine/Dockerfile` builds the wheel (the same `maturin build --release` was run and installed here); H3 v3/v4 shim (`test_h3compat.py`); `test_rust_parity.py` asserts `RUST_AVAILABLE`. Engine mode is visible at authenticated `GET /risk/health`. ERA5/xarray processing is still not installed → still returns `[]`. |
| 4 | DB/engine cold start takes everything down | ◐ | `/health` (liveness) vs `/ready` (DB); `InitDBWithRetry` (tested against a dead then live Postgres); startup config validation fails closed in production; no implicit public engine URL; blueprint uses always-on paid plans and a managed Postgres. Gateway still exits if the DB never appears (by design). |
| 5 | IP exposure (public repo? Apache-2.0 `LICENSE`/`NOTICE` vs "proprietary" README) | ❌ not changed | Legal/business decision. Split into private core + public site, assign IP to the company, decide the licence with counsel. Added gitleaks (CI) — run it on full history locally first. |
| 6 | Fabricated numbers / false claims | ✅ | Fake "live" stat flicker removed; UI no longer shows random fallback simulation or random risk scores; hand-typed "87 % confidence" replaced by CDF-interpolated exceedance, labelled uncalibrated; "AR6" attribution of hand-set seasonal constants removed; README rewritten where it contradicted code (routes, JWT 24 h, bcrypt, rate limits, Raksha/Healtho status, Postgres version). |

## P1
| # | Finding | Status | Evidence / note |
|---|---|---|---|
| 7 | Cross-tenant risk cache | ✅ | `risk_test.go` (key = user + path + body hash). |
| 8 | Two half-built auth systems; JWT 24 h, no revocation; open registration | ◐ | ABAC (clearance, compartments, TLP, purpose, export, no-write-down) implemented once in `prexus_core.abac` (default-deny, every decision explainable/ledgered) and enforced by Raksha. Gateway auth unchanged (bcrypt RBAC); Go `internal/auth` still unwired; no revocation/refresh; JWT still in `localStorage`. Mitigation added: per-user daily AI quota. |
| 9 | No audit ledger in the gateway | ◐ | Ledger implemented (Node + Python, cross-verified, signed head, offline verifier) — used by air-gap + Raksha. Porting to the Go gateway is next (spec: `docs/LEDGER_SPEC.md`). |
| 10 | LLM path ignored the model selector; Gemini key in URL; duplicate LLM code | ✅ | `ai_gateway_test.go`; one code path; allowlist (`ALLOWED_MODELS`); `*_BASE_URL` switches to a local model. Model IDs follow Anthropic's current lineup (+2 legacy) — re-check when models change. |
| 11 | No Go/Python tests; SLSA template; `panic=abort`; no `Cargo.lock` | ✅ | See totals; `ci.yml`; real SLSA workflow over real artifacts; `panic=abort` removed (bad input now raises `ValueError`); `Cargo.lock` committed. **Correction:** the first audit said Rust tests covered `mc_portfolio.rs` — in fact that file was never compiled (`mod mc_portfolio` missing), so its 13 tests never ran. It is compiled now and passes; there is still no PyO3 binding for it. |
| 12 | Duplicate engines/APIs/schedulers | ❌ | `api_queued.py` (wildcard CORS+credentials, unvalidated AI inputs) is not deployed — delete it or fix it. |
| 13 | State in `/tmp/meteorium` | ✅ config | Dockerfile + blueprint disk + compose volume. |
| 14 | 3 of ~19 sources wired | ❌ | Needs live-network work (see Raksha connectors for the pattern). |
| 15 | Science | ◐ | `catmodel` (Poisson/NegBin frequency × GPD severity × Weibull/Beta vulnerability, Gaussian/t copula, EP curves/AAL/VaR/TVaR, CRPS/Brier/PIT harness) verified against closed-form results. **Priors are placeholders**; no hindcast on real data (no network here); legacy sea-level term is still 0. |
| 16 | Stale docs | ✅ | `BUILD.md`, READMEs, `docs/*`. |
| 17 | Air-gap skeleton defects | ✅ code · ⚠ Docker | Per-operator auth (header identity gone), serialised fsync'd ledger, signed head, tamper tests, bundle import, internal-only engine URL, egress probe; compose uses an ingress proxy because `internal` networks publish no ports (`nginx -t` passes); full suite passes in a loopback-only network namespace. |

## Found while building (not in the first audit)
1. **Rust scenario multipliers were reversed** (Paris 1.40 … SSP5-8.5 0.70 — hottest scenario cheapest). Fixed; `test_rust_parity.py` fails on any future drift.
2. **The browser called the engine directly** (`/risk/simulate`), which is why the engine was open. Now routed through the authenticated gateway.
3. **`/alerts` was called by the UI but did not exist.** Now derived from the caller's own asset scores.
4. Hand-typed confidence buckets (see #6).

## Things only you can do
Set `NOTIFY_EMAILS`/`SMTP_*`; apply the blueprint and confirm the engine is `pserv`; rotate/cap provider keys; run gitleaks on full history; decide repo visibility + licence; provision offline signing keys and operator tokens; run `docker compose up` once and fix whatever the first real run shows.

## New components
`packages/prexus_core` (canonical JSON, ledger, bundles, ABAC) · `modules/raksha` (STIX/TAXII, scoring, cascade, back-test, builder; synthetic fixtures) · `data-engine/python/catmodel` · `airgap/control-plane` v2.
