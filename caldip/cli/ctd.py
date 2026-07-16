"""caldip ctd — pre-process CTD reference data and save as NetCDF."""

import sys
import argparse
import numpy as np
from pathlib import Path

from caldip.readers import (
    find_config_file,
    load_config,
    load_instrument_data,
    resolve_data_dir,
    _normalize_ctd_vars,
    _wild_edit_ctd,
    _resample_1hz,
)


def build_parser(subparsers=None):
    kwargs = dict(
        help="pre-process CTD file: normalize, wild-edit, 1 Hz resample, save NetCDF + plot",
        description="Pre-process CTD reference data: normalize, wild-edit, resample to 1 Hz, plot, and save as NetCDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  caldip ctd data/proc_calib/odb_2026/cal_dip/castB1/castB1.caldip.yaml
  caldip ctd castB1/castB1.caldip.yaml -o outputs/
        """,
    )
    if subparsers is not None:
        parser = subparsers.add_parser("ctd", **kwargs)
    else:
        parser = argparse.ArgumentParser(prog="caldip ctd", **kwargs)

    parser.add_argument(
        "config_path",
        help="Path to .caldip.yaml config file or directory containing config",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help=(
            "Directory to save the HTML plot (default: same directory as the CTD file). "
            "NetCDF output is always written next to the CTD file so it can be found on reload."
        ),
    )
    parser.add_argument("--data-dir", help="Override data directory from config")
    parser.add_argument(
        "--format",
        default="nc,html",
        help=(
            "Comma-separated output formats to produce: "
            "'nc' (save processed NetCDF), 'html' (save comparison plot). "
            "Default: nc,html"
        ),
    )
    return parser


def _count_masked(ds_raw, ds_edited, var):
    """Count samples that were finite in ds_raw but NaN in ds_edited for var."""
    if var not in ds_raw.data_vars or var not in ds_edited.data_vars:
        return 0
    raw_v = ds_raw[var].values.astype(float)
    edit_v = ds_edited[var].values.astype(float)
    return int(np.sum(~np.isnan(raw_v) & np.isnan(edit_v)))


def _make_comparison_plot(
    ds_raw, ds_edited, ds_processed, ctd_name, n_masked_1, n_masked_2
):
    """Return a Plotly figure comparing raw vs wild-edit+1Hz processed CTD data.

    Panel order: Pressure, Temperature, Conductivity (if present), Salinity (if present).

    Colours
    -------
    Primary raw          thin black  (opacity 0.35)
    Primary 1 Hz         thick black (width 3)
    Secondary raw        thin gray   (opacity 0.35)
    Secondary 1 Hz       thick gray  (width 2)
    Primary masked       red ×
    Secondary masked     blue ×

    Parameters
    ----------
    ds_raw       : normalized, pre-wild-edit (full resolution)
    ds_edited    : post-wild-edit, pre-resample (full resolution, NaNs inserted)
    ds_processed : post-wild-edit + 1 Hz median (saved to NetCDF)
    n_masked_1   : number of samples masked for primary sensor
    n_masked_2   : number of samples masked for secondary sensor (0 if no secondary)
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    has_t2 = "temperature_2" in ds_raw.data_vars
    has_c2 = "conductivity_2" in ds_raw.data_vars
    has_cond = "conductivity" in ds_raw.data_vars
    has_sal = "salinity" in ds_raw.data_vars

    # Panel order: P, T, C, S
    panel_titles = ["Pressure (dbar)", "Temperature (°C)"]
    if has_cond:
        panel_titles.append("Conductivity (mS/cm)")
    if has_sal:
        panel_titles.append("Salinity (PSU)")

    n_rows = len(panel_titles)
    fig = make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        subplot_titles=panel_titles,
        vertical_spacing=0.06,
    )

    P_ROW = 1
    T_ROW = 2
    C_ROW = 3 if has_cond else None
    S_ROW = (4 if has_cond else 3) if has_sal else None

    t_raw = ds_raw.time.values
    t_proc = ds_processed.time.values

    # Track which legend groups have already been shown
    _shown = set()

    def _add(
        row,
        x,
        y,
        name,
        group,
        mode="lines",
        color="black",
        width=1,
        opacity=1.0,
        marker_sym="x",
        marker_size=6,
    ):
        show = group not in _shown
        if show:
            _shown.add(group)
        kw = dict(x=x, y=y, mode=mode, name=name, legendgroup=group, showlegend=show)
        if mode == "lines":
            kw["line"] = dict(color=color, width=width)
            kw["opacity"] = opacity
        else:
            kw["marker"] = dict(color=color, size=marker_size, symbol=marker_sym)
        fig.add_trace(go.Scatter(**kw), row=row, col=1)

    def raw_primary(row, var):
        if var not in ds_raw.data_vars:
            return
        _add(
            row,
            t_raw,
            ds_raw[var].values.astype(float),
            name="raw",
            group="raw_primary",
            color="black",
            width=1,
            opacity=0.35,
        )

    def raw_secondary(row, var):
        if var not in ds_raw.data_vars:
            return
        _add(
            row,
            t_raw,
            ds_raw[var].values.astype(float),
            name="raw (2nd)",
            group="raw_secondary",
            color="gray",
            width=1,
            opacity=0.35,
        )

    def proc_primary(row, var):
        if var not in ds_processed.data_vars:
            return
        _add(
            row,
            t_proc,
            ds_processed[var].values,
            name="1 Hz",
            group="proc_primary",
            color="black",
            width=3,
        )

    def proc_secondary(row, var):
        if var not in ds_processed.data_vars:
            return
        _add(
            row,
            t_proc,
            ds_processed[var].values,
            name="1 Hz (2nd)",
            group="proc_secondary",
            color="gray",
            width=2,
        )

    def masked_primary(row, var):
        if var not in ds_raw.data_vars or var not in ds_edited.data_vars:
            return
        rv = ds_raw[var].values.astype(float)
        ev = ds_edited[var].values.astype(float)
        m = ~np.isnan(rv) & np.isnan(ev)
        if not np.any(m):
            return
        _add(
            row,
            t_raw[m],
            rv[m],
            name="masked",
            group="masked_primary",
            mode="markers",
            color="red",
            marker_sym="x",
        )

    def masked_secondary(row, var):
        if var not in ds_raw.data_vars or var not in ds_edited.data_vars:
            return
        rv = ds_raw[var].values.astype(float)
        ev = ds_edited[var].values.astype(float)
        m = ~np.isnan(rv) & np.isnan(ev)
        if not np.any(m):
            return
        _add(
            row,
            t_raw[m],
            rv[m],
            name="masked (2nd)",
            group="masked_secondary",
            mode="markers",
            color="blue",
            marker_sym="x",
        )

    # ---- Pressure (primary only) ----
    raw_primary(P_ROW, "pressure")
    masked_primary(P_ROW, "pressure")
    proc_primary(P_ROW, "pressure")

    # ---- Temperature ----
    raw_primary(T_ROW, "temperature")
    raw_secondary(T_ROW, "temperature_2")
    masked_primary(T_ROW, "temperature")
    masked_secondary(T_ROW, "temperature_2")
    proc_primary(T_ROW, "temperature")
    proc_secondary(T_ROW, "temperature_2")

    # ---- Conductivity ----
    if has_cond and C_ROW:
        raw_primary(C_ROW, "conductivity")
        raw_secondary(C_ROW, "conductivity_2")
        masked_primary(C_ROW, "conductivity")
        masked_secondary(C_ROW, "conductivity_2")
        proc_primary(C_ROW, "conductivity")
        proc_secondary(C_ROW, "conductivity_2")

    # ---- Salinity ----
    if has_sal and S_ROW:
        raw_primary(S_ROW, "salinity")
        masked_primary(S_ROW, "salinity")
        proc_primary(S_ROW, "salinity")

    # ---- Axis labels ----
    fig.update_yaxes(
        title_text="Pressure (dbar)", autorange="reversed", row=P_ROW, col=1
    )
    fig.update_yaxes(title_text="Temp (°C)", row=T_ROW, col=1)
    if has_cond and C_ROW:
        fig.update_yaxes(title_text="Cond (mS/cm)", row=C_ROW, col=1)
    if has_sal and S_ROW:
        fig.update_yaxes(title_text="Salinity", row=S_ROW, col=1)

    # ---- Title ----
    masked_parts = [f"{n_masked_1} masked (primary)"]
    if has_t2 or has_c2:
        masked_parts.append(f"{n_masked_2} masked (secondary)")
    title = (
        f"CTD {ctd_name} — raw vs wild-edit + 1 Hz median "
        f"| {len(ds_processed.time)} samples | {', '.join(masked_parts)}"
    )

    fig.update_layout(
        title=title,
        height=250 * n_rows + 100,
        legend=dict(orientation="v", x=1.01, xanchor="left"),
    )
    return fig


