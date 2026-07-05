#!/usr/bin/env python3
"""
Compare SBE37 hex and CNV file data using Plotly.

Usage:
    python compare_hex_cnv.py <hex_file> <cnv_file>
    python compare_hex_cnv.py data/proc_calib/msm142_2026/cal_dip/castM4/14626_cal_dip_data.hex data/proc_calib/msm142_2026/cal_dip/castM4/14626_cal_dip_data_time.cnv
"""

import sys
import argparse
from pathlib import Path
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from caldip.readers import sbe37_hex_reader, load_microcat_data


def main():
    parser = argparse.ArgumentParser(
        description="Compare SBE37 hex and CNV file data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python compare_hex_cnv.py file.hex file.cnv
  python compare_hex_cnv.py data/proc_calib/msm142_2026/cal_dip/castM4/14626_cal_dip_data.hex data/proc_calib/msm142_2026/cal_dip/castM4/14626_cal_dip_data_time.cnv
        """,
    )

    parser.add_argument("hex_file", help="Path to SBE37 hex file")
    parser.add_argument("cnv_file", help="Path to CNV file")
    parser.add_argument(
        "--output",
        help="Output HTML file (default: comparison_plot.html)",
        default="comparison_plot.html",
    )

    args = parser.parse_args()

    try:
        print(f"Loading hex file: {args.hex_file}")
        ds_hex = sbe37_hex_reader(args.hex_file)

        print(f"Loading CNV file: {args.cnv_file}")
        ds_cnv = load_microcat_data(args.cnv_file)

        print("Creating comparison plot...")

        # Create subplot figure with 3 rows
        fig = make_subplots(
            rows=3,
            cols=1,
            subplot_titles=["Temperature", "Conductivity", "Pressure"],
            vertical_spacing=0.08,
            shared_xaxes=True,
        )

        # Temperature plot
        fig.add_trace(
            go.Scatter(
                x=ds_hex.time.values,
                y=ds_hex.temp.values,
                name="Hex Temperature",
                line=dict(color="red", width=2),
                mode="lines",
            ),
            row=1,
            col=1,
        )

        # Find temperature variable in CNV (tv290C)
        temp_var = None
        for var in ds_cnv.data_vars:
            if "tv290c" in var.lower() or "t090c" in var.lower():
                temp_var = var
                break

        if temp_var:
            fig.add_trace(
                go.Scatter(
                    x=ds_cnv.time.values,
                    y=ds_cnv[temp_var].values,
                    name="CNV Temperature",
                    line=dict(color="black", width=2, dash="dash"),
                    mode="lines",
                ),
                row=1,
                col=1,
            )

        # Conductivity plot
        fig.add_trace(
            go.Scatter(
                x=ds_hex.time.values,
                y=ds_hex.cond.values,
                name="Hex Conductivity",
                line=dict(color="blue", width=2),
                mode="lines",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

        # Find conductivity variable in CNV (cond0mS/cm)
        cond_var = None
        for var in ds_cnv.data_vars:
            if "cond" in var.lower() and ("ms" in var.lower() or "mscm" in var.lower()):
                cond_var = var
                break

        if cond_var:
            fig.add_trace(
                go.Scatter(
                    x=ds_cnv.time.values,
                    y=ds_cnv[cond_var].values,
                    name="CNV Conductivity",
                    line=dict(color="black", width=2, dash="dash"),
                    mode="lines",
                    showlegend=False,
                ),
                row=2,
                col=1,
            )

        # Pressure plot
        fig.add_trace(
            go.Scatter(
                x=ds_hex.time.values,
                y=ds_hex.press.values,
                name="Hex Pressure",
                line=dict(color="green", width=2),
                mode="lines",
                showlegend=False,
            ),
            row=3,
            col=1,
        )

        # Find pressure variable in CNV (prdM)
        press_var = None
        for var in ds_cnv.data_vars:
            if "prdm" in var.lower() or ("pres" in var.lower() and "db" in var.lower()):
                press_var = var
                break

        if press_var:
            fig.add_trace(
                go.Scatter(
                    x=ds_cnv.time.values,
                    y=ds_cnv[press_var].values,
                    name="CNV Pressure",
                    line=dict(color="black", width=2, dash="dash"),
                    mode="lines",
                    showlegend=False,
                ),
                row=3,
                col=1,
            )

        # Update layout
        fig.update_layout(
            title=f"SBE37 Hex vs CNV Comparison<br><sub>{Path(args.hex_file).name} vs {Path(args.cnv_file).name}</sub>",
            height=800,
            showlegend=True,
            legend=dict(x=0.7, y=0.98),
            hovermode="x unified",
        )

        # Update y-axis labels
        fig.update_yaxes(title_text="Temperature (°C)", row=1, col=1)
        fig.update_yaxes(title_text="Conductivity (mS/cm)", row=2, col=1)
        fig.update_yaxes(title_text="Pressure (dbar)", row=3, col=1)

        # Update x-axis label only for bottom plot
        fig.update_xaxes(title_text="Time (UTC)", row=3, col=1)

        # Save plot
        fig.write_html(args.output)
        print(f"Plot saved to: {args.output}")

        # Print summary statistics
        print("\n" + "=" * 60)
        print("DATA COMPARISON SUMMARY")
        print("=" * 60)

        print(f"\nHex file: {ds_hex.sizes['time']} samples")
        print(f"CNV file: {ds_cnv.sizes['time']} samples")

        print("\nTime ranges:")
        print(f"Hex: {ds_hex.time.values[0]} to {ds_hex.time.values[-1]}")
        print(f"CNV: {ds_cnv.time.values[0]} to {ds_cnv.time.values[-1]}")

        print("\nVariable mapping:")
        print(f"Temperature - Hex: 'temp', CNV: '{temp_var}'")
        print(f"Conductivity - Hex: 'cond', CNV: '{cond_var}'")
        print(f"Pressure - Hex: 'press', CNV: '{press_var}'")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
