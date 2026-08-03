"""
Universal plotting functions for caldip data visualization.

This module provides plotting functions that work with any instrument type.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional

# Import plotting libraries
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.colors as pc

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# Import caldip functions
import caldip.core as cf

def plot(
    instrument_data: Dict[str, Dict],
    reference_data: Dict[str, Dict],
    config: Optional[Dict] = None,
    title: str = "Caldip Data Comparison",
    show_bottle_stops: bool = True,
    bottle_stop_params: Optional[Dict] = None,
    optional_variables: Optional[list[str] | str] = None,
) -> Optional[object]:
    """
    Create interactive caldip comparison plot with dynamic panels based on requested variables.

    Parameters
    ----------
    instrument_data : dict
        Dictionary of instrument data by serial number:
        {serial: {'data': xr.Dataset, 'config': dict, 'type': str}}
    reference_data : dict
        Dictionary of reference (CTD) data by name:
        {name: {'data': xr.Dataset, 'file': str}}
    config : dict, optional
        Configuration dictionary with deployment_time and recovery_time
    title : str, optional
        Plot title
    show_bottle_stops : bool, optional
        Whether to show bottle stop markers (default True)
    bottle_stop_params : dict, optional
        Parameters for bottle stop detection:
        {'threshold_dbar_per_min': 30.0, 'min_duration_seconds': 120.0}
    optional_variables : list of str or str, optional
        List of base variable names to plot dynamically (e.g., ['pressure', 'temperature', 'conductivity', 'oxygen']).
        Variables with a '_2' suffix (e.g., 'temperature_2') are automatically grouped with their primary panel.

    Returns
    -------
    plotly.graph_objects.Figure or None
        Interactive plot figure, or None if plotly not available
    """
    if not PLOTLY_AVAILABLE:
        print("Plotly not available - cannot create interactive plot")
        return None

    # Default base variables, additional ones appended
    variables = ["pressure", "temperature", "conductivity", "oxygen"]
    if optional_variables is not None:
        if isinstance(optional_variables, str):
            optional_variables = [optional_variables]
        for var in optional_variables:
            variables.append(var)

    # Set default bottle stop parameters
    if bottle_stop_params is None:
        bottle_stop_params = {
            "threshold_dbar_per_min": 30.0,
            "min_duration_seconds": 120.0,
        }

    # Dynamically check which requested base variables exist across data sources
    active_vars = []
    for var in variables:
        found = False
        # Check instrument datasets
        for info in instrument_data.values():
            ds = info["data"]
            if var in ds.data_vars or f"{var}_2" in ds.data_vars or (var == "oxygen" and "oxygen_phase" in ds.data_vars):
                found = True
                break
        # Check reference datasets if not found yet
        if not found:
            for info in reference_data.values():
                ds = info["data"]
                if var in ds.data_vars or f"{var}_2" in ds.data_vars:
                    found = True
                    break
        if found:
            active_vars.append(var)

    if not active_vars:
        print("No matching variables found in datasets to plot.")
        return None

    # Map each active variable to a specific 1-based subplot row index
    var_to_row = {var: idx for idx, var in enumerate(active_vars, start=1)}
    n_rows = len(active_vars)

    # Collect data values for dynamic y-axis range calculations per variable
    var_values = {var: [] for var in active_vars}

    for info in instrument_data.values():
        ds = info["data"]
        for var in active_vars:
            # Gather primary, secondary, and fallback variables
            check_vars = [var, f"{var}_2"]
            if var == "oxygen":
                check_vars.append("oxygen_phase")
            
            for v in check_vars:
                if v in ds.data_vars:
                    vals = ds[v].values[~np.isnan(ds[v].values)]
                    if len(vals) > 0:
                        var_values[var].extend(vals)

    for info in reference_data.values():
        ds = info["data"]
        for var in active_vars:
            check_vars = [var, f"{var}_2"]
            if var == "oxygen":
                check_vars.append("oxygen_phase")
                
            for v in check_vars:
                if v in ds.data_vars:
                    vals = ds[v].values[~np.isnan(ds[v].values)]
                    if len(vals) > 0:
                        var_values[var].extend(vals)

    def smart_range(values, padding=0.05):
        """Return [min, max] axis range with fractional padding; defaults to [0,1] for empty input."""
        if not values:
            return [0, 1]
        min_val, max_val = min(values), max(values)
        range_val = max_val - min_val
        pad = range_val * padding
        return [min_val - pad, max_val + pad]

    var_ranges = {var: smart_range(var_values[var]) for var in active_vars}

    # Setup subplot titles and row heights
    subplot_titles = []
    row_heights = [1] * n_rows
    ctd_name = list(reference_data.keys())[0] if reference_data else "CTD"

    for idx, var in enumerate(active_vars):
        if idx == 0:
            subplot_titles.append(f"{title} / CTD {ctd_name}")
        else:
            subplot_titles.append("")

    total_height = sum(row_heights)
    row_heights = [h / total_height for h in row_heights]

    # Create subplots dynamically
    fig = make_subplots(
        rows=n_rows,
        cols=1,
        subplot_titles=subplot_titles,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=row_heights,
    )

    # Generate colors for instruments
    instrument_serials = list(instrument_data.keys())
    base_colors = pc.qualitative.Plotly + pc.qualitative.D3 + pc.qualitative.G10
    color_map = {serial: base_colors[i % len(base_colors)] for i, serial in enumerate(instrument_serials)}

    # Plot instrument data
    for serial, info in instrument_data.items():
        ds = info["data"]
        color = color_map[serial]
        instrument_label = info["config"].get("label", "Unknown")

        instrument_type = info["config"].get("instrument", "").lower()
        if instrument_type == "sbe" or "sbe" in instrument_label.lower():
            legend_name = f"MC {serial}"
            line_dash = "solid"
        elif instrument_type == "rbr":
            line_dash = "dash"
            legend_name = f"solo {serial}" if "solo" in instrument_label.lower() else f"RBR {serial}"
        else:
            legend_name = f"{serial}"
            line_dash = "solid"

        show_legend_on_first_plot = True

        for var in active_vars:
            row_idx = var_to_row[var]
            
            # Determine which dataset variable to pull (checking primary, secondary, or oxygen phase)
            target_var = None
            if var in ds.data_vars:
                target_var = var
            elif var == "oxygen" and "oxygen_phase" in ds.data_vars:
                target_var = "oxygen_phase"

            if target_var:
                fig.add_trace(
                    go.Scatter(
                        x=ds.time.values,
                        y=ds[target_var].values,
                        mode="lines",
                        name=legend_name,
                        line=dict(color=color, width=2, dash=line_dash),
                        hoverinfo="skip",
                        legendgroup=serial,
                        showlegend=show_legend_on_first_plot,
                    ),
                    row=row_idx,
                    col=1,
                )
                show_legend_on_first_plot = False

    # Plot reference data
    ref_colors = ["black", "gray", "darkred", "darkblue"]
    for i, (name, info) in enumerate(reference_data.items()):
        ds = info["data"]

        for var in active_vars:
            row_idx = var_to_row[var]

            # Handle primary and secondary reference variables dynamically
            ref_configs = []
            if var == "temperature":
                ref_configs = [
                    ("temperature", "CTD T1", "black", 3),
                    ("temperature_2", "CTD T2", "gray", 2)
                ]
            elif var == "conductivity":
                ref_configs = [
                    ("conductivity", "CTD C1", "black", 3),
                    ("conductivity_2", "CTD C2", "gray", 2)
                ]
            else:
                # Default primary variable mapping
                if var in ds.data_vars:
                    ref_configs = [(var, f"CTD {var.capitalize()}", "black", 3)]

            for tvar, tlabel, tcolor, twidth in ref_configs:
                if tvar in ds.data_vars:
                    # Only show legend entries for the first reference source to avoid duplicates
                    show_leg = (i == 0)
                    fig.add_trace(
                        go.Scatter(
                            x=ds.time.values,
                            y=ds[tvar].values,
                            mode="lines",
                            name=tlabel,
                            line=dict(color=tcolor, width=twidth),
                            hoverinfo="skip",
                            legendgroup=f"ctd_{tvar}",
                            showlegend=show_leg,
                        ),
                        row=row_idx,
                        col=1,
                    )

    # Update y-axis labels and ranges dynamically based on active variables
    unit_map = {
        "pressure": "Pressure (dbar)",
        "temperature": "Temperature (°C)",
        "conductivity": "Conductivity (mS/cm)",
        "oxygen": "Oxygen (μmol/L | phase°)"
    }

    for var, row_idx in var_to_row.items():
        axis_title = unit_map.get(var, f"{var.capitalize()}")
        fig.update_yaxes(
            range=var_ranges[var],
            title_text=axis_title,
            row=row_idx,
            col=1
        )

    # Update x-axis configurations
    for row in range(1, n_rows + 1):
        fig.update_xaxes(title_text="", showticklabels=True, row=row, col=1)

    fig.update_layout(
        height=300 * n_rows + 100,
        hovermode=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )

    # Add gridlines
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="rgba(128,128,128,0.2)")
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="rgba(128,128,128,0.2)")

    # Set x-axis limits based on config deployment/recovery times
    if config and "deployment_time" in config and "recovery_time" in config:
        deployment_time = pd.to_datetime(config["deployment_time"])
        recovery_time = pd.to_datetime(config["recovery_time"])
        fig.update_xaxes(range=[deployment_time, recovery_time])

    # Add bottle stop markers if requested
    if show_bottle_stops and reference_data:
        ref_name = list(reference_data.keys())[0]
        ref_ds = reference_data[ref_name]["data"]

        bottle_stops = cf.find_bottle_stops(
            ref_ds,
            threshold_dbar_per_min=bottle_stop_params["threshold_dbar_per_min"],
            min_duration_seconds=bottle_stop_params["min_duration_seconds"],
        )

        if bottle_stops:
            print(f"\nFound {len(bottle_stops)} bottle stops:")

            for i, stop in enumerate(bottle_stops, 1):
                print(
                    f"  Stop {i}: {stop['start_time']} to {stop['end_time']} "
                    f"({stop['duration_seconds']:.0f}s) at {stop['pressure']:.1f} dbar"
                )

                end_dt = pd.to_datetime(stop["end_time"])
                comp_end = end_dt - pd.Timedelta(seconds=30)
                comp_start = comp_end - pd.Timedelta(minutes=2)

                for row in range(1, n_rows + 1):
                    # Fetch appropriate y-range for the current row
                    current_var = active_vars[row - 1]
                    y_range = var_ranges[current_var]

                    # Start of bottle stop (blue)
                    fig.add_trace(
                        go.Scatter(
                            x=[stop["start_time"], stop["start_time"]],
                            y=y_range,
                            mode="lines",
                            line=dict(color="blue", width=2),
                            showlegend=False,
                            hoverinfo="skip",
                        ),
                        row=row,
                        col=1,
                    )

                    # End of bottle stop (red)
                    fig.add_trace(
                        go.Scatter(
                            x=[stop["end_time"], stop["end_time"]],
                            y=y_range,
                            mode="lines",
                            line=dict(color="red", width=2),
                            showlegend=False,
                            hoverinfo="skip",
                        ),
                        row=row,
                        col=1,
                    )

                    # Comparison period boundaries (black dotted)
                    fig.add_trace(
                        go.Scatter(
                            x=[comp_start, comp_start],
                            y=y_range,
                            mode="lines",
                            line=dict(color="black", width=1, dash="dot"),
                            showlegend=False,
                            hoverinfo="skip",
                        ),
                        row=row,
                        col=1,
                    )

                    fig.add_trace(
                        go.Scatter(
                            x=[comp_end, comp_end],
                            y=y_range,
                            mode="lines",
                            line=dict(color="black", width=1, dash="dot"),
                            showlegend=False,
                            hoverinfo="skip",
                        ),
                        row=row,
                        col=1,
                    )

    return fig