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
    optional_variables: Optional[list[str]] = None,
    config: Optional[Dict] = None,
    title: str = "Caldip Data Comparison",
    show_bottle_stops: bool = True,
    bottle_stop_params: Optional[Dict] = None,
) -> Optional[object]:
    """
    Create interactive caldip comparison plot with dynamic optional variables.

    Subplot layout:
    - Row 1: Pressure (Default)
    - Row 2: Temperature (Default)
    - Rows 3+: Optional variables (including conductivity, oxygen, etc., if specified or available)
    """
    # Ensure optional_variables is a list if passed as string or None
    if optional_variables is None:
        optional_variables = []
    elif isinstance(optional_variables, str):
        optional_variables = [optional_variables]

    # Ensure 'conductivity' and 'oxygen' (or 'oxygen_phase') are included if requested/available
    # If the user wants them strictly optional, we check if they exist or if they are explicitly passed.
    # To treat them as optional variables, we can make sure they append smoothly if present in datasets.
    
    # Subplot base row assignments (Pressure and Temperature are fixed at the top)
    PRESSURE_ROW = 1
    TEMPERATURE_ROW = 2

    # Dynamically assign row indices for optional variables starting after Row 2
    next_row = 3
    optional_rows = {}
    
    # Standard mandatory set to check against custom ones
    standard_optional_candidates = ["conductivity", "oxygen"]
    
    # Combine user-defined optional variables with standard optional ones if they exist in the data
    # or let the user explicitly list what they want. Here we automatically include standard ones 
    # if they are present in the data datasets, or you can pass them explicitly via `optional_variables`.
    all_possible_optionals = list(set(optional_variables + standard_optional_candidates))

    if not PLOTLY_AVAILABLE:
        print("Plotly not available - cannot create interactive plot")
        return None

    # Set default bottle stop parameters
    if bottle_stop_params is None:
        bottle_stop_params = {
            "threshold_dbar_per_min": 30.0,
            "min_duration_seconds": 120.0,
        }

    # Collect all data values for y-axis range calculation
    pressure_values = []
    temperature_values = []
    
    # Dynamic storage for values and availability of all optional fields
    active_optionals = []
    optional_values = {}
    optional_has_data = {}

    # Pre-scan instrument and reference data to see which optional variables actually contain data
    all_data_sources = list(instrument_data.values()) + list(reference_data.values())
    
    for var in all_possible_optionals:
        var_values = []
        for info in all_data_sources:
            ds = info["data"]
            # Handle standard oxygen naming flexibility
            target_vars = [var]
            if var == "oxygen":
                target_vars = ["oxygen", "oxygen_phase"]
                
            for tv in target_vars:
                if tv in ds.data_vars:
                    val = ds[tv].values[~np.isnan(ds[tv].values)]
                    if len(val) > 0:
                        var_values.extend(val)
        
        # Keep variable active if it was explicitly requested OR if it's a standard one with valid data
        is_explicitly_requested = var in optional_variables
        is_standard_with_data = var in standard_optional_candidates and len(var_values) > 0
        
        if is_explicitly_requested or is_standard_with_data:
            if var not in active_optionals:
                active_optionals.append(var)
            optional_values[var] = var_values

    # Assign row indices for all active optional variables
    for var in active_optionals:
        optional_rows[var] = next_row
        next_row += 1

    # Collect core pressure and temperature values
    for info in all_data_sources:
        ds = info["data"]
        if "pressure" in ds.data_vars:
            pressure_values.extend(ds["pressure"].values[~np.isnan(ds["pressure"].values)])
        
        for tvar in ["temperature", "temperature_2"]:
            if tvar in ds.data_vars:
                temperature_values.extend(ds[tvar].values[~np.isnan(ds[tvar].values)])

    def smart_range(values, padding=0.05):
        """Return [min, max] axis range with fractional padding; defaults to [0,1] for empty input."""
        if not values:
            return [0, 1]
        min_val, max_val = min(values), max(values)
        range_val = max_val - min_val
        pad = range_val * padding
        return [min_val - pad, max_val + pad]

    pressure_range = smart_range(pressure_values)
    temperature_range = smart_range(temperature_values)
    optional_ranges = {var: smart_range(optional_values.get(var, [])) for var in active_optionals}

    # Dynamic subplot structure setup
    subplot_titles = []
    row_heights = []

    ctd_name = list(reference_data.keys())[0] if reference_data else "CTD"

    # Subplot 1: Pressure
    subplot_titles.append(f"{title} / CTD {ctd_name}")
    row_heights.append(1)

    # Subplot 2: Temperature
    subplot_titles.append("")
    row_heights.append(1)

    # Subplots 3+: Active Optional Variables
    for var in active_optionals:
        subplot_titles.append("")
        row_heights.append(1)

    # Normalize row heights
    total_height = sum(row_heights)
    row_heights = [h / total_height for h in row_heights]
    n_rows = len(subplot_titles)

    # Create subplots
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
            legend_name = f"{instrument_label} {serial}" if ("solo" in instrument_label.lower() or "tr" in instrument_label.lower()) else f"RBR {serial}"
        else:
            legend_name = f"{serial}"
            line_dash = "solid"

        show_legend_on_first_plot = True

        # Pressure subplot
        if "pressure" in ds.data_vars:
            fig.add_trace(
                go.Scatter(
                    x=ds.time.values,
                    y=ds["pressure"].values,
                    mode="lines",
                    name=legend_name,
                    line=dict(color=color, width=2, dash=line_dash),
                    hoverinfo="skip",
                    legendgroup=serial,
                    showlegend=show_legend_on_first_plot,
                ),
                row=PRESSURE_ROW,
                col=1,
            )
            show_legend_on_first_plot = False

        # Temperature subplot
        if "temperature" in ds.data_vars:
            fig.add_trace(
                go.Scatter(
                    x=ds.time.values,
                    y=ds["temperature"].values,
                    mode="lines",
                    name=legend_name,
                    line=dict(color=color, width=2, dash=line_dash),
                    hoverinfo="skip",
                    legendgroup=serial,
                    showlegend=show_legend_on_first_plot,
                ),
                row=TEMPERATURE_ROW,
                col=1,
            )
            show_legend_on_first_plot = False

        # Optional variables subplots (instrument)
        for var in active_optionals:
            target_vars = [var]
            if var == "oxygen":
                target_vars = ["oxygen", "oxygen_phase"]
                
            for tv in target_vars:
                if tv in ds.data_vars:
                    fig.add_trace(
                        go.Scatter(
                            x=ds.time.values,
                            y=ds[tv].values,
                            mode="lines",
                            name=legend_name,
                            line=dict(color=color, width=2, dash=line_dash),
                            hoverinfo="skip",
                            legendgroup=serial,
                            showlegend=False,
                        ),
                        row=optional_rows[var],
                        col=1,
                    )
                    break

    # Plot reference data
    ref_colors = ["black", "gray", "darkred", "darkblue"]
    for i, (name, info) in enumerate(reference_data.items()):
        ds = info["data"]

        # Reference pressure
        if "pressure" in ds.data_vars:
            fig.add_trace(
                go.Scatter(
                    x=ds.time.values,
                    y=ds["pressure"].values,
                    mode="lines",
                    name=f"CTD {name}",
                    line=dict(color=ref_colors[i % len(ref_colors)], width=3),
                    hoverinfo="skip",
                    legendgroup=f"ctd_{name}",
                    showlegend=False,
                ),
                row=PRESSURE_ROW,
                col=1,
            )

        # Reference temperatures
        for tvar, tlabel, tcolor, twidth in [
            ("temperature", "CTD T1", "black", 3),
            ("temperature_2", "CTD T2", "gray", 2),
        ]:
            if tvar in ds.data_vars:
                fig.add_trace(
                    go.Scatter(
                        x=ds.time.values,
                        y=ds[tvar].values,
                        mode="lines",
                        name=tlabel,
                        line=dict(color=tcolor, width=twidth),
                        hoverinfo="skip",
                        legendgroup=f"ctd_{tvar}",
                        showlegend=True,
                    ),
                    row=TEMPERATURE_ROW,
                    col=1,
                )

        # Reference optional variables
        for var in active_optionals:
            target_vars = [var]
            if var == "oxygen":
                target_vars = ["oxygen", "oxygen_phase"]
                
            for tv in target_vars:
                if tv in ds.data_vars:
                    fig.add_trace(
                        go.Scatter(
                            x=ds.time.values,
                            y=ds[tv].values,
                            mode="lines",
                            name=f"CTD {var}",
                            line=dict(color="black", width=3),
                            hoverinfo="skip",
                        ),
                        row=optional_rows[var],
                        col=1,
                    )
                    break

    # Update y-axis labels and ranges for core parameters
    fig.update_yaxes(range=pressure_range, title_text="Pressure (dbar)", row=PRESSURE_ROW, col=1)
    fig.update_yaxes(range=temperature_range, title_text="Temperature (°C)", row=TEMPERATURE_ROW, col=1)

    # Update y-axes for active optional variables dynamically with smart formatting
    for var in active_optionals:
        unit_label = "mS/cm" if "conductivity" in var else ("μmol/L | phase°" if "oxygen" in var else "")
        title_text = f"{var.replace('_', ' ').title()} ({unit_label})" if unit_label else var.replace('_', ' ').title()
        
        fig.update_yaxes(
            range=optional_ranges[var],
            title_text=title_text,
            row=optional_rows[var],
            col=1,
        )

    # Update x-axis
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

    # Add bottle stop markers if requested (spanning all dynamic rows)
    if show_bottle_stops and reference_data:
        ref_name = list(reference_data.keys())[0]
        ref_ds = reference_data[ref_name]["data"]

        bottle_stops = cf.find_bottle_stops(
            ref_ds,
            threshold_dbar_per_min=bottle_stop_params["threshold_dbar_per_min"],
            min_duration_seconds=bottle_stop_params["min_duration_seconds"],
        )

        if bottle_stops:
            for stop in bottle_stops:
                end_dt = pd.to_datetime(stop["end_time"])
                comp_end = end_dt - pd.Timedelta(seconds=30)
                comp_start = comp_end - pd.Timedelta(minutes=2)

                for row in range(1, n_rows + 1):
                    # Map row to appropriate range reference
                    if row == PRESSURE_ROW:
                        y_range = pressure_range
                    elif row == TEMPERATURE_ROW:
                        y_range = temperature_range
                    else:
                        y_range = temperature_range
                        for var, opt_r in optional_rows.items():
                            if opt_r == row:
                                y_range = optional_ranges[var]

                    # Draw boundaries across all subplots
                    for x_val, color, dash in [
                        (stop["start_time"], "blue", "solid"),
                        (stop["end_time"], "red", "solid"),
                        (comp_start, "black", "dot"),
                        (comp_end, "black", "dot")
                    ]:
                        fig.add_trace(
                            go.Scatter(
                                x=[x_val, x_val],
                                y=y_range,
                                mode="lines",
                                line=dict(color=color, width=1 if dash=="dot" else 2, dash=dash),
                                showlegend=False,
                                hoverinfo="skip",
                            ),
                            row=row,
                            col=1,
                        )

    return fig