"""
core/config.py
Meteorium Engine — Central Configuration
All environment variables, paths, constants, and system parameters.
Single source of truth across all 7 layers.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Base paths ───────────────────────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("METEORIUM_BASE", "/tmp/meteorium"))

LAKE_DIR  = BASE_DIR / "lake"
CACHE_DIR = BASE_DIR / "cache"
STORE_DIR = BASE_DIR / "store"
LOG_DIR   = BASE_DIR / "logs"

# ✅ Safe directory creation
for d in (LAKE_DIR, CACHE_DIR, STORE_DIR, LOG_DIR):
    try:
        d.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # fallback safety (never crash app)
        fallback = Path("/tmp/meteorium_fallback") / d.name
        fallback.mkdir(parents=True, exist_ok=True)


# ─── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{STORE_DIR}/meteorium.db"
)
# For production PostgreSQL:
# DATABASE_URL = "postgresql+asyncpg://user:pass@host/meteorium"


# ─── External API keys ────────────────────────────────────────────────────────
NASA_FIRMS_KEY    = os.environ.get("NASA_FIRMS_KEY",    "DEMO_KEY")
CDS_URL           = os.environ.get("CDS_URL",           "https://cds.climate.copernicus.eu/api/v2")
CDS_KEY           = os.environ.get("CDS_KEY",           "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY",    "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY",    "")
ENGINE_SECRET     = os.environ.get("ENGINE_SECRET",     "")


# ─── Monte Carlo ──────────────────────────────────────────────────────────────
MONTE_CARLO_DRAWS    = int(os.environ.get("MONTE_CARLO_DRAWS",    "10000"))
MONTE_CARLO_DRAWS_PF = int(os.environ.get("MONTE_CARLO_DRAWS_PF", "5000"))   # portfolio
MAX_PORTFOLIO_ASSETS = 200


# ─── H3 resolution levels ─────────────────────────────────────────────────────
H3_RESOLUTION_COUNTRY  = 3    # ~86,000 km²  — country aggregation
H3_RESOLUTION_REGIONAL = 5    # ~252 km²     — regional hazard zones
H3_RESOLUTION_ASSET    = 7    # ~5 km²       — primary asset query level
H3_RESOLUTION_PRECISE  = 9    # ~0.1 km²     — precision footprint


# ─── Feature freshness thresholds (hours) ─────────────────────────────────────
FRESHNESS = {
    "firms_viirs":     3.0,
    "open_meteo":      1.0,
    "era5_forecast":   6.0,
    "era5_archive":   168.0,   # 1 week (downloaded once, reused)
    "carbon_monitor":  24.0,
    "gsmap_precip":    6.0,
    "cmip6":         8760.0,   # 1 year (static projections)
    "srtm":          87600.0,  # 10 years (static elevation)
}


# ─── Ingestion worker schedules (cron-style intervals) ────────────────────────
SCHEDULE = {
    "firms_viirs":    {"hours": 3},
    "open_meteo":     {"hours": 1},
    "carbon_monitor": {"hours": 24},
    "era5_archive":   {"days":  7},
    "gsmap":          {"hours": 6},
}


# ─── Risk engine thresholds ───────────────────────────────────────────────────
RISK_ALERT_THRESHOLDS = {
    "CRITICAL": 0.85,
    "HIGH":     0.65,
    "ELEVATED": 0.45,
    "MODERATE": 0.25,
    "LOW":      0.0,
}

SCENARIO_MULTIPLIERS = {
    "ssp119":   0.88,
    "paris":    0.88,
    "ssp245":   1.12,
    "baseline": 1.12,
    "ssp370":   1.24,
    "ssp585":   1.38,
    "failed":   1.38,
}

ASSET_VULNERABILITY = {
    "agriculture":    1.35,
    "energy":         1.20,
    "infrastructure": 1.15,
    "transport":      1.15,
    "real estate":    1.10,
    "manufacturing":  1.08,
    "technology":     1.05,
    "healthcare":     1.00,
    "financial":      0.85,
}


# ─── Data lake structure ──────────────────────────────────────────────────────
LAKE_STRUCTURE = {
    "firms":   LAKE_DIR / "firms",
    "era5":    LAKE_DIR / "era5",
    "gsmap":   LAKE_DIR / "gsmap",
    "carbon":  LAKE_DIR / "carbon",
    "cmip6":   LAKE_DIR / "cmip6",
    "srtm":    LAKE_DIR / "srtm",
}

for d in LAKE_STRUCTURE.values():
    d.mkdir(parents=True, exist_ok=True)


# ─── API configuration ────────────────────────────────────────────────────────
API_HOST           = os.environ.get("HOST", "0.0.0.0")
API_PORT           = int(os.environ.get("PORT", "8001"))
API_WORKERS        = int(os.environ.get("WORKERS", "1"))
API_RELOAD         = os.environ.get("ENV", "production") == "development"
RISK_CACHE_TTL_SEC = int(os.environ.get("RISK_CACHE_TTL", "300"))


# ─── Carbon intensity benchmarks (tCO2/MWh) — static fallback ─────────────────
CARBON_INTENSITY = {
    "IND": 0.71, "CHN": 0.62, "USA": 0.38, "GBR": 0.23,
    "DEU": 0.35, "FRA": 0.07, "JPN": 0.47, "AUS": 0.65,
    "BRA": 0.09, "ZAF": 0.91, "RUS": 0.37, "CAN": 0.15,
    "KOR": 0.46, "MEX": 0.44, "IDN": 0.73, "SAU": 0.68,
    "TUR": 0.47, "ARG": 0.30, "POL": 0.74, "NGA": 0.41,
    "PAK": 0.45, "BGD": 0.52, "VNM": 0.55, "THA": 0.48,
    "EGY": 0.44, "IRN": 0.58, "IRQ": 0.61, "ARE": 0.65,
}

# Country ISO3 → ISO2
ISO3_TO_ISO2 = {
    "IND": "IN", "CHN": "CN", "USA": "US", "GBR": "GB",
    "DEU": "DE", "FRA": "FR", "JPN": "JP", "AUS": "AU",
    "BRA": "BR", "ZAF": "ZA", "RUS": "RU", "CAN": "CA",
    "KOR": "KR", "MEX": "MX", "IDN": "ID", "SAU": "SA",
    "TUR": "TR", "ARG": "AR", "POL": "PL", "NGA": "NG",
    "PAK": "PK", "BGD": "BD", "VNM": "VN", "THA": "TH",
}
