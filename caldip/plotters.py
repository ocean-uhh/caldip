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
import caldip.caldip_functions as cf


def create_universal_caldip_plot(
    instrument_data: Dict[str, Dict],
    reference_data: Dict[str, Dict],
    config: Optional[Dict] = None,
    title: str = "Caldip Data Comparison",
    show_bottle_stops: bool = True,
    bottle_stop_params: Optional[Dict] = None,
) -> Optional[object]:
    """
    Create interactive caldip comparison plot for any instrument types.

    Subplot layout:
    - Row 1: Pressure
    - Row 2: Temperature
    - Row 3: Conductivity (if available)

    This function replaces the instrument-specific plotting functions with a
    universal approach that works for MicroCATs, RBRs, and other instruments.

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

    Returns
    -------
    plotly.graph_objects.Figure or None
        Interactive plot figure, or None if plotly not available
    """
    # Subplot row assignments (can be changed here if needed)
    PRESSURE_ROW = 1
    TEMPERATURE_ROW = 2
    CONDUCTIVITY_ROW = 3
    OXYGEN_ROW = 4

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
    conductivity_values = []
    oxygen_values = []

    # Determine if we have pressure data from instruments (vs temperature-only)
    has_instrument_pressure = False
    has_conductivity = False
    has_oxygen = False

    # Collect instrument values and determine plot structure
    for serial, info in instrument_data.items():
        ds = info["data"]

        # Check for pressure variables
        pressure_vars = ["prdM", "pressure", "press", "PRES"]
        for var in pressure_vars:
            if var in ds.data_vars:
                pressure_values.extend(ds[var].values[~np.isnan(ds[var].values)])
                has_instrument_pressure = True
                break

        # Check for temperature variables
        temp_vars = ["tv290C", "temperature", "temp", "TEMP"]
        for var in temp_vars:
            if var in ds.data_vars:
                temperature_values.extend(ds[var].values[~np.isnan(ds[var].values)])
                break

        # Check for conductivity variables - only from instruments that should have conductivity
        cond_vars = ["cond0mS/cm", "conductivity", "cond", "COND"]
        for var in cond_vars:
            if var in ds.data_vars:
                # Only count conductivity if it has actual values (not just NaN)
                cond_data = ds[var].values[~np.isnan(ds[var].values)]
                if len(cond_data) > 0:
                    conductivity_values.extend(cond_data)
                    has_conductivity = True
                break
        
        # Check for oxygen variables - SBE37-ODO sensors
        oxygen_vars = ["oxygen_phase", "oxygen_temp", "oxygen", "OXYGEN"]
        for var in oxygen_vars:
            if var in ds.data_vars:
                # Only count oxygen if it has actual values (not just NaN)
                oxygen_data = ds[var].values[~np.isnan(ds[var].values)]
                if len(oxygen_data) > 0:
                    oxygen_values.extend(oxygen_data)
                    has_oxygen = True
                break

    # Collect reference data values
    for name, info in reference_data.items():
        ds = info["data"]

        # CTD pressure
        if "prDM" in ds.data_vars:
            pressure_values.extend(ds.prDM.values[~np.isnan(ds.prDM.values)])

        # CTD temperatures
        for temp_var in ["t090C", "t190C", "temp_primary", "temp_secondary"]:
            if temp_var in ds.data_vars:
                temperature_values.extend(
                    ds[temp_var].values[~np.isnan(ds[temp_var].values)]
                )

        # CTD conductivities - only collect values if instruments have conductivity
        if has_conductivity:
            for cond_var in ["c0mS/cm", "c1mS/cm", "cond_primary", "cond_secondary"]:
                if cond_var in ds.data_vars:
                    conductivity_values.extend(
                        ds[cond_var].values[~np.isnan(ds[cond_var].values)]
                    )
        
        # CTD oxygen - only collect values if instruments have oxygen
        if has_oxygen:
            for oxy_var in ["sbeox0Mm/L", "sbeox1Mm/L", "oxygen", "oxy_primary", "oxy_secondary"]:
                if oxy_var in ds.data_vars:
                    oxygen_values.extend(
                        ds[oxy_var].values[~np.isnan(ds[oxy_var].values)]
                    )

    def smart_range(values, padding=0.05):
        if not values:
            return [0, 1]
        min_val, max_val = min(values), max(values)
        range_val = max_val - min_val
        pad = range_val * padding
        return [min_val - pad, max_val + pad]

    pressure_range = smart_range(pressure_values)
    temperature_range = smart_range(temperature_values)
    conductivity_range = smart_range(conductivity_values)
    oxygen_range = smart_range(oxygen_values)

    # Dynamic subplot structure - 2-4 subplots
    subplot_titles = []
    row_heights = []

    # Get CTD reference name for title
    ctd_name = list(reference_data.keys())[0] if reference_data else "CTD"

    # Subplot 1: Always pressure (with main title)
    subplot_titles.append(f"{title} / CTD {ctd_name}")
    row_heights.append(1)

    # Subplot 2: Always temperature (no title)
    subplot_titles.append("")
    row_heights.append(1)

    # Subplot 3: Conductivity if any instruments have it (no title)
    if has_conductivity:
        subplot_titles.append("")
        row_heights.append(1)
    
    # Subplot 4: Oxygen if any instruments have it (no title)
    if has_oxygen:
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

    color_map = {}
    for i, serial in enumerate(instrument_serials):
        color_map[serial] = base_colors[i % len(base_colors)]

    current_row = 1

    # Plot instrument data
    for serial, info in instrument_data.items():
        ds = info["data"]
        color = color_map[serial]
        instrument_label = info["config"].get("label", "Unknown")

        # Create smart legend labels and line styles
        instrument_type = info["config"].get("instrument", "").lower()
        if instrument_type == "sbe" or "sbe" in instrument_label.lower():
            legend_name = f"MC {serial}"
            line_dash = "solid"  # MicroCATs get solid lines
        elif instrument_type == "rbr":
            if "solo" in instrument_label.lower():
                legend_name = f"solo {serial}"
                line_dash = "dash"  # RBR thermistors get dashed lines
            elif "tr" in instrument_label.lower():
                legend_name = f"TR {serial}"
                line_dash = "dash"  # RBR thermistors get dashed lines
            else:
                legend_name = f"RBR {serial}"
                line_dash = "dash"  # Default RBR get dashed lines
        else:
            legend_name = f"{serial}"
            line_dash = "solid"  # Default to solid

        show_legend_on_first_plot = True

        # Pressure subplot
        pressure_vars = ["prdM", "pressure", "press", "PRES"]
        for var in pressure_vars:
            if var in ds.data_vars:
                fig.add_trace(
                    go.Scatter(
                        x=ds.time.values,
                        y=ds[var].values,
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
                break

        # Temperature subplot
        temp_vars = ["tv290C", "temperature", "temp", "TEMP"]
        for var in temp_vars:
            if var in ds.data_vars:
                fig.add_trace(
                    go.Scatter(
                        x=ds.time.values,
                        y=ds[var].values,
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
                break

        # Conductivity subplot (if conductivity subplot exists)
        if has_conductivity:
            cond_vars = ["cond0mS/cm", "conductivity", "cond", "COND"]
            for var in cond_vars:
                if var in ds.data_vars:
                    fig.add_trace(
                        go.Scatter(
                            x=ds.time.values,
                            y=ds[var].values,
                            mode="lines",
                            name=legend_name,
                            line=dict(color=color, width=2, dash=line_dash),
                            hoverinfo="skip",
                            legendgroup=serial,
                            showlegend=False,
                        ),
                        row=CONDUCTIVITY_ROW,
                        col=1,
                    )
                    break
        
        # Oxygen subplot (if oxygen subplot exists)
        if has_oxygen:
            # Plot oxygen phase (primary oxygen measurement for SBE37-ODO)
            oxygen_vars = ["oxygen_phase", "oxygen", "OXYGEN"]
            for var in oxygen_vars:
                if var in ds.data_vars:
                    fig.add_trace(
                        go.Scatter(
                            x=ds.time.values,
                            y=ds[var].values,
                            mode="lines",
                            name=legend_name,
                            line=dict(color=color, width=2, dash=line_dash),
                            hoverinfo="skip",
                            legendgroup=serial,
                            showlegend=False,
                        ),
                        row=OXYGEN_ROW,
                        col=1,
                    )
                    break

    # Plot reference data
    ref_colors = ["black", "gray", "darkred", "darkblue"]
    for i, (name, info) in enumerate(reference_data.items()):
        ds = info["data"]
        ref_color = ref_colors[i % len(ref_colors)]

        show_ref_legend = i == 0  # Only show legend for first reference

        current_row = 1

        # Reference pressure
        if "prDM" in ds.data_vars:
            fig.add_trace(
                go.Scatter(
                    x=ds.time.values,
                    y=ds.prDM.values,
                    mode="lines",
                    name=f"CTD {name}",
                    line=dict(color=ref_color, width=3),
                    hoverinfo="skip",
                    legendgroup=f"ctd_{name}",
                    showlegend=False,  # Don't show CTD pressure in legend
                ),
                row=PRESSURE_ROW,
                col=1,
            )

        # Reference temperatures
        temp_vars = ["t090C", "t190C", "temp_primary", "temp_secondary"]
        temp_sensors = [var for var in temp_vars if var in ds.data_vars]

        for j, temp_var in enumerate(temp_sensors[:2]):  # Max 2 temperature sensors
            sensor_color = "black" if j == 0 else "gray"
            sensor_name = "CTD primary" if j == 0 else "CTD secondary"

            fig.add_trace(
                go.Scatter(
                    x=ds.time.values,
                    y=ds[temp_var].values,
                    mode="lines",
                    name=sensor_name,
                    line=dict(color=sensor_color, width=3),
                    hoverinfo="skip",
                    legendgroup=f"ctd_t{j+1}",
                    showlegend=(show_ref_legend and j < 2),
                ),
                row=TEMPERATURE_ROW,
                col=1,
            )
            show_ref_legend = False  # Only show legend for first temperature sensor

        # Reference conductivities
        if has_conductivity:
            cond_vars = ["c0mS/cm", "c1mS/cm", "cond_primary", "cond_secondary"]
            cond_sensors = [var for var in cond_vars if var in ds.data_vars]

            for j, cond_var in enumerate(
                cond_sensors[:2]
            ):  # Max 2 conductivity sensors
                sensor_color = "black" if j == 0 else "gray"
                sensor_name = "CTD C1" if j == 0 else "CTD C2"

                fig.add_trace(
                    go.Scatter(
                        x=ds.time.values,
                        y=ds[cond_var].values,
                        mode="lines",
                        name=sensor_name,
                        line=dict(color=sensor_color, width=3),
                        hoverinfo="skip",
                        legendgroup=f"ctd_c{j+1}",
                        showlegend=False,  # Don't repeat CTD in legend for conductivity
                    ),
                    row=CONDUCTIVITY_ROW,
                    col=1,
                )
        
        # CTD Oxygen sensors
        if has_oxygen:
            oxy_vars = ["sbeox0Mm/L", "sbeox1Mm/L", "oxygen", "oxy_primary", "oxy_secondary"]
            oxy_sensors = [var for var in oxy_vars if var in ds.data_vars]

            for j, oxy_var in enumerate(
                oxy_sensors[:2]
            ):  # Max 2 oxygen sensors
                sensor_color = "black" if j == 0 else "gray"
                sensor_name = "CTD O2-1" if j == 0 else "CTD O2-2"

                fig.add_trace(
                    go.Scatter(
                        x=ds.time.values,
                        y=ds[oxy_var].values,
                        mode="lines",
                        name=sensor_name,
                        line=dict(color=sensor_color, width=3),
                        hoverinfo="skip",
                        legendgroup=f"ctd_o{j+1}",
                        showlegend=False,  # Don't repeat CTD in legend for oxygen
                    ),
                    row=OXYGEN_ROW,
                    col=1,
                )

    # Update y-axis labels and ranges
    fig.update_yaxes(
        range=pressure_range, title_text="Pressure (dbar)", row=PRESSURE_ROW, col=1
    )
    fig.update_yaxes(
        range=temperature_range,
        title_text="Temperature (°C)",
        row=TEMPERATURE_ROW,
        col=1,
    )

    if has_conductivity:
        fig.update_yaxes(
            range=conductivity_range,
            title_text="Conductivity (mS/cm)",
            row=CONDUCTIVITY_ROW,
            col=1,
        )
    
    if has_oxygen:
        fig.update_yaxes(
            range=oxygen_range,
            title_text="Oxygen (μmol/L | phase°)",
            row=OXYGEN_ROW,
            col=1,
        )

    # Update x-axis (remove titles, keep tick labels)
    for row in range(1, n_rows + 1):
        fig.update_xaxes(title_text="", showticklabels=True, row=row, col=1)

    fig.update_layout(
        height=300 * n_rows + 100,  # Scale height based on number of subplots
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
        # Get the first reference dataset for bottle stop detection
        ref_name = list(reference_data.keys())[0]
        ref_ds = reference_data[ref_name]["data"]

        # Find bottle stops using the configurable parameters
        bottle_stops = cf.find_bottle_stops(
            ref_ds,
            threshold_dbar_per_min=bottle_stop_params["threshold_dbar_per_min"],
            min_duration_seconds=bottle_stop_params["min_duration_seconds"],
        )

        if bottle_stops:
            print(f"\\nFound {len(bottle_stops)} bottle stops:")

            # Add bottle stop markers to all subplots
            for i, stop in enumerate(bottle_stops, 1):
                print(
                    f"  Stop {i}: {stop['start_time']} to {stop['end_time']} "
                    f"({stop['duration_seconds']:.0f}s) at {stop['pressure']:.1f} dbar"
                )

                # Calculate comparison period (2 minutes ending 30 seconds before bottle stop end)
                end_dt = pd.to_datetime(stop["end_time"])
                comp_end = end_dt - pd.Timedelta(seconds=30)
                comp_start = comp_end - pd.Timedelta(minutes=2)

                # Add vertical lines to all subplot rows
                for row in range(1, n_rows + 1):
                    # Get appropriate y-range for this subplot
                    if row == PRESSURE_ROW:
                        y_range = pressure_range
                    elif row == TEMPERATURE_ROW:
                        y_range = temperature_range
                    elif row == CONDUCTIVITY_ROW:
                        y_range = conductivity_range
                    elif row == OXYGEN_ROW:
                        y_range = oxygen_range
                    else:
                        y_range = temperature_range  # Default

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
