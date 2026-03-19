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

</div>

**Base URL:** `https://prexus-intelligence.onrender.com`

All protected endpoints require a Bearer JWT issued at registration.

### Authentication Flow

```
Client                                    Prexus API
  │                                           │
  ├── POST /api/v1/auth/register ────────────►│
  │   { orgName, email, password }            │
  │◄──────────────── 200 { token, org_id } ───┤  JWT · 15 min · Authorization
  │                                           │  ABAC Clearance assigned
  │                                           │
  ├── POST /api/v1/meteorium/run ────────────►│
  │◄──────────── 200 { risk_score, VaR, ... } ┤  Level 2 clearance required
  │                                           │
```

### Endpoint Reference

<details>
<summary><strong>GET /health</strong> — Liveness probe</summary>

```json
// Response 200
{
  "status": "operational",
  "version": "2.0.0-prx",
  "ts": "2025-01-01T00:00:00Z"
}
```
</details>

<details>
<summary><strong>POST /api/v1/auth/register</strong> — Provision organisation</summary>

```json
// Request body
{
  "org_name":  "Apex Capital Management",
  "email":     "operator@apex.com",
  "password":  "***************",
  "org_type":  "FINANCIAL",
  "tier":      "ENTERPRISE"
}

// Response 201
{
  "ok": true,
  "token":   "eyJhR...",
  "org_id":  "ORG-7f3a9c2d",
  "user_id": "USR-1a2b3c4d",
  "role":    "ORG_ADMIN",
  "clearance": 2
}
```
</details>

<details>
<summary><strong>POST /api/v1/meteorium/run</strong> — Full Monte Carlo climate risk simulation</summary>

*Required headers:* `Authorization: Bearer <token>` · *Required clearance: Level 2 · Role: `ORG_ADMIN`*

```json
// Request body
{
  "horizonDays":      365,
  "scenario":         "disorderly",
  "UrbanDensity":     0.65,
  "InsuranceDrag":    0.40,
  "LiquidityShock":   0.30,
  "AssetValue":       125000000
}

// Response 200
{
  "ok": true,
  "mission_id": "MIS-8f2a5b9c",
  "intelligence_outputs": {
    "risk_score":     0.78,
    "var_95":         14.2,
    "cvar_95":        21.1,
    "expected_loss":  24879000,
    "risk_band":      "HIGH"
  },
  "simulation_params": {
    "iterations":    10000,
    "horizon_days":  3600,
    "scenario":      "disorderly"
  }
}
```
</details>

<details>
<summary><strong>POST /risk/asset</strong> — Single asset environmental risk (Python intelligence layer)</summary>

| Parameter | Type | Description |
|---|---|---|
| `asset_id` | string | Unique asset identifier |
| `lat` | float | Latitude |
| `lon` | float | Longitude |
| `country_code` | string | ISO 3166-1 alpha-2 |
| `valuation` | float | Asset value in USD |
| `scenario` | string | `baseline` \| `disorderly` \| `failed` |
| `horizon_days` | int | 180 \| 365 \| 1095 |

</details>

<details>
<summary><strong>POST /risk/portfolio</strong> — Portfolio-level aggregated risk</summary>

Aggregate risk exposure across multiple assets.

*Returns: composite risk score, expected portfolio loss, per-asset breakdown, scenario stress estimates, VaR/CVaR at portfolio level.*

</details>

### HTTP Status Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 201 | Resource created (register) |
| 400 | Malformed request body |
| 401 | Missing or expired JWT |
| 403 | Insufficient clearance / CORS origin blocked |
| 429 | Rate limit exceeded (20 req / 10 s per IP) |
| 500 | Internal server error |

<br/>

---

<div align="center">

## Security Model

</div>

```
Layer 1 — TLS 1.3          Edge encryption (client layer)
Layer 2 — JWT + ABAC        Role-based access, 15 min TTL
Layer 3 — Rate Limiting     50 req/s max, 15 sec TLS autosave
Layer 4 — CORS Policy       Origin allowlist per environment
Layer 5 — Audit Ledger      All actions logged to tamper-evident chain
Layer 6 — Password Hashing  SHA-256 + 100k iterations
```

### ABAC Role Matrix

| Role | Clearance | Accessible Endpoints |
|---|---|---|
| `PUBLIC` | 0 | `/health` |
| `ORG_VIEWER` | 1 | `/health`, `/auth/*` |
| `ORG_ADMIN` | 2 | All above + `/meteorium/run` |
| `SYS_OPERATOR` | 3 | All above + admin routes |
| `SOVEREIGN` | 5 | All routes including `/raksha/*` |

### Audit Ledger

Every authenticated action is recorded in a tamper-evident hash-chained log:

```
{ action_org, ... } ──► hash: SHA-256 ──► prev_hash
                                           │
Tamper entry 0 ──► all subsequent headers invalidated
```

<br/>

---

<div align="center">

## Deployment

</div>

### Cloud Stack

| Service | Platform | Role |
|---|---|---|
| Go API Gateway | Render Web Service | Auth, routing, audit, rate limiting |
| Python Intelligence | Render Web Service | Analytics, risk modelling |
| Frontend | Netlify CDN | Static web delivery |
| Secrets | Sentry CDN / Render Env Vars | API keys, JWT secret (auto-generated) |

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
| ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=flat-square&logo=postgresql&logoColor=white) | Structured API endpoints, persistence | 5.10+ |
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

🔄  v1.5  Raksha Module — 360-degree clearance threat intelligence,
          geopolitical risk modelling, sovereign operator dashboard

🔄  v1.6  Healtho Module — Population health risk engine,
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
| JWT Authentication + ABAC | ✅ Live | Core | Public |
| Monte Carlo Simulation | ✅ Live | Meteorium | Level 2 |
| VaR 95% / CVaR 95% | ✅ Live | Meteorium | Level 2 |
| Tamper-Evident Audit | ✅ Live | Core | Level 2 |
| 3D Climate Globe | ✅ Live | Meteorium | Level 2 |
| Meto AI (Claude / GPT-4o / Gemini) | ✅ Live | Meteorium | Level 2 |
| Portfolio Aggregation | 🔄 Progress | Meteorium | Level 2 |
| PostgreSQL Persistence | 🔄 Progress | Core | — |
| Raksha Threat Intelligence | 🔨 Planned | Raksha | Level 5 |
| Healtho Risk Engine | 🔨 Planned | Healtho | Level 3 |
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

Commercial licensing, institutional pilots, and sovereign deployment agreements are available. Contact: **[contact@prexus.io](mailto:contact@prexus.io)**

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
