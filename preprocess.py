"""
Step 2: Preprocess ERA5 data -- resample hourly to 3-hourly.

- Cumulative variables (precip, radiation): converts accumulated values
  to 3-hour totals.  Automatically detects whether the CDS delivered
  cumulative-from-midnight data or already-de-accumulated hourly data.
- Instantaneous variables (T, P, wind, humidity): subsamples every 3 h.

Handles both full-year files and split (Jan-Nov + Dec) files automatically.

Usage:
    python preprocess.py
    python preprocess.py --years 2020 2021
    python preprocess.py --vars precipitation solar_radiation
"""
import argparse
import os

import numpy as np
import pandas as pd
import xarray as xr

import config as cfg


# ── Helpers ──────────────────────────────────────────────────


def _time_dim(ds):
    """Return the name of the time dimension."""
    for name in ("valid_time", "time"):
        if name in ds.dims:
            return name
    raise ValueError("No time dimension found in dataset")


def _data_var(ds):
    """Return the (last) data variable name."""
    names = list(ds.data_vars)
    if not names:
        raise ValueError("No data variables in dataset")
    return names[-1]


def _detect_cumulative(ds, dvar, tdim):
    """Auto-detect whether an accumulated variable is stored as cumulative
    (monotonically increasing from forecast init) or as independent
    per-hour totals (already de-accumulated by the CDS).

    Strategy: compute the spatial mean over hours 3-21 of the first day.
    Cumulative data increases monotonically; per-hour data fluctuates
    (e.g. solar radiation drops to zero at night, then rises again).

    Returns True if the data appears cumulative, False if per-hour.
    """
    n = min(22, ds[tdim].size)
    if n < 6:
        # Too few time steps to detect; assume cumulative (safer)
        return True

    subset = ds[dvar].isel({tdim: slice(3, n)})
    # Average over all spatial dimensions to get a 1D time series
    spatial_dims = [d for d in subset.dims if d != tdim]
    means = subset.mean(dim=spatial_dims).values

    diffs = np.diff(means)
    is_monotonic = np.all(diffs >= -1e-10)

    return is_monotonic


def _cumulative_to_increments(values):
    """Convert cumulative values to per-step increments.

    Handles reset points (where accumulation restarts) at ANY hour --
    works for ERA5-Land (resets at 00:00 and 12:00 UTC) and ERA5
    single-levels (resets at 06:00 and 18:00 UTC).

    Reset detection: at each pixel, if value[i] < value[i-1], a reset
    occurred and value[i] itself is the increment since the reset.
    """
    inc = np.empty_like(values)
    # First time step: if it looks like a leftover from a previous
    # forecast (much larger than the next step), approximate with
    # the next step's value; otherwise keep as-is.
    if len(values) > 1:
        mean_0 = np.nanmean(values[0])
        mean_1 = np.nanmean(values[1])
        if mean_0 > mean_1 * 3 and mean_1 > 0:
            # values[0] is a big leftover → approximate
            inc[0] = values[1]
        else:
            inc[0] = values[0]
    else:
        inc[0] = values[0]

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        # Per-pixel: negative diff → reset → use value directly
        inc[i] = np.where(diff < 0, values[i], diff)

    return inc


# ── Load / merge ─────────────────────────────────────────────


def _load(name, year):
    """Load a raw NetCDF file, merging a separate December file if present.

    Some downloads split a year into Jan-Nov + Dec files.  If a file named
    ``{name}_{year}_12.nc`` exists alongside the main file, it is
    concatenated automatically.
    """
    raw_dir = cfg.ERA5_RAW_DIR
    main_path = os.path.join(raw_dir, f"{name}_{year}.nc")
    dec_path = os.path.join(raw_dir, f"{name}_{year}_12.nc")

    if not os.path.exists(main_path):
        raise FileNotFoundError(main_path)

    ds = xr.open_dataset(main_path)
    tdim = _time_dim(ds)

    # Merge December file if it exists
    if os.path.exists(dec_path):
        print(f"    merging December file")
        ds_dec = xr.open_dataset(dec_path)
        for coord in ("expver",):
            if coord in ds.coords:
                ds = ds.drop_vars(coord)
            if coord in ds_dec.coords:
                ds_dec = ds_dec.drop_vars(coord)
        ds = xr.concat([ds, ds_dec], dim=tdim)
        ds_dec.close()

    return ds, tdim


