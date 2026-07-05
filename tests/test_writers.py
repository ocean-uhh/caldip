"""
Tests for caldip/writers.py output formatting functions.
"""

import numpy as np
import pandas as pd

from caldip import writers


def _make_summary_df(with_cond=True, with_press=True, with_bottle_stops=False):
    """Build a minimal summary DataFrame matching the real output structure."""
    ctd_stats = {
        "comparison_start": "12:00:00",
        "comparison_end": "12:02:00",
        "bl_press": 1500.0,
        "press_std": 0.5,
        "ctd_temp": 4.523,
        "temp_std": 0.002,
        "ctd_cond": 34.51,
        "mean_cond": 34.51,
        "cond_std": 0.003,
        # No timing_info key → triggers the else branch in print_universal_statistics_report
    }

    if with_bottle_stops:
        ctd_stats["timing_info"] = {
            "bottle_stops": [
                {
                    "start_time": "2024-01-01 12:00:00",
                    "end_time": "2024-01-01 12:05:00",
                    "duration_seconds": 300,
                    "pressure": 1500.0,
                }
            ]
        }

    rows = [
        {
            "serial": "S001",
            "instrument_type": "sbe37",
            "label": "SBE37",
            "N": 120,
            "temp_diff": 0.003,
            "temp_diff_std": 0.001,
            "cond_diff": 0.01 if with_cond else np.nan,
            "cond_diff_std": 0.005 if with_cond else np.nan,
            "press_diff": 0.5 if with_press else np.nan,
            "press_diff_std": 0.2 if with_press else np.nan,
            "ctd_stats": ctd_stats,
        },
    ]
    return pd.DataFrame(rows)


def test_print_report_runs_without_error(capsys):
    """Report prints without raising exceptions."""
    df = _make_summary_df()
    writers.print_universal_statistics_report(df, {"name": "testCast"}, ctd_sensor=1)
    out = capsys.readouterr().out
    assert "testCast" in out
    assert "S001" in out


def test_print_report_sensor_2(capsys):
    """Sensor number appears in the header line."""
    df = _make_summary_df()
    writers.print_universal_statistics_report(df, {"name": "testCast"}, ctd_sensor=2)
    out = capsys.readouterr().out
    assert "Sensor 2" in out


def test_print_report_nan_cond_and_press(capsys):
    """NaN conductivity and pressure are shown as N/A, not errors."""
    df = _make_summary_df(with_cond=False, with_press=False)
    writers.print_universal_statistics_report(df, {"name": "testCast"})
    out = capsys.readouterr().out
    assert "N/A" in out


def test_print_report_with_bottle_stops(capsys):
    """Bottle stop timing block is printed when stops are present."""
    df = _make_summary_df(with_bottle_stops=True)
    writers.print_universal_statistics_report(df, {"name": "testCast"})
    out = capsys.readouterr().out
    assert "Bottle Stop 1" in out
    assert "Duration" in out


def test_print_report_no_bottle_stops(capsys):
    """Falls back to generic timing text when no bottle stops in timing_info."""
    df = _make_summary_df(with_bottle_stops=False)
    writers.print_universal_statistics_report(df, {"name": "testCast"})
    out = capsys.readouterr().out
    assert "Bottle stop period" in out
