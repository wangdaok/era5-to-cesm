"""
Step 1: Download ERA5 data from the Copernicus Climate Data Store.

Downloads all variables defined in config.py for the specified year range.
Existing files are automatically skipped.

Usage:
    python download.py                    # All years from config
    python download.py --years 2020 2021  # Specific years only
"""
import argparse
import os

import cdsapi

import config as cfg


def download_one(client, name, var_def, year):
    """Download one variable for one year. Skips if file exists."""
    filepath = os.path.join(cfg.ERA5_RAW_DIR, f"{name}_{year}.nc")
    if os.path.exists(filepath):
        print(f"  [skip] {os.path.basename(filepath)}")
        return

    request = {
        "product_type": ["reanalysis"],
        "variable": [var_def["cds_name"]],
        "year": [str(year)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "area": cfg.DOWNLOAD_AREA,
        "data_format": "netcdf",  # Use "format" for older CDS API versions
    }
    if "pressure_level" in var_def:
        request["pressure_level"] = [str(var_def["pressure_level"])]

    try:
        client.retrieve(var_def["dataset"], request, filepath)
        print(f"  [done] {os.path.basename(filepath)}")
    except Exception as exc:
        print(f"  [FAIL] {os.path.basename(filepath)}: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Download ERA5 data from CDS")
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=list(range(cfg.START_YEAR, cfg.END_YEAR + 1)),
        help="Years to download (default: range from config)",
    )
    args = parser.parse_args()

    os.makedirs(cfg.ERA5_RAW_DIR, exist_ok=True)
    client = cdsapi.Client()

    for year in sorted(args.years):
        print(f"\nYear {year}")
        for name, var_def in cfg.VARIABLES.items():
            print(f"  {var_def['cds_name']}")
            download_one(client, name, var_def, year)

    print("\nDownload complete.")


if __name__ == "__main__":
    main()
