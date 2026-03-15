"""
layer0/sources.py
Meteorium Engine — LAYER 0: Satellite & Agency Source Registry
Complete catalogue of every external data source Meteorium ingests.
This is the source of truth for what data exists, where it comes from,
how fresh it is, and what format it arrives in.
"""

from core.models import DataSource

# ════════════════════════════════════════════════════════════════════════════
# COMPLETE SOURCE REGISTRY
# Every source Meteorium knows about — active, planned, or fallback.
# ════════════════════════════════════════════════════════════════════════════

REGISTRY: dict[str, DataSource] = {

    # ── WEATHER & CLIMATE ──────────────────────────────────────────────────

    "open_meteo_forecast": DataSource(
        id                = "open_meteo_forecast",
        name              = "Open-Meteo ECMWF Forecast",
        agency            = "Open-Meteo / ECMWF",
        type              = "weather_forecast",
        format            = "json",
        update_freq_hours = 1.0,
        requires_key      = False,
        key_env_var       = None,
        base_url          = "https://api.open-meteo.com/v1/forecast",
        coverage          = "global",
        resolution_km     = 9.0,
        latency_hours     = 0.5,
        notes             = "Free, no key. Best-match model selects IFS or GFS. "
                            "7-day forecast, hourly. Temperature, precipitation, "
                            "wind, humidity, soil moisture, evapotranspiration.",
    ),

    "open_meteo_era5": DataSource(
        id                = "open_meteo_era5",
        name              = "Open-Meteo ERA5 Historical Archive",
        agency            = "ECMWF / Open-Meteo",
        type              = "climate_reanalysis",
        format            = "json",
        update_freq_hours = 168.0,
        requires_key      = False,
        key_env_var       = None,
        base_url          = "https://archive-api.open-meteo.com/v1/archive",
        coverage          = "global",
        resolution_km     = 31.0,
        latency_hours     = 120.0,   # ~5 day lag
        notes             = "ERA5 from 1940–present. 10-year baseline for "
                            "anomaly detection. Free via Open-Meteo wrapper.",
    ),

    "era5_cds": DataSource(
        id                = "era5_cds",
        name              = "ERA5 Reanalysis via Copernicus CDS",
        agency            = "ECMWF / Copernicus",
        type              = "climate_reanalysis",
        format            = "netcdf",
        update_freq_hours = 168.0,
        requires_key      = True,
        key_env_var       = "CDS_KEY",
        base_url          = "https://cds.climate.copernicus.eu/api/v2",
        coverage          = "global",
        resolution_km     = 31.0,
        latency_hours     = 120.0,
        notes             = "Full ERA5: 80+ variables, hourly, 1940–present. "
                            "cdsapi Python client. Free account at "
                            "cds.climate.copernicus.eu. NetCDF format.",
    ),

    "gfs_noaa": DataSource(
        id                = "gfs_noaa",
        name              = "NOAA GFS Global Forecast",
        agency            = "NOAA / NCEP",
        type              = "weather_forecast",
        format            = "grib2",
        update_freq_hours = 6.0,
        requires_key      = False,
        key_env_var       = None,
        base_url          = "https://nomads.ncep.noaa.gov/dods/gfs_0p25",
        coverage          = "global",
        resolution_km     = 27.8,
        latency_hours     = 4.0,
        notes             = "16-day forecast, 0.25° resolution. "
                            "GRIB2 format requires cfgrib/eccodes. "
                            "Updated 4× daily. NOAA Big Data on AWS S3.",
    ),

    # ── FIRE & THERMAL ANOMALIES ──────────────────────────────────────────

    "firms_viirs": DataSource(
        id                = "firms_viirs",
        name              = "NASA FIRMS VIIRS 375m",
        agency            = "NASA EOSDIS",
        type              = "fire_detection",
        format            = "csv",
        update_freq_hours = 3.0,
        requires_key      = True,
        key_env_var       = "NASA_FIRMS_KEY",
        base_url          = "https://firms.modaps.eosdis.nasa.gov/api/area/csv",
        coverage          = "global",
        resolution_km     = 0.375,
        latency_hours     = 3.0,
        notes             = "VIIRS instrument on Suomi-NPP & NOAA-20. "
                            "375m resolution. Fire Radiative Power (FRP) in MW. "
                            "Confidence: low/nominal/high. Free key at "
                            "firms.modaps.eosdis.nasa.gov/api/ — 2 minutes.",
    ),

    "firms_modis": DataSource(
        id                = "firms_modis",
        name              = "NASA FIRMS MODIS 1km",
        agency            = "NASA EOSDIS",
        type              = "fire_detection",
        format            = "csv",
        update_freq_hours = 6.0,
        requires_key      = True,
        key_env_var       = "NASA_FIRMS_KEY",
        base_url          = "https://firms.modaps.eosdis.nasa.gov/api/area/csv",
        coverage          = "global",
        resolution_km     = 1.0,
        latency_hours     = 6.0,
        notes             = "Same API as VIIRS, source=MODIS_NRT. "
                            "1km resolution, longer archive. "
                            "Backup when VIIRS unavailable.",
    ),

    # ── SATELLITE MULTISPECTRAL ───────────────────────────────────────────

    "sentinel2_s3": DataSource(
        id                = "sentinel2_s3",
        name              = "Sentinel-2 MSI L2A (AWS)",
        agency            = "ESA / Copernicus",
        type              = "multispectral",
        format            = "cog_geotiff",
        update_freq_hours = 120.0,   # 5-day revisit
        requires_key      = False,
        key_env_var       = None,
        base_url          = "s3://sentinel-cogs/sentinel-s2-l2a-cogs",
        coverage          = "global",
        resolution_km     = 0.01,    # 10m
        latency_hours     = 24.0,
        notes             = "13 spectral bands. NDVI, NDWI, NBR, NDBI indices. "
                            "Cloud-optimized GeoTIFF on AWS S3 (requester-pays). "
                            "MGRS tile grid. boto3 + rasterio to access.",
    ),

    "sentinel1_sar": DataSource(
        id                = "sentinel1_sar",
        name              = "Sentinel-1 SAR C-Band",
        agency            = "ESA / Copernicus",
        type              = "sar_radar",
        format            = "safe_geotiff",
        update_freq_hours = 240.0,   # 10-day revisit
        requires_key      = False,
        key_env_var       = None,
        base_url          = "https://scihub.copernicus.eu/dhus",
        coverage          = "global",
        resolution_km     = 0.01,    # 10m
        latency_hours     = 24.0,
        notes             = "Sees through clouds and at night. "
                            "VV/VH polarization. Flood mapping: SAR "
                            "backscatter drops sharply over water. "
                            "Free via Copernicus Data Space.",
    ),

    # ── PRECIPITATION ────────────────────────────────────────────────────

    "gsmap_jaxa": DataSource(
        id                = "gsmap_jaxa",
        name              = "JAXA GSMaP Precipitation",
        agency            = "JAXA",
        type              = "precipitation",
        format            = "netcdf",
        update_freq_hours = 1.0,
        requires_key      = True,
        key_env_var       = "JAXA_KEY",
        base_url          = "ftp://rainmap:Niskur+1404@hokusai.eorc.jaxa.jp",
        coverage          = "global",
        resolution_km     = 11.1,    # 0.1°
        latency_hours     = 4.0,
        notes             = "Hourly global precipitation at 0.1° resolution. "
                            "~4h latency. Near-real-time product. "
                            "Free registration at JAXA G-Portal.",
    ),

    "gpm_imerg": DataSource(
        id                = "gpm_imerg",
        name              = "NASA GPM IMERG",
        agency            = "NASA",
        type              = "precipitation",
        format            = "hdf5",
        update_freq_hours = 0.5,
        requires_key      = True,
        key_env_var       = "NASA_EARTHDATA_TOKEN",
        base_url          = "https://gpm.nasa.gov/data/imerg",
        coverage          = "global",
        resolution_km     = 11.1,
        latency_hours     = 6.0,
        notes             = "Global Precipitation Measurement. "
                            "30-min estimates, 0.1° grid. "
                            "NASA Earthdata account required (free).",
    ),

    # ── EMISSIONS & CARBON ────────────────────────────────────────────────

    "carbon_monitor": DataSource(
        id                = "carbon_monitor",
        name              = "Carbon Monitor CO₂",
        agency            = "Carbon Monitor Consortium",
        type              = "emissions",
        format            = "json",
        update_freq_hours = 24.0,
        requires_key      = False,
        key_env_var       = None,
        base_url          = "https://carbonmonitor.org/api",
        coverage          = "country_level",
        resolution_km     = 9999.0,  # country-level
        latency_hours     = 120.0,   # ~5-day lag
        notes             = "Near-real-time CO₂ by country and sector. "
                            "Power, industry, transport, residential, aviation. "
                            "Free API, no key. carbonmonitor.org",
    ),

    "global_forest_watch": DataSource(
        id                = "global_forest_watch",
        name              = "Global Forest Watch Deforestation",
        agency            = "WRI / Hansen / UMD",
        type              = "land_cover",
        format            = "geotiff",
        update_freq_hours = 8760.0,  # annual
        requires_key      = False,
        key_env_var       = None,
        base_url          = "https://opendata.arcgis.com/datasets/globalforestwatch",
        coverage          = "global",
        resolution_km     = 0.03,    # 30m
        latency_hours     = 8760.0,
        notes             = "Annual forest cover loss at 30m. "
                            "Hansen dataset via GFW API. "
                            "Transition risk proxy for land-use policy.",
    ),

    # ── CLIMATE SCENARIOS ────────────────────────────────────────────────

    "cmip6_esgf": DataSource(
        id                = "cmip6_esgf",
        name              = "CMIP6 Climate Projections (ESGF)",
        agency            = "IPCC / WCRP",
        type              = "climate_scenario",
        format            = "netcdf",
        update_freq_hours = 87600.0,  # static / annual release
        requires_key      = False,
        key_env_var       = None,
        base_url          = "https://esgf-node.llnl.gov/search/cmip6",
        coverage          = "global",
        resolution_km     = 111.0,   # ~1°
        latency_hours     = 0.0,
        notes             = "SSP1-1.9, SSP2-4.5, SSP3-7.0, SSP5-8.5. "
                            "Multi-model ensemble (100+ models). "
                            "2025–2100 projections. Download once, store. "
                            "Use pre-computed statistical summaries.",
    ),

    # ── ELEVATION & TERRAIN ──────────────────────────────────────────────

    "srtm_nasa": DataSource(
        id                = "srtm_nasa",
        name              = "NASA SRTM Digital Elevation",
        agency            = "NASA / USGS",
        type              = "elevation",
        format            = "geotiff",
        update_freq_hours = 87600.0,  # static
        requires_key      = False,
        key_env_var       = None,
        base_url          = "https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003",
        coverage          = "global_land",
        resolution_km     = 0.03,    # 30m
        latency_hours     = 0.0,
        notes             = "Shuttle Radar Topography Mission. "
                            "30m global elevation. Download once. "
                            "Required for flood routing and inundation models.",
    ),

    # ── OCEAN & SEA LEVEL ────────────────────────────────────────────────

    "cmems_ocean": DataSource(
        id                = "cmems_ocean",
        name              = "Copernicus Marine Service (CMEMS)",
        agency            = "Copernicus / Mercator Ocean",
        type              = "ocean_analysis",
        format            = "netcdf",
        update_freq_hours = 24.0,
        requires_key      = True,
        key_env_var       = "CMEMS_KEY",
        base_url          = "https://nrt.cmems-du.eu/motu-web/Motu",
        coverage          = "global_ocean",
        resolution_km     = 9.0,
        latency_hours     = 24.0,
        notes             = "Sea level anomalies, SST, currents, waves. "
                            "Coastal asset risk: storm surge + SLR. "
                            "Free registration at marine.copernicus.eu.",
    ),

    # ── GROUNDWATER ─────────────────────────────────────────────────────

    "grace_fo": DataSource(
        id                = "grace_fo",
        name              = "NASA GRACE-FO Groundwater",
        agency            = "NASA / GFZ",
        type              = "groundwater",
        format            = "netcdf",
        update_freq_hours = 720.0,   # monthly
        requires_key      = True,
        key_env_var       = "NASA_EARTHDATA_TOKEN",
        base_url          = "https://podaac.jpl.nasa.gov/GRACE-FO",
        coverage          = "global",
        resolution_km     = 330.0,   # ~3°
        latency_hours     = 1440.0,  # ~2 month lag
        notes             = "Gravity anomaly → groundwater storage. "
                            "Critical for agricultural and water infrastructure. "
                            "NASA Earthdata (free) via earthaccess library.",
    ),

    # ── ISRO ────────────────────────────────────────────────────────────

    "insat_3d": DataSource(
        id                = "insat_3d",
        name              = "ISRO INSAT-3D/3DR Meteorological",
        agency            = "ISRO / IMD",
        type              = "weather_geostationary",
        format            = "hdf5",
        update_freq_hours = 0.5,     # 30-min slots
        requires_key      = True,
        key_env_var       = "MOSDAC_KEY",
        base_url          = "https://mosdac.gov.in/data",
        coverage          = "south_asia_indian_ocean",
        resolution_km     = 4.0,
        latency_hours     = 1.0,
        notes             = "Geostationary over Indian subcontinent. "
                            "Temperature profiles, humidity, cloud properties. "
                            "MOSDAC portal: mosdac.gov.in (free registration). "
                            "Primary for South Asian asset risk.",
    ),

    "resourcesat2": DataSource(
        id                = "resourcesat2",
        name              = "ISRO Resourcesat-2A LISS",
        agency            = "ISRO / NRSC",
        type              = "multispectral",
        format            = "geotiff",
        update_freq_hours = 576.0,   # 24-day revisit
        requires_key      = True,
        key_env_var       = "BHUVAN_KEY",
        base_url          = "https://bhuvan-app1.nrsc.gov.in/bhuvan2d",
        coverage          = "india_regional",
        resolution_km     = 0.024,   # 24m LISS-III
        latency_hours     = 48.0,
        notes             = "LISS-III (24m) and LISS-IV (5.8m). "
                            "Vegetation, agricultural health for Indian assets. "
                            "Bhuvan portal: bhuvan.nrsc.gov.in",
    ),

}


