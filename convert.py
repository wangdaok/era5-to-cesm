"""
Step 3: Convert preprocessed ERA5 data to CESM atmospheric forcing format.

Reads 3-hourly ERA5 NetCDF files (from Step 2) and produces CESM CLM
forcing files with correct variable names, units, grid, and metadata.

Output per month:
    clmforc.0.1x0.1.prec-YYYY-MM.nc    PRECTmms
    clmforc.0.1x0.1.solar-YYYY-MM.nc   FSDS
    clmforc.0.1x0.1.TPQWL-YYYY-MM.nc   TBOT, PSRF, QBOT, WIND, FLDS

Usage:
    python convert.py
    python convert.py --years 2020 2021
"""
import argparse
import os
from collections import defaultdict

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr

import config as cfg

FILL = -32767.0


# ── Grid construction ────────────────────────────────────────


def _build_grid():
    """Create the target grid arrays for CESM output."""
    lat_s, lat_n = cfg.TARGET_LAT
    lon_w, lon_e = cfg.TARGET_LON
    h = cfg.TARGET_RES / 2

    lon = np.arange(lon_w + h, lon_e, cfg.TARGET_RES)
    lat = np.arange(lat_s + h, lat_n, cfg.TARGET_RES)

    return {
        "lon": lon,
        "lat": lat,
        "lon_2d": np.tile(lon, (len(lat), 1)).astype(np.float32),
        "lat_2d": np.tile(lat[:, np.newaxis], (1, len(lon))).astype(np.float32),
    }


def _cesm_days(year, month):
    """Days in month for the CESM noleap calendar (Feb always 28)."""
    if month == 2:
        return 28
    return pd.Period(f"{year}-{month:02d}").days_in_month


# ── CESM dataset skeleton ───────────────────────────────────


def _base_ds(grid, year, month, n_times):
    """Create a CESM-skeleton Dataset with time, coordinates, and edges."""
    time_vals = (np.arange(n_times) * 0.125 + 0.0625).astype(np.float32)

    ds = xr.Dataset()
    ds["time"] = xr.DataArray(
        time_vals,
        dims="time",
        attrs={
            "long_name": "observation time",
            "units": f"days since {year}-{month:02d}-01 00:00:00",
            "calendar": "noleap",
        },
    )
    ds["LONGXY"] = xr.DataArray(
        grid["lon_2d"],
        dims=("lat", "lon"),
        attrs={
            "long_name": "longitude",
            "units": "degrees_east",
            "mode": "time-invariant",
        },
    )
    ds["LATIXY"] = xr.DataArray(
        grid["lat_2d"],
        dims=("lat", "lon"),
        attrs={
            "long_name": "latitude",
            "units": "degrees_north",
            "mode": "time-invariant",
        },
    )

    for tag, val, compass, unit in [
        ("EDGEE", grid["lon"].max(), "eastern", "degrees_east"),
        ("EDGEW", grid["lon"].min(), "western", "degrees_east"),
        ("EDGES", grid["lat"].min(), "southern", "degrees_north"),
        ("EDGEN", grid["lat"].max(), "northern", "degrees_north"),
    ]:
        ds[tag] = xr.DataArray(
            [val],
            dims="scalar",
            attrs={
                "long_name": f"{compass} edge in atmospheric data",
                "units": unit,
                "mode": "time-invariant",
            },
        )
    return ds


def _save(ds, path, data_vars):
    """Save dataset to NetCDF and fix time attributes with netCDF4."""
    enc = {v: {"_FillValue": FILL, "dtype": "float32"} for v in data_vars}
    enc["time"] = {"dtype": "float32"}
    ds.to_netcdf(path, encoding=enc)

    # xarray sometimes alters time attributes; re-write with netCDF4
    with netCDF4.Dataset(path, "r+") as nc:
        tv = nc.variables["time"]
        tv.long_name = ds["time"].attrs.get("long_name", "")
        tv.units = ds["time"].attrs.get("units", "")
        tv.calendar = ds["time"].attrs.get("calendar", "")


# ── Data processing ─────────────────────────────────────────


def _regrid(data, grid):
    """Bilinear interpolation to target grid."""
    return data.interp(
        latitude=grid["lat"], longitude=grid["lon"], method="linear"
    )


def _process_var(data, var_def, grid):
    """Regrid, convert units, clip to min_value, fill NaN."""
    out = _regrid(data, grid) * var_def["conversion"]
    mv = var_def.get("min_value")
    if mv is not None:
        out = out.where(out >= mv, mv)
    return out.fillna(FILL).values.astype(np.float32)


def _process_wind(u_data, v_data, grid):
    """Compute wind speed from u/v components after regridding."""
    u = _regrid(u_data, grid)
    v = _regrid(v_data, grid)
    speed = np.sqrt(u**2 + v**2)
    speed = speed.where(speed >= 0, 0)
    return speed.fillna(FILL).values.astype(np.float32)


