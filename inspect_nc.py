"""
Utility: Inspect NetCDF files -- dimensions, variables, time range, statistics.

Usage:
    python inspect_nc.py <file.nc>            # Inspect one file
    python inspect_nc.py <directory>           # All .nc files in directory
    python inspect_nc.py <file.nc> --detail    # Include data statistics
"""
import argparse
import os
import sys

import numpy as np
import xarray as xr


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024


def inspect_file(path, detail=False):
    """Print a compact summary of a single NetCDF file."""
    size = _fmt_size(os.path.getsize(path))
    print(f"\n{'=' * 70}")
    print(f"  {os.path.basename(path)}  ({size})")
    print(f"  {os.path.abspath(path)}")
    print(f"{'=' * 70}")

    ds = xr.open_dataset(path)

    # ---- Dimensions ----
    print("\nDimensions:")
    for name, sz in ds.dims.items():
        print(f"  {name:<20} {sz}")

    # ---- Coordinates ----
    print("\nCoordinates:")
    for name, coord in ds.coords.items():
        extra = ""
        # Time coordinates
        if "time" in name.lower() and coord.size > 0:
            t = coord.values
            extra = f"  [{t[0]} .. {t[-1]}]  ({coord.size} steps)"
        elif coord.dtype.kind in "iufc" and coord.size > 0:
            vals = coord.values
            if coord.size > 1:
                extra = f"  [{vals.min():.4f} .. {vals.max():.4f}]"
            else:
                extra = f"  [{vals.item():.4f}]"
        print(
            f"  {name:<20} {str(coord.dtype):<10} "
            f"{str(coord.shape):<15}{extra}"
        )

    # ---- Data variables ----
    print("\nData Variables:")
    for name, var in ds.data_vars.items():
        unit = var.attrs.get("units", "")
        long = var.attrs.get("long_name", "")
        print(
            f"  {name:<15} {str(var.dtype):<10} "
            f"{str(var.shape):<25} {unit:<15} {long}"
        )
        if detail and var.dtype.kind in "iufc" and var.size > 0:
            _print_stats(var)

    # ---- Spatial resolution ----
    for lat_key in ("latitude", "lat"):
        for lon_key in ("longitude", "lon"):
            if lat_key in ds.coords and lon_key in ds.coords:
                lats = ds[lat_key].values
                lons = ds[lon_key].values
                if len(lats) > 1 and len(lons) > 1:
                    dlat = np.mean(np.abs(np.diff(lats)))
                    dlon = np.mean(np.abs(np.diff(lons)))
                    print(
                        f"\nSpatial resolution: "
                        f"{dlat:.4f} deg lat x {dlon:.4f} deg lon"
                    )
                break

    # ---- Global attributes ----
    if ds.attrs:
        print("\nGlobal attributes:")
        for k, v in ds.attrs.items():
            s = str(v)
            if len(s) > 60:
                s = s[:57] + "..."
            print(f"  {k}: {s}")

    ds.close()


def _print_stats(var):
    """Print min/max/mean/std for a numeric variable."""
    try:
        vals = var.values
        finite = vals[np.isfinite(vals)]
        if finite.size > 0:
            print(f"    {'min':>8}: {finite.min():.6g}")
            print(f"    {'max':>8}: {finite.max():.6g}")
            print(f"    {'mean':>8}: {finite.mean():.6g}")
            print(f"    {'std':>8}: {finite.std():.6g}")
        nan_frac = (vals.size - finite.size) / vals.size
        if nan_frac > 0:
            print(f"    {'NaN%':>8}: {nan_frac:.1%}")
    except Exception as exc:
        print(f"    (stats error: {exc})")


def main():
    parser = argparse.ArgumentParser(description="Inspect NetCDF files")
    parser.add_argument("path", help="NetCDF file or directory")
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show data statistics for each variable",
    )
    args = parser.parse_args()

    if os.path.isdir(args.path):
        files = sorted(
            f
            for f in os.listdir(args.path)
            if f.endswith((".nc", ".nc4"))
        )
        if not files:
            print(f"No .nc files in {args.path}")
            sys.exit(1)
        for f in files:
            inspect_file(os.path.join(args.path, f), args.detail)
    elif os.path.isfile(args.path):
        inspect_file(args.path, args.detail)
    else:
        print(f"Not found: {args.path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