def run(args):
    """Execute the ctd subcommand. Returns exit code."""
    config_file = find_config_file(args.config_path)
    if not config_file:
        print(f"Error: No caldip configuration file found in {args.config_path}")
        return 1

    print(f"Using config file: {config_file}")

    try:
        config = load_config(config_file)
        print(f"Loaded config for: {config.get('name', 'Unknown')}")
    except Exception as e:
        print(f"Error loading config file: {e}")
        return 1

    ctd_file = config.get("ctd_file")
    if not ctd_file:
        print("Error: No ctd_file specified in config")
        return 1

    data_dir = resolve_data_dir(config_file, config, args.data_dir)
    ctd_path = data_dir / ctd_file
    if not ctd_path.exists():
        print(f"Error: CTD file not found: {ctd_path}")
        return 1

    print(f"\nProcessing CTD file: {ctd_path.name}")

    try:
        # NOTE: reads 'ctd_sensor' (singular). Old YAMLs using 'ctd_sensors' will
        # silently default to 1 — fix by renaming the key in the YAML.
        ctd_sensor = int(config.get("ctd_sensor", 1))
        ds_raw = load_instrument_data(ctd_path, "ctd-cnv")
        ds_raw = _normalize_ctd_vars(ds_raw, ctd_sensor=ctd_sensor)
        ds_edited = _wild_edit_ctd(ds_raw, config)
        ds_processed = _resample_1hz(ds_edited)
    except Exception as e:
        print(f"Error processing CTD data: {e}")
        return 1

    formats = {f.strip().lower() for f in args.format.split(",")}

    # Count masked samples for primary (temperature) and secondary (temperature_2)
    n_masked_1 = _count_masked(ds_raw, ds_edited, "temperature")
    n_masked_2 = _count_masked(ds_raw, ds_edited, "temperature_2")

    nc_path = ctd_path.with_suffix(".nc")

    if "nc" in formats:
        try:
            save_ds = ds_processed.copy()
            save_ds.attrs = {k: v for k, v in save_ds.attrs.items() if v is not None}
            save_ds.to_netcdf(nc_path)
            print(f"  Saved: {nc_path}")
        except Exception as e:
            print(f"  Failed to save NetCDF: {e}")
            return 1

    if "html" in formats:
        try:
            import plotly  # noqa: F401

            output_dir = Path(args.output_dir) if args.output_dir else ctd_path.parent
            output_dir.mkdir(parents=True, exist_ok=True)
            ctd_name = ctd_path.stem
            fig = _make_comparison_plot(
                ds_raw, ds_edited, ds_processed, ctd_name, n_masked_1, n_masked_2
            )
            plot_path = output_dir / f"{ctd_name}_ctd_plot.html"
            fig.write_html(str(plot_path))
            print(f"  Plot saved: {plot_path}")
        except ImportError:
            print("  plotly not available — skipping plot")
        except Exception as e:
            print(f"  Failed to generate plot: {e}")
            import traceback

            traceback.print_exc()

    print(f"\nDone. CTD data ready at: {nc_path}")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
