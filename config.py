"""
ERA5 -> CESM Forcing Data Pipeline -- Configuration
=====================================================

Edit the settings below, then run the pipeline steps in order:

    python download.py           # Step 1: Download ERA5 data from CDS
    python preprocess.py         # Step 2: Resample hourly -> 3-hourly
    python convert.py            # Step 3: Convert to CESM forcing format

Utility:
    python inspect_nc.py <file>  # Inspect any NetCDF file

Prerequisites:
    uv sync                      # Install Python dependencies
    CDS API key configured       # See https://cds.climate.copernicus.eu
"""

# -- Time Range -------------------------------------------------------
START_YEAR = 2019
END_YEAR = 2023

# -- Spatial Region ----------------------------------------------------
# CDS API download area: [North, West, South, East]
DOWNLOAD_AREA = [55, 114, 45, 124]

# Target grid for CESM output (0.1 deg resolution)
TARGET_LAT = (45.1, 54.9)    # (south, north)
TARGET_LON = (115.5, 124.0)  # (west, east)
TARGET_RES = 0.1              # degrees

# -- Directory Paths ---------------------------------------------------
ERA5_RAW_DIR = r"G:\ERA5"                      # Step 1 output
ERA5_PROCESSED_DIR = r"G:\ERA5_3h\processed"   # Step 2 output
CESM_OUTPUT_DIR = r"G:\cesm_forc_data"         # Step 3 output

# -- ERA5 Variable Definitions ----------------------------------------
#
# Each entry defines a variable to download, preprocess, and convert.
#
# Download fields:
#   cds_name       - Variable name for the CDS API request
#   dataset        - CDS dataset identifier
#   pressure_level - (optional) Pressure level in hPa
#
# Preprocessing fields:
#   era5_var       - Variable name inside the downloaded NetCDF file
#   cumulative     - True for accumulated variables (precip, radiation)
#
# CESM conversion fields (omit for wind components):
#   cesm_var       - CESM output variable name
#   units          - CESM output units
#   long_name      - CESM long_name attribute
#   conversion     - Multiplication factor: ERA5 value -> CESM units
#   min_value      - Floor value (None = no constraint)
#   group          - Output file group: "prec", "solar", or "TPQWL"

VARIABLES = {
    "precipitation": {
        "cds_name": "total_precipitation",
        "dataset": "reanalysis-era5-land",
        "era5_var": "tp",
        "cumulative": True,
        "cesm_var": "PRECTmms",
        "units": "mm H2O / sec",
        "long_name": "PRECTmms total precipitation",
        "conversion": 1000 / 10800,  # m per 3h -> mm/s
        "min_value": 0.0,
        "group": "prec",
    },
    "solar_radiation": {
        "cds_name": "surface_solar_radiation_downwards",
        "dataset": "reanalysis-era5-land",
        "era5_var": "ssrd",
        "cumulative": True,
        "cesm_var": "FSDS",
        "units": "W/m**2",
        "long_name": "FSDS total incident solar radiation",
        "conversion": 1 / 10800,  # J/m2 per 3h -> W/m2
        "min_value": 0.0,
        "group": "solar",
    },
    "longwave_flux": {
        "cds_name": "surface_thermal_radiation_downwards",
        "dataset": "reanalysis-era5-single-levels",
        "era5_var": "strd",
        "cumulative": True,
        "cesm_var": "FLDS",
        "units": "W/m**2",
        "long_name": "FLDS incident longwave radiation",
        "conversion": 1 / 10800,
        "min_value": 1.0,
        "group": "TPQWL",
    },
    "surface_pressure": {
        "cds_name": "surface_pressure",
        "dataset": "reanalysis-era5-single-levels",
        "era5_var": "sp",
        "cumulative": False,
        "cesm_var": "PSRF",
        "units": "Pa",
        "long_name": "surface pressure at the lowest atm level",
        "conversion": 1.0,
        "min_value": None,
        "group": "TPQWL",
    },
    "2m_temperature": {
        "cds_name": "2m_temperature",
        "dataset": "reanalysis-era5-single-levels",
        "era5_var": "t2m",
        "cumulative": False,
        "cesm_var": "TBOT",
        "units": "K",
        "long_name": "temperature at the lowest atm level",
        "conversion": 1.0,
        "min_value": None,
        "group": "TPQWL",
    },
    "10m_u_wind": {
        "cds_name": "10m_u_component_of_wind",
        "dataset": "reanalysis-era5-single-levels",
        "era5_var": "u10",
        "cumulative": False,
        # No cesm_var -- combined with v_wind to compute WIND
    },
    "10m_v_wind": {
        "cds_name": "10m_v_component_of_wind",
        "dataset": "reanalysis-era5-single-levels",
        "era5_var": "v10",
        "cumulative": False,
    },
    "specific_humidity": {
        "cds_name": "specific_humidity",
        "dataset": "reanalysis-era5-pressure-levels",
        "era5_var": "q",
        "cumulative": False,
        "pressure_level": 1000,
        "cesm_var": "QBOT",
        "units": "kg/kg",
        "long_name": "specific humidity at the lowest atm level",
        "conversion": 1.0,
        "min_value": 0.0,
        "group": "TPQWL",
    },
}

# Wind speed (computed from u10 + v10)
WIND = {
    "cesm_var": "WIND",
    "units": "m/s",
    "long_name": "wind at the lowest atm level",
    "min_value": 0.0,
    "group": "TPQWL",
}

# CESM output filename prefix
CESM_FILE_PREFIX = "clmforc.0.1x0.1"