# ─── Source categories ────────────────────────────────────────────────────────

FREE_SOURCES = [s.id for s in REGISTRY.values() if not s.requires_key]
KEYED_SOURCES = [s.id for s in REGISTRY.values() if s.requires_key]

LAYER1_PRIORITY = [
    "open_meteo_forecast",   # always available, no key
    "firms_viirs",           # fire — free key, 2 min
    "carbon_monitor",        # emissions — no key
    "open_meteo_era5",       # climate baseline — no key
    "gsmap_jaxa",            # precipitation — free key
    "era5_cds",              # full reanalysis — free key
    "cmems_ocean",           # ocean — free key
    "grace_fo",              # groundwater — free key
    "sentinel2_s3",          # optical satellite — no key
    "insat_3d",              # ISRO geostationary — free key
    "cmip6_esgf",            # scenarios — no key
    "srtm_nasa",             # elevation — no key (download once)
]


def get_source(source_id: str) -> DataSource:
    if source_id not in REGISTRY:
        raise KeyError(f"Unknown source: {source_id}")
    return REGISTRY[source_id]


def active_sources(available_keys: set[str]) -> list[DataSource]:
    """Return sources that can run given the available API keys."""
    result = []
    for src in REGISTRY.values():
        if not src.requires_key:
            result.append(src)
        elif src.key_env_var and src.key_env_var in available_keys:
            result.append(src)
    return result

