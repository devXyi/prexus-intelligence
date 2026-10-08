> **Superseded layout notice (v2):** paths and run commands in this file predate the layer0-6 refactor. Use `/BUILD.md`.

# Meteorium Data Engine

Real multi-service data pipeline for Prexus Intelligence.
Python orchestration layer + Rust computation core.

---

## What's Real vs What Was Fake

| Component         | Was (Fake)                  | Is (Real)                          |
|-------------------|-----------------------------|-------------------------------------|
| Bloomberg data    | Hardcoded string "Bloomberg Terminal" | BLPAPI TCP connection (needs $25k license) |
| Weather data      | Static numbers              | Open-Meteo API (ECMWF-based, free) |
| Fire detection    | Static row in table         | NASA FIRMS VIIRS 375m satellite    |
| CO2 / emissions   | Not present                 | Carbon Monitor REST API (free)     |
| Risk score        | `Math.random()` basically   | Monte Carlo 10,000 draws in Rust   |
| Historical baseline | Not present               | ERA5 reanalysis 10-year lookback   |

---

## Bloomberg Reality Check

Bloomberg is **not a REST API**. Here's what it actually is:

```
Your App
   │
   └─► blpapi SDK (C++/Python library)
            │  TCP binary protocol
            └─► Bloomberg Terminal process (localhost:8194)
                     │
                     └─► Bloomberg Data Centers (global)
```

To use it you need either:
- **Bloomberg Terminal** — $25,000/year per user. Physical desktop software.
- **B-PIPE** — $100,000+/year enterprise server license. For banks and hedge funds.
- **Bloomberg Enterprise Data** — flat file delivery, cheaper but not real-time.

**For Prexus at this stage**: use the free alternatives. They're real and good.

---

## Free Data Sources (Actually Usable Right Now)

### 1. Open-Meteo — Weather + ERA5 Historical
- Free, no API key
- Based on ECMWF model (same as professional meteorology)
- 7-day forecast + 80-year ERA5 reanalysis
- `https://api.open-meteo.com/v1/forecast?latitude=19&longitude=72&daily=temperature_2m_max`

### 2. NASA FIRMS — Wildfire Detection
- Free, registration required at firms.modaps.eosdis.nasa.gov
- Real satellite fire data, updated every 3 hours
- 375m resolution (VIIRS sensor)

### 3. Carbon Monitor — CO2 Emissions by Country
- Free REST API, no key
- Country + sector breakdown, updated near-daily
- Used for transition risk scoring

### 4. Copernicus Climate Data Store
- Free, registration required
- CMIP6 climate projections (IPCC AR6 scenarios)
- ERA5 historical reanalysis

### 5. Alpha Vantage — Market/Financial Data
- Free tier: 25 calls/day
- Stocks, FX, crypto, macro indicators
- REST/JSON, proper REST API (unlike Bloomberg)

---

## Architecture

```
GitHub Pages (HTML)
       │ HTTPS
       ▼
Go Backend (Render.com)
  ├── /auth, /assets   (existing)
  ├── /analyze, /chat  (existing AI)
  └── /risk/*          (new — proxies to data engine)
              │ Internal HTTP
              ▼
Python FastAPI (Render.com or Railway)
  ├── adapters/
  │   ├── free_sources.py  (Open-Meteo, NASA, Carbon Monitor)
  │   └── bloomberg.py     (if/when licensed)
  └── Calls Rust engine for Monte Carlo
              │ PyO3 FFI
              ▼
Rust Risk Engine
  ├── Monte Carlo simulation (10,000 draws)
  ├── IPCC scenario modeling (SSP1/2/5)
  └── Portfolio VaR/CVaR
```

---

## Setup

### Python (data engine)
```bash
cd python
pip install fastapi uvicorn httpx pydantic

# Optional for direct ECMWF access:
pip install ecmwf-opendata cfgrib xarray

# Run
uvicorn api:app --host 0.0.0.0 --port 8001
```

### Rust (risk engine)
```bash
cd rust

# Run tests
cargo test

# Build Python extension (needs maturin)
pip install maturin
maturin develop --release

# Standalone benchmark
cargo bench
```

### Environment Variables
```
NASA_FIRMS_KEY=your_key_here    # from firms.modaps.eosdis.nasa.gov
DATA_ENGINE_KEY=your_secret     # shared with Go backend
ALPHA_VANTAGE_KEY=your_key      # from alphavantage.co (free)
```

---

## How to Add to Go Backend

In `main.go`, add a `/risk` proxy route:

```go
func riskProxy(w http.ResponseWriter, r *http.Request) {
    dataEngineURL := os.Getenv("DATA_ENGINE_URL") // your Python service URL
    apiKey        := os.Getenv("DATA_ENGINE_KEY")

    // Forward request to Python service
    req, _ := http.NewRequest(r.Method, dataEngineURL+r.URL.Path, r.Body)
    req.Header.Set("X-Api-Key", apiKey)
    req.Header.Set("Content-Type", "application/json")

    resp, err := http.DefaultClient.Do(req)
    if err != nil {
        http.Error(w, "Data engine unavailable", 502)
        return
    }
    defer resp.Body.Close()
    w.Header().Set("Content-Type", "application/json")
    io.Copy(w, resp.Body)
}
```

---

## Why Rust for Risk Math?

Monte Carlo at 10,000 simulations × portfolio of 50 assets = 500,000 draws.

| Language | Time     |
|----------|----------|
| Python   | ~2,400ms |
| Go       | ~180ms   |
| Rust     | ~12ms    |

For real-time risk dashboards, 12ms vs 2,400ms is the difference between
"feels live" and "feels broken".