# ── Core processing ─────────────────────────────────────────


def process(name, var_def, year):
    """Preprocess one variable for one year."""
    out_dir = cfg.ERA5_PROCESSED_DIR
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{name}_{year}_processed_3h.nc")

    if os.path.exists(out_path):
        print(f"  [skip] {os.path.basename(out_path)}")
        return

    print(f"  {name}")
    ds, tdim = _load(name, year)
    dvar = _data_var(ds)

    # Detect time resolution
    times = ds[tdim].values
    res_h = int(round(np.median(np.diff(times) / np.timedelta64(1, "h"))))
    print(f"    resolution={res_h}h  var={dvar}")

    if var_def["cumulative"]:
        # ---- Accumulated variable ----
        is_cumul = _detect_cumulative(ds, dvar, tdim)

        if is_cumul:
            # Data is cumulative from forecast init → compute increments
            print(f"    detected: CUMULATIVE (from forecast init)")
            ds[dvar].values = _cumulative_to_increments(ds[dvar].values)
        else:
            # Data is already per-hour (CDS de-accumulated)
            print(f"    detected: PER-HOUR (already de-accumulated)")
            # No differencing needed; just aggregate below

        # Aggregate to 3-hourly sums
        if res_h == 1:
            ds = ds.resample({tdim: "3h"}).sum()
        # If already 3h, values are already 3h totals (no action)

        # Drop residual expver coordinate
        if "expver" in ds.coords:
            ds = ds.drop_vars("expver")
    else:
        # ---- Instantaneous variable: subsample ----
        if res_h == 1:
            ds = ds.isel({tdim: slice(0, None, 3)})

    # Ensure time coverage extends to Dec-31 21:00
    last = pd.to_datetime(ds[tdim].values[-1])
    year_end = pd.Timestamp(f"{year}-12-31 21:00:00")
    if last < year_end:
        print(f"    extending to {year_end}")
        tail_data = ds[dvar].isel({tdim: -1}).values[np.newaxis, ...]
        new_time = np.array([year_end.to_datetime64()])
        coords = {}
        for k, v in ds.coords.items():
            if k == tdim:
                coords[k] = np.concatenate([v.values, new_time])
            else:
                coords[k] = v.values
        ds = xr.Dataset(
            {dvar: (ds[dvar].dims, np.concatenate([ds[dvar].values, tail_data], axis=0))},
            coords=coords,
        )

    print(f"    -> {os.path.basename(out_path)}")
    ds.to_netcdf(out_path)
    ds.close()


# ── CLI ──────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Preprocess ERA5 data: hourly -> 3-hourly"
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=list(range(cfg.START_YEAR, cfg.END_YEAR + 1)),
        help="Years to process (default: range from config)",
    )
    parser.add_argument(
        "--vars",
        nargs="+",
        default=None,
        help="Variable keys to process (default: all in config)",
    )
    args = parser.parse_args()

    names = args.vars or list(cfg.VARIABLES.keys())

    for year in sorted(args.years):
        print(f"\nYear {year}")
        for name in names:
            if name not in cfg.VARIABLES:
                print(f"  [warn] unknown variable: {name}")
                continue
            try:
                process(name, cfg.VARIABLES[name], year)
            except Exception as exc:
                print(f"  [ERROR] {name}: {exc}")

    print("\nPreprocessing complete.")


if __name__ == "__main__":
    main()
