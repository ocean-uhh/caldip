"""
Tests for caldip/tools.py utility functions.
"""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from caldip import tools


def make_dataset(start="2024-01-01 12:00:00", periods=600, pressure=None):
    """Build a minimal xarray Dataset with time and pressure."""
    times = pd.date_range(start, periods=periods, freq="1s")
    if pressure is None:
        pressure = np.linspace(0, 100, periods)
    return xr.Dataset(
        {"prDM": ("time", pressure), "temp": ("time", np.full(periods, 15.0))},
        coords={"time": times},
    )


# ---------------------------------------------------------------------------
# trim_data_to_deployment
# ---------------------------------------------------------------------------

def test_trim_data_to_deployment_basic():
    """Data outside deployment window is removed."""
    ds = make_dataset(periods=600)
    instruments = {"S001": {"data": ds, "config": {}, "type": "sbe37"}}
    reference = {"ctd": {"data": ds.copy(), "config": {}}}
    config = {
        "deployment_time": "2024-01-01 12:03:00",
        "recovery_time": "2024-01-01 12:07:00",
    }

    inst_out, ref_out = tools.trim_data_to_deployment(instruments, reference, config)

    assert "S001" in inst_out
    assert len(inst_out["S001"]["data"].time) < 600
    assert len(inst_out["S001"]["data"].time) == pytest.approx(240, abs=2)


def test_trim_data_to_deployment_no_times():
    """Returns data unchanged when config has no deployment/recovery times."""
    ds = make_dataset(periods=100)
    instruments = {"S001": {"data": ds, "config": {}, "type": "sbe37"}}
    reference = {"ctd": {"data": ds.copy(), "config": {}}}

    inst_out, ref_out = tools.trim_data_to_deployment(instruments, reference, {})

    assert inst_out is instruments
    assert ref_out is reference


def test_trim_data_to_deployment_instrument_outside_window():
    """Instruments with no samples in deployment window are dropped."""
    ds = make_dataset(start="2024-01-01 10:00:00", periods=60)  # well before deployment
    instruments = {"S001": {"data": ds, "config": {}, "type": "sbe37"}}
    reference = {"ctd": {"data": make_dataset(periods=600), "config": {}}}
    config = {
        "deployment_time": "2024-01-01 12:00:00",
        "recovery_time": "2024-01-01 12:10:00",
    }

    inst_out, ref_out = tools.trim_data_to_deployment(instruments, reference, config)

    assert "S001" not in inst_out


# ---------------------------------------------------------------------------
# extract_summary_from_detailed_stats
# ---------------------------------------------------------------------------

def _make_detailed_df():
    """Build a minimal detailed stats DataFrame matching the real output structure."""
    return pd.DataFrame([
        {
            "serial": "S001", "instrument_type": "sbe37", "label": "SBE37",
            "N": 120, "bl_press": 1500, "temp_diff": 0.003, "temp_std": 0.001,
            "cond_diff": 0.01, "cond_std": 0.005,
            "press_diff": 0.5, "press_std": 0.2,
            "time_start": "12:00:00", "time_end": "12:02:00",
            "ctd_temp": 4.5, "ctd_cond": 34.5,
        },
        {
            "serial": "S001", "instrument_type": "sbe37", "label": "SBE37",
            "N": 120, "bl_press": 800, "temp_diff": 0.002, "temp_std": 0.001,
            "cond_diff": 0.008, "cond_std": 0.004,
            "press_diff": 0.4, "press_std": 0.1,
            "time_start": "13:00:00", "time_end": "13:02:00",
            "ctd_temp": 6.0, "ctd_cond": 34.2,
        },
        {
            "serial": "T002", "instrument_type": "rbr", "label": "TR1050",
            "N": 120, "bl_press": 1500, "temp_diff": -0.004, "temp_std": 0.002,
            "cond_diff": "", "cond_std": "",
            "press_diff": "", "press_std": "",
            "time_start": "12:00:00", "time_end": "12:02:00",
            "ctd_temp": 4.5, "ctd_cond": "",
        },
    ])


def test_extract_summary_picks_deepest_stop():
    """Summary uses the deepest bottle stop (highest bl_press) per instrument."""
    df = _make_detailed_df()
    summary = tools.extract_summary_from_detailed_stats(df, {"name": "test"})

    s001_row = summary[summary["serial"] == "S001"].iloc[0]
    assert s001_row["bl_press"] == 1500


def test_extract_summary_empty_input():
    """Empty input returns empty DataFrame."""
    result = tools.extract_summary_from_detailed_stats(pd.DataFrame(), {})
    assert result.empty


def test_extract_summary_converts_empty_strings_to_nan():
    """Empty string placeholders (used for RBR thermistors) become NaN."""
    df = _make_detailed_df()
    summary = tools.extract_summary_from_detailed_stats(df, {"name": "test"})

    rbr_row = summary[summary["serial"] == "T002"].iloc[0]
    assert np.isnan(rbr_row["cond_diff"])
    assert np.isnan(rbr_row["press_diff"])


def test_extract_summary_one_row_per_instrument():
    """Each instrument appears exactly once in the summary."""
    df = _make_detailed_df()
    summary = tools.extract_summary_from_detailed_stats(df, {"name": "test"})

    assert len(summary) == 2
    assert set(summary["serial"]) == {"S001", "T002"}
