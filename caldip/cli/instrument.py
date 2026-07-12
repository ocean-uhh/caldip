"""caldip instrument — process a single instrument to NetCDF and/or HTML plot."""

import sys
import argparse
import pandas as pd
from pathlib import Path

from caldip.readers import (
    find_config_file,
    load_config,
    load_instrument_data,
    resolve_data_dir,
    _normalize_instrument_vars,
)
from caldip._writers import save_instrument_nc


def build_parser(subparsers=None):
    kwargs = dict(
        help="load and save one instrument to _raw.nc and/or _use.nc",
        description=(
            "Load, normalize, and save one instrument from a cast config to NetCDF.\n\n"
            "Produces:\n"
            "  caldip_{type}_{serial}_raw.nc  — full normalized data (clock offset applied)\n"
            "  caldip_{type}_{serial}_use.nc  — trimmed to deployment_time / recovery_time"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  caldip instrument castB1/castB1.caldip.yaml --serial 7507
  caldip instrument castB1/castB1.caldip.yaml --serial 240230 --output use
  caldip instrument castB1/castB1.caldip.yaml --serial 26202 --output raw -o exports/
        """,
    )
    if subparsers is not None:
        parser = subparsers.add_parser("instrument", **kwargs)
    else:
        parser = argparse.ArgumentParser(prog="caldip instrument", **kwargs)

    parser.add_argument(
        "config_path",
        help="Path to .caldip.yaml config file or directory containing one",
    )
    parser.add_argument(
        "--serial",
        "-s",
        required=True,
        help="Serial number of the instrument to process (as it appears in the YAML)",
    )
    parser.add_argument(
        "--output",
        choices=["raw", "use", "both"],
        default="both",
        help=(
            "Which NetCDF variant(s) to save: 'raw' (full data), "
            "'use' (trimmed to deployment window), or 'both' (default)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Directory to write output files (default: same directory as source data)",
    )
    parser.add_argument("--data-dir", help="Override data directory from config")
    parser.add_argument(
        "--format",
        default="nc,html",
        help=(
            "Comma-separated output formats to produce: "
            "'nc' (save NetCDF), 'html' (save time-series plot). "
            "Default: nc,html"
        ),
    )
    return parser


_PLOT_VAR_LABELS = {
    "temperature": "Temperature (°C)",
    "conductivity": "Conductivity (mS/cm)",
    "pressure": "Pressure (dbar)",
}
_PLOT_VARS = ["pressure", "temperature", "conductivity"]


def _make_instrument_plot(dataset, deploy_ds, config, label, serial):
    """Return a Plotly figure of the instrument time series.

    dataset    — full normalized dataset (raw, clock-offset applied)
    deploy_ds  — deployment-window subset (or None if unavailable)
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    available = set(dataset.data_vars)
    plot_vars = [v for v in _PLOT_VARS if v in available]
    if not plot_vars:
        return None

    n_rows = len(plot_vars)
    fig = make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        subplot_titles=[_PLOT_VAR_LABELS.get(v, v) for v in plot_vars],
        vertical_spacing=0.06,
    )

    t_full = dataset.time.values
    t_dep = deploy_ds.time.values if deploy_ds is not None else None

    for i, var in enumerate(plot_vars, 1):
        # Full record in light gray
        fig.add_trace(
            go.Scatter(
                x=t_full,
                y=dataset[var].values.astype(float),
                mode="lines",
                name="full record",
                legendgroup="full",
                showlegend=(i == 1),
                line=dict(color="lightgray", width=1),
            ),
            row=i,
            col=1,
        )
        # Deployment window in color
        if deploy_ds is not None and var in deploy_ds.data_vars:
            fig.add_trace(
                go.Scatter(
                    x=t_dep,
                    y=deploy_ds[var].values.astype(float),
                    mode="lines",
                    name="deployment window",
                    legendgroup="deploy",
                    showlegend=(i == 1),
                    line=dict(color="steelblue", width=1.5),
                ),
                row=i,
                col=1,
            )
        if var == "pressure":
            fig.update_yaxes(autorange="reversed", row=i, col=1)
        fig.update_yaxes(title_text=_PLOT_VAR_LABELS.get(var, var), row=i, col=1)

    n = len(t_full)
    start_str = str(pd.to_datetime(t_full[0]))[:16] if n > 0 else "?"
    end_str = str(pd.to_datetime(t_full[-1]))[:16] if n > 0 else "?"
    fig.update_layout(
        title=f"{label} {serial} — {n} samples | {start_str} – {end_str}",
        height=max(300, 200 * n_rows + 80),
        legend=dict(orientation="v", x=1.01, xanchor="left"),
    )
    return fig


def run(args):
    """Execute the instrument subcommand. Returns exit code."""
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

    # Find the requested instrument entry by serial
    target_serial = str(args.serial)
    instrument_cfg = None
    for inst in config.get("instruments", []):
        if str(inst.get("serial", "")) == target_serial:
            instrument_cfg = inst
            break

    if instrument_cfg is None:
        serials = [str(i.get("serial", "?")) for i in config.get("instruments", [])]
        print(f"Error: Serial '{target_serial}' not found in config.")
        print(f"  Available serials: {', '.join(serials)}")
        return 1

    data_dir = resolve_data_dir(config_file, config, args.data_dir)
    filename = instrument_cfg.get("filename", "")
    if not filename:
        print(f"Error: No filename for serial {target_serial} in config")
        return 1

    file_path = data_dir / filename
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        return 1

    file_type = instrument_cfg["file_type"]
    instr_type = instrument_cfg.get("instrument", file_type).lower()
    label = instrument_cfg.get("label", instr_type)
    clock_offset = instrument_cfg.get("clock_offset", 0)

    print(f"\nProcessing {label} {target_serial} ({file_type.upper()}) ...")

    # Load and normalize
    try:
        load_kwargs = {}
        if "header_file" in instrument_cfg:
            load_kwargs["header_file"] = str(data_dir / instrument_cfg["header_file"])

        dataset = load_instrument_data(file_path, file_type, **load_kwargs)
        dataset = _normalize_instrument_vars(dataset)
        print(f"  Loaded: {len(dataset.time)} samples")
        print(f"  Variables: {sorted(dataset.data_vars)}")
    except Exception as e:
        print(f"  Error loading: {e}")
        return 1

    # Apply clock offset
    if clock_offset:
        print(f"  Clock offset: {clock_offset:+.0f} s")
        dataset = dataset.assign_coords(
            time=dataset.time + pd.Timedelta(seconds=clock_offset)
        )

    formats = {f.strip().lower() for f in args.format.split(",")}

    output_dir = Path(args.output_dir) if args.output_dir else data_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"caldip_{instr_type}_{target_serial}"

    # Build the deployment-window subset (needed for nc _use and for the html plot)
    deploy = config.get("deployment_time")
    recover = config.get("recovery_time")
    deploy_ds = None
    if deploy and recover:
        deploy_np = pd.to_datetime(deploy).to_datetime64()
        recover_np = pd.to_datetime(recover).to_datetime64()
        mask = (dataset.time.values >= deploy_np) & (dataset.time.values <= recover_np)
        if mask.any():
            deploy_ds = dataset.sel(time=mask)

    if "nc" in formats:
        want_raw = args.output in ("raw", "both")
        want_use = args.output in ("use", "both")

        if want_raw:
            nc_path = output_dir / f"{stem}_raw.nc"
            save_instrument_nc(dataset, nc_path, str(nc_path.name))

        if want_use:
            if not (deploy and recover):
                print(
                    "  Warning: deployment_time / recovery_time not in config — skipping _use.nc"
                )
            elif deploy_ds is None:
                print(f"  Warning: No data in deployment window {deploy} – {recover}")
            else:
                nc_path = output_dir / f"{stem}_use.nc"
                save_instrument_nc(deploy_ds, nc_path, str(nc_path.name))

    if "html" in formats:
        try:
            import plotly  # noqa: F401

            fig = _make_instrument_plot(
                dataset, deploy_ds, config, label, target_serial
            )
            if fig is not None:
                plot_path = output_dir / f"{stem}_plot.html"
                fig.write_html(str(plot_path))
                print(f"  Plot saved: {plot_path}")
        except ImportError:
            print("  plotly not available — skipping plot")
        except Exception as e:
            print(f"  Failed to generate plot: {e}")
            import traceback

            traceback.print_exc()

    print("\nDone.")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