# ── Loader ───────────────────────────────────────────────────


def _find_var(ds, expected):
    """Find a data variable -- try expected name, fall back to last var."""
    if expected in ds:
        return expected
    names = list(ds.data_vars)
    return names[-1] if names else None


def _load_all(year):
    """Load all preprocessed ERA5 files for a given year."""
    ds_map = {}
    for name in cfg.VARIABLES:
        path = os.path.join(
            cfg.ERA5_PROCESSED_DIR, f"{name}_{year}_processed_3h.nc"
        )
        if not os.path.exists(path):
            print(f"    [warn] missing {os.path.basename(path)}")
            continue

        ds = xr.open_dataset(path)

        # Normalise time dimension name
        if "valid_time" in ds.dims:
            ds = ds.rename({"valid_time": "time"})

        # Drop unnecessary coordinates
        for coord in ("number", "expver"):
            if coord in ds.coords:
                ds = ds.drop_vars(coord)

        # Squeeze single pressure level
        if "pressure_level" in ds.dims:
            ds = ds.squeeze("pressure_level")

        ds_map[name] = ds
        print(f"    loaded {name}")

    return ds_map


# ── Year / month conversion loop ────────────────────────────


def _convert_year(year, grid):
    """Convert one year of ERA5 data to CESM forcing files."""
    ds_map = _load_all(year)
    if not ds_map:
        return

    for month in range(1, 13):
        days = _cesm_days(year, month)
        n = days * 8
        times = pd.date_range(
            f"{year}-{month:02d}-01", periods=n, freq="3h"
        )
        print(f"  {year}-{month:02d}  ({days}d, {n} steps)")

        # Collect processed arrays grouped by output file
        groups = defaultdict(dict)  # group -> {cesm_var: (array, info)}

        # ---- Scalar variables (direct ERA5 -> CESM mapping) ----
        for name, var_def in cfg.VARIABLES.items():
            if "cesm_var" not in var_def or name not in ds_map:
                continue

            era5_v = _find_var(ds_map[name], var_def["era5_var"])
            if era5_v is None:
                continue

            try:
                data = ds_map[name][era5_v].sel(time=times)
            except KeyError:
                print(f"    [skip] time mismatch: {name}")
                continue

            arr = _process_var(data, var_def, grid)
            groups[var_def["group"]][var_def["cesm_var"]] = (arr, var_def)

        # ---- Wind speed (computed from u10 + v10) ----
        if "10m_u_wind" in ds_map and "10m_v_wind" in ds_map:
            uv = _find_var(ds_map["10m_u_wind"], "u10")
            vv = _find_var(ds_map["10m_v_wind"], "v10")
            if uv and vv:
                try:
                    u = ds_map["10m_u_wind"][uv].sel(time=times)
                    v = ds_map["10m_v_wind"][vv].sel(time=times)
                    arr = _process_wind(u, v, grid)
                    groups[cfg.WIND["group"]][cfg.WIND["cesm_var"]] = (
                        arr,
                        cfg.WIND,
                    )
                except KeyError:
                    print("    [skip] wind time mismatch")

        # ---- Write output files ----
        for grp, var_dict in groups.items():
            out_ds = _base_ds(grid, year, month, n)
            out_ds.attrs["case_title"] = (
                f"{grp} atmospheric forcing data for CESM"
            )
            out_ds.attrs["source_file"] = (
                f"Converted from ERA5 for {year}-{month:02d}"
            )

            names_written = []
            for cesm_var, (arr, info) in var_dict.items():
                out_ds[cesm_var] = xr.DataArray(
                    arr,
                    dims=("time", "lat", "lon"),
                    attrs={
                        "long_name": info["long_name"],
                        "units": info["units"],
                        "mode": "time-dependent",
                        "missing_value": FILL,
                    },
                )
                names_written.append(cesm_var)

            fname = (
                f"{cfg.CESM_FILE_PREFIX}.{grp}-{year}-{month:02d}.nc"
            )
            fpath = os.path.join(cfg.CESM_OUTPUT_DIR, fname)
            _save(out_ds, fpath, names_written)
            print(f"    -> {fname}  [{', '.join(names_written)}]")

    # Close datasets
    for ds in ds_map.values():
        ds.close()


# ── CLI ──────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Convert preprocessed ERA5 to CESM forcing data"
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=list(range(cfg.START_YEAR, cfg.END_YEAR + 1)),
        help="Years to convert (default: range from config)",
    )
    args = parser.parse_args()

    os.makedirs(cfg.CESM_OUTPUT_DIR, exist_ok=True)
    grid = _build_grid()

    for year in sorted(args.years):
        print(f"\nYear {year}")
        _convert_year(year, grid)

    print("\nConversion complete.")


if __name__ == "__main__":
    main()
