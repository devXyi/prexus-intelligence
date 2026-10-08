<div align="center">

<br/>

```
██████╗ ██████╗ ███████╗██╗  ██╗██╗   ██╗███████╗
██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝██║   ██║██╔════╝
██████╔╝██████╔╝█████╗   ╚███╔╝ ██║   ██║███████╗
██╔═══╝ ██╔══██╗██╔══╝   ██╔██╗ ██║   ██║╚════██║
██║     ██║  ██║███████╗██╔╝ ██╗╚██████╔╝███████║
╚═╝     ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
```

### **Sovereign AI Intelligence System**

*Anticipating systemic risk before it materialises*

<br/>

[![Status](https://img.shields.io/badge/Status-Early_Stage_Prototype-0EA5E9?style=flat-square&logoColor=white)](.)
[![Engine](https://img.shields.io/badge/Engine-Monte_Carlo_%2B_Rust-EF4444?style=flat-square)](.)
[![Clearance](https://img.shields.io/badge/Classification-Institutional_Use-F59E0B?style=flat-square)](.)
[![License UI](https://img.shields.io/badge/UI%2FDesign-Apache_2.0-10B981?style=flat-square)](./LICENSE)
[![License Core](https://img.shields.io/badge/Backend%2FEngine-Proprietary-8B5CF6?style=flat-square)](./NOTICE)

<br/>

*For governments, financial institutions, and enterprise operators*

---

[Platform Overview](#what-is-prexus) · [Architecture](#architecture) · [Intelligence Modules](#intelligence-modules) · [API Reference](#api-reference) · [Licensing](#licensing)

</div>

<br/>

---

# Prexus — Sovereign AI Intelligence System

## What is Prexus?

Prexus is an AI-driven system designed to predict large-scale risks and outcomes across complex systems such as infrastructure, geopolitics, and institutional decision-making.

Instead of reacting to events, Prexus focuses on **anticipating them**.

<br/>

---

## Why this matters

Modern systems are becoming:

- Highly interconnected
- Increasingly unpredictable
- Difficult to manage using traditional models

Governments and institutions today rely on reactive strategies.

**Prexus aims to shift this from reaction → prediction.**

<br/>

---

## What we've built

- Early-stage prototype
- Monte Carlo simulation engine (Python + Rust)
- Scenario-based risk modeling
- Probabilistic outcome forecasting

<br/>

---

## Example Output

**Input:**
- System variables (economic, infrastructure, external risks)

**Output:**
- Probability of specific events
- Simulation paths across multiple scenarios
- Risk distribution over time

<br/>

---

## How it works (simplified)

```
1. Define system variables
2. Run thousands of simulations
3. Analyze probability distributions
4. Generate predictive insights
```

<br/>

---

## Current Status

| Component | Status |
|---|---|
| Core simulation engine | ✅ Functional |
| Prototype | ✅ Completed |
| Meteorium (Climate Risk) | ✅ Live |
| Real-world dataset integration | 🔄 Expanding |
| Healtho (Health Intelligence) | 🔨 In Build |
| Raksha (Threat Intelligence) | 🔨 In Build |

<br/>

---

## Vision

To build a **sovereign intelligence layer** that enables:

- Governments to predict risks before they occur
- Institutions to make high-stakes decisions with data-backed foresight
- Systems to evolve from reactive → predictive

<br/>

---

## Tech Stack

- Python + FastAPI
- Rust (Monte Carlo simulation core)
- Go (API Gateway)
- Simulation modeling
- Probabilistic analysis

<br/>

---

## Next Steps

- Improve model accuracy
- Integrate real-world datasets
- Build scalable architecture

<br/>

---

<div align="center">

## Platform Architecture

</div>

Prexus is built as a **distributed, polyglot system** — each layer uses the best-fit language for its role.

```
┌─────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                        │
│        Gov Dashboards · Financial Terminals · Enterprise    │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS / TLS 1.3
┌──────────────────────────▼──────────────────────────────────┐
│                     API GATEWAY  (Go)                       │
│         JWT Auth · ABAC · Rate Limiting · CORS · Audit Log  │
└───────────────┬─────────────────────────┬───────────────────┘
                │                         │
┌───────────────▼──────────┐  ┌───────────▼───────────────────┐
│   INTELLIGENCE LAYER     │  │      COMPUTE LAYER            │
│       (Python)           │  │          (Rust)               │
│  · Risk Analytics        │◄─►  · Monte Carlo Engine        │
│  · Scenario Models       │  │  · VaR / CVaR                │
│  · IPCC Pathways         │  │  · Numerical Analysis        │
└───────────────┬──────────┘  └───────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│                     DATA ADAPTER LAYER                        │
│         Sentinel-1 SAR · ECMWF · Bloomberg · IPCC AR6        │
└───────────────────────────────────────────────────────────────┘
```

### Layer Breakdown

| Layer | Language | Role | Key Capability |
|---|---|---|---|
| API Gateway | Go | Request routing, auth, audit | Zero-trust ABAC, JWT, rate limiting, SHA-256 hash chain |
| Intelligence Engine | Python / FastAPI | Analytics orchestration | Risk scoring, scenario modelling, IPCC pathway integration |
| Compute Acceleration | Rust | High-performance numerics | Monte Carlo simulation, VaR/CVaR, loss distribution |
| Data Adapters | Python | External data ingestion | Climate, environmental, financial signal normalisation |
| Audit Ledger | Go | Immutable event log | SHA-256 hash-chained tamper-evident records |

<br/>

---

<div align="center">

## Intelligence Modules

</div>

Prexus is a **multi-module intelligence platform**. Each module addresses a distinct institutional risk domain. They share a common compute layer, auth infrastructure, and audit ledger.

<br/>

### ◆ Meteorium — Climate Risk Intelligence
**Status: Live**

Meteorium is the environmental intelligence core of Prexus — a dedicated risk computation engine for physical climate exposure analysis. It is the first module in production.

```
┌─────────────────────────────────────────────────────┐
│                  METEORIUM ENGINE                   │
├──────────────────────────┬──────────────────────────┤
│    Input Parameters      │   Intelligence Output    │
├──────────────────────────┼──────────────────────────┤
│ · Asset coordinates      │ · Composite Risk Score   │
│ · Asset valuation        │ · VaR 95%                │
│ · Prediction horizon     │ · CVaR 95%               │
│   (180d / 1y / 3y)       │ · Expected Loss          │
│ · Urban density factor   │ · Risk Band              │
│ · Climate scenario       │ · Audit Receipt          │
│ · Insurance coverage     │                          │
│ · Liquidity shock factor │                          │
└──────────────────────────┴──────────────────────────┘

         STOCHASTIC SIMULATION CORE
  ┌───────────────────────────────────────────┐
  │  10,000 Monte Carlo iterations            │
  │  IPCC AR6 scenario integration            │
  │  Urban density amplification  (λ)         │
  │  Insurance drag factor        (δ)         │
  │  Liquidity shock multiplier   (κ)         │
  └───────────────────────────────────────────┘
```

**Supported Climate Scenarios**

| Scenario | ID | Description | Risk Premium |
|---|---|---|---|
| 🟢 Baseline | `baseline` | Orderly, Paris-aligned policy | +0% |
| 🟡 Disorderly Transition | `disorderly` | Delayed policy action, repricing shock | +9% |
| 🔴 Failed Transition | `failed` | No policy correction, full physical exposure | +16% |

**Prediction Horizons**

| Tactical | Strategic | Structural |
|---|---|---|
| 180 Days | 1 Year | 3 Years |
| Near-term positioning | Capital planning | Long-run mispricing |

**Risk Band Classification**

| Score | Band | Indicator |
|---|---|---|
| ≥ 0.85 | `CRITICAL` | Immediate exposure — intervention required |
| ≥ 0.75 | `HIGH` | Elevated repricing risk — review urgently |
| ≥ 0.60 | `ELEVATED` | Material risk — monitor closely |
| ≥ 0.50 | `MODERATE` | Acceptable range — standard monitoring |

<br/>

---

### ◆ Meteorium UI — 3D Climate Globe

> **Platform intelligence view. Add asset to see risk visualisation.**

<!-- ═══════════════════════════════════════════════════════ -->
<!-- METEORIUM OUTPUT VIEW — Insert screenshot / GIF below  -->
<!--                                                        -->
<!--  Recommended: 1280×720 screenshot or screen recording  -->
<!--  Show: 3D globe with asset pins, warning tabs,         -->
<!--        right panel with Meto AI chat, time slider      -->
<!--                                                        -->
<!-- ![Meteorium Climate Globe](./docs/meteorium-demo.gif)  -->
<!-- ═══════════════════════════════════════════════════════ -->

*Screenshot / demo recording coming soon. The globe renders live climate risk heatmaps, asset pins with severity-graded warning tabs, RCP 8.5 scenario projection (2023–2050), and Meto AI — a 3-model intelligence assistant (Claude / GPT-4o / Gemini) with full portfolio context.*

<br/>

---

### ◆ Healtho — Health Intelligence Module
**Status: In Build**

Healtho applies the Prexus simulation core to population health and bio-systemic risk domains. Designed for national health authorities, pandemic preparedness agencies, and insurance actuaries.

**Planned capabilities:**

- Epidemic spread modelling across urban networks
- Healthcare system load forecasting under stress scenarios
- Mortality and morbidity risk curves (Monte Carlo)
- Bio-systemic shock propagation across economic sectors
- Integration with WHO datasets and national health registries

*Target clearance: Level 3 · Target deployment: National governments, Central health authorities*

<br/>

---

### ◆ Raksha — Threat Intelligence Module
**Status: In Build**

Raksha is the geopolitical and institutional threat layer of Prexus. Named for protection, it is designed to give sovereign operators 360-degree situational awareness across physical, cyber, and systemic threat vectors.

**Planned capabilities:**

- Geopolitical risk scoring with probabilistic conflict modelling
- Critical infrastructure threat surface analysis
- Supply chain disruption forecasting
- Cyber-physical threat correlation engine
- Macro-economic instability early-warning system

*Target clearance: Level 5 · Target deployment: National governments, Sovereign wealth funds, Defence ministries*

<br/>

---

<div align="center">

## API Reference

All routes are served by the Go gateway; the Python engine is a private service reachable only from the gateway.
Authentication: `Authorization: Bearer <JWT>` (24 h). Rate limit: 5 req/s per IP (burst 10); `/apply`: 3 per 2 min.

| Method · Path | Auth | Purpose |
|---|---|---|
| `GET /health` · `GET /ready` | none | liveness · readiness (database) |
| `POST /register` · `POST /login` | none | create account (role `user`) · obtain JWT |
| `POST /apply` | none | access / procurement application (stored in Postgres, emailed if SMTP configured) |
| `GET/POST/PUT/DELETE /assets[/:id]` | `assets:*` | the caller's assets |
| `GET /alerts` | `assets:read` | alerts derived from the caller's asset scores |
| `POST /risk/asset` · `/risk/portfolio` · `/risk/stress-test` | `risk:run` | Monte Carlo (Rust core) via the engine |
| `POST /risk/simulate` | `risk:run` | scenario simulation (`catmodel-v0`, **uncalibrated**) |
| `GET /risk/health` · `/sources` · `/lake/stats` · `/lake/files` | `risk:run` | engine status and data catalogue |
| `POST /claude` · `/openai` · `/gemini` · `/chat` · `/analyze` | `risk:run` + daily quota | the single LLM gateway (model allowlist, `*_BASE_URL` for local models) |
| `GET/PUT /me` · `GET /conduit/tools` | auth | profile · Conduit MCP tool list |

Errors: `400` validation · `401` missing/invalid token · `403` permission · `404` · `413` payload too large ·
`429` rate/quota · `502/503` upstream unavailable (details are logged, never returned).


## Security Model

| Layer | Implemented |
|---|---|
| Transport / CORS | explicit origin allow-list, no credentials, TLS at the platform edge |
| Authentication | JWT (HS256, 24 h, algorithm pinned); bcrypt password hashing (cost 10) with a dummy-hash timing defence |
| Authorisation | RBAC (`admin`/`user`/`viewer` → permissions). **ABAC** (clearance, compartments, TLP, purpose) lives in `packages/prexus_core` and is enforced by Raksha |
| Abuse control | per-IP rate limit (5 req/s, burst 10), strict `/apply` limiter, per-user daily AI quota, body-size caps |
| Service-to-service | engine is a private service and requires `ENGINE_SECRET` on every route; it refuses to boot without it |
| Audit | tamper-evident ledger (SHA-256 chain + Ed25519 signed head) in the air-gap control plane and Raksha; the Go gateway still logs to stdout only |
| Supply chain | CodeQL (4 languages), `govulncheck`, `pip-audit`, `cargo audit`, gitleaks, SLSA provenance for release artifacts |

Not yet implemented: token revocation / refresh tokens, per-organisation tenancy in the gateway, HSM-backed key management,
third-party penetration test. See `docs/AUDIT_FIXES.md`.


## Deployment

</div>

### Cloud Stack

| Service | Platform | Role |
|---|---|---|
| Go API Gateway | Render Web Service | Auth, routing, audit, rate limiting |
| Python Intelligence | Render Web Service | Analytics, risk modelling |
| Frontend | Netlify CDN | Static web delivery |
| Secrets | Render env-var groups (`generateValue`) / Docker secrets in the air-gap stack | JWT + engine secrets are generated, never committed |

### Quick Deploy (15 min)

```bash
# Backend — Render
# Push prexus-kernel to private GitHub repo → connect to Render

# Required environment variables on Render:
# ANTHROPIC_API_KEY       → Your Claude API key
# OPENAI_API_KEY          → Your OpenAI API key
# GEMINI_API_KEY          → Your Gemini API key
# JWT_SECRET              → Run: openssl rand -base64 32
# CORS_ALLOWED_ORIGINS    → https://your-app.netlify.app

# Frontend — Netlify
# Drag and drop /frontend folder to Netlify
# Update API_BASE in meteorium.html to point to Render URL
```

### Docker

```bash
# Build
docker build -t prexus-kernel:latest .

# Run
docker run -p 8080:8080 \
  -e JWT_SECRET=your-secret-here \
  -e ANTHROPIC_API_KEY=your-key \
  prexus-kernel:latest

# Health check
curl localhost:8080/health
```

<br/>

---

<div align="center">

## Technology Stack

</div>

| Technology | Role | Version |
|---|---|---|
| ![Go](https://img.shields.io/badge/Go-00ADD8?style=flat-square&logo=go&logoColor=white) | API gateway, middleware, audit ledger | 1.22 |
| ![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white) | Analytics, risk models, IPCC integration | 3.11+ |
| ![Rust](https://img.shields.io/badge/Rust-CE422B?style=flat-square&logo=rust&logoColor=white) | Monte Carlo engine, VaR/CVaR numerics | 1.77+ |
| ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=flat-square&logo=postgresql&logoColor=white) | Structured API endpoints, persistence | 13+ |
| ![Grafana](https://img.shields.io/badge/Grafana-F46800?style=flat-square&logo=grafana&logoColor=white) | Predictive intelligence dashboard | 18 |
| CesiumJS | 3D globe, geospatial visualisation | 1.114 |
| Three.js | WebGL heatwave overlays | r128 |
| Cloudflare | Managed cloud hosting | — |

### External Data Sources

| Source | Domain | Cadence | Integration |
|---|---|---|---|
| Sentinel-1 SAR | Physical / Geospatial | 6-day revisit | ESA Open |
| ECMWF | Meteorological | 51-member ensemble | API adapter |
| IPCC-AR6 Database | Climate Scenarios | Built-in | Bundled pathways |
| Terminal Database | Financial Signals | 12 ms lag | API adapter |

<br/>

---

<div align="center">

## Roadmap

</div>

```
✅  v1.4  Meteorium Engine — Physical risk scoring, Monte Carlo,
          API Gateway · Meteorium UI with 3D globe

🧪  v1.5  Raksha Module — 360-degree clearance threat intelligence,
          geopolitical risk modelling, sovereign operator dashboard

⬜  v1.6  Healtho Module — Population health risk engine,
          bio-systemic shock propagation, epidemic modelling

⬜  v1.7  PostgreSQL Persistence — Full asset history, org workspaces,
          audit-trail queryable database

⬜  v1.8  Real-time streaming — WebSocket push for live intelligence,
          multi-asset portfolio event feeds

⬜  v2.0  Macro-Economic Module — Cross-domain risk correlation,
          supply chain intelligence, geospatial signals
```

<br/>

---

<div align="center">

## Platform Capabilities Matrix

</div>

| Capability | Status | Module | Clearance |
|---|---|---|---|
| Health / Liveness Probe | ✅ Live | Core | Public |
| Organisation Registration | ✅ Live | Core | Public |
| JWT Authentication + RBAC | ✅ Live | Core | Public |
| Monte Carlo Simulation | ✅ Live | Meteorium | Level 2 |
| VaR 95% / CVaR 95% | ✅ Live | Meteorium | Level 2 |
| Tamper-Evident Audit | ✅ Live | Core | Level 2 |
| 3D Climate Globe | ✅ Live | Meteorium | Level 2 |
| Meto AI (Claude / GPT-4o / Gemini) | ✅ Live | Meteorium | Level 2 |
| Portfolio Aggregation | 🔄 Progress | Meteorium | Level 2 |
| PostgreSQL Persistence | ✅ Gateway (users, assets, applications) · ⬜ engine lake (SQLite) | Core | — |
| Raksha Threat Intelligence | 🧪 v0 scaffold | Raksha | ABAC in `prexus_core` |
| Healtho Risk Engine | 📝 Planned (no code) | Healtho | — |
| Macro-Economic Module | 🔨 Planned | Macro | Level 3 |
| Geospatial Signals | 🔨 Planned | Geo | Level 4 |
| Supply Chain Intelligence | 🔨 Planned | Supply | Level 3 |
| Real-time WebSocket Feed | 🔨 Planned | Core | Level 2 |

<br/>

---

<div align="center">

## Target Deployment Environments

</div>

| Sector | Use Case | Key Modules |
|---|---|---|
| **National Government** | Climate resilience planning, infrastructure stress testing | Raksha, Geo |
| **Central Banks** | Systemic climate-financial risk, portfolio exposure | Meteorium, Core |
| **Asset Managers** | Portfolio-level climate VaR, regulatory disclosure (TCFD) | Meteorium |
| **Insurance / Reinsurance** | Physical risk underwriting, loss modelling | Meteorium |
| **Infrastructure Planning** | Asset optimisation, multi-scenario planning | Meteorium, Supply |
| **Sovereign Wealth Funds** | Long-horizon structural risk, geopolitical overlays | All modules |

<br/>

---

<div align="center">

## Licensing

</div>

Prexus Intelligence operates under a **dual licensing model** that cleanly separates open interface from proprietary intelligence.

### What is open — Apache 2.0

The **user interface, design system, and frontend components** of Prexus are released under the Apache 2.0 License. This includes:

- All files under `/frontend/` (HTML, CSS, JavaScript)
- UI design tokens, component styles, layout system
- The Meteorium globe interface and dashboard shell
- Index, hub, landing, and demo pages

You may use, modify, and distribute these under standard Apache 2.0 terms.

### What is proprietary — Prexus Intelligence Proprietary License

The **backend systems, intelligence pipelines, simulation engines, and data infrastructure** are proprietary to Prexus Intelligence and are **not licensed for external use, reproduction, or deployment** without a signed agreement. This includes:

- `/backend/` — Go API gateway, auth, audit ledger, risk proxy
- `/data-engine/` — Python intelligence layers (Layer 0–6), FastAPI endpoints
- `/data-engine/rust/` — Monte Carlo simulation engine, VaR/CVaR computation
- All risk models, IPCC pathway integrations, scenario calibration logic
- The Prexus intelligence architecture, scoring algorithms, and data fusion methods

Commercial licensing, institutional pilots, and sovereign deployment agreements are available. Contact: **[dev@prexus.in](mailto:dev@prexus.in)**

See [`LICENSE`](./LICENSE) (Apache 2.0) and [`NOTICE`](./NOTICE) (Proprietary terms) for full details.

<br/>

---

<div align="center">

<br/>

```
P R E X U S   I N T E L L I G E N C E
```

**Sovereign Predictive Intelligence Infrastructure**

[![Apache 2.0 — UI/Design](https://img.shields.io/badge/UI%2FDesign-Apache_2.0-10B981?style=flat-square)](./LICENSE)
[![Proprietary — Backend/Engine](https://img.shields.io/badge/Backend%2FEngine-Proprietary-8B5CF6?style=flat-square)](./NOTICE)
[![Classification](https://img.shields.io/badge/Classification-RESTRICTED-EF4444?style=flat-square)](.)

*For authorised institutional recipients only*

<br/>

© Prexus Intelligence. All rights reserved.

</div>
