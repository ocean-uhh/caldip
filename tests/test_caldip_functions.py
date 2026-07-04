"""
Unit tests for caldip_functions.py core functionality.
"""

import pytest
import numpy as np
import pandas as pd
import xarray as xr

from caldip import caldip_functions as cf


def test_find_bottle_stops_basic():
    """Test basic bottle stop detection with simple synthetic data."""
    # Create synthetic CTD data with one long bottle stop
    times = pd.date_range("2024-01-01 12:00:00", periods=1000, freq="1s")

    # Pressure profile: descent to 100m, one long stop, then ascent
    pressure = np.concatenate(
        [
            np.linspace(0, 90, 300),  # descent to 90m
            np.full(400, 100),  # stop at 100m for 6+ minutes
            np.linspace(100, 0, 300),  # ascent
        ]
    )

    # Create xarray dataset
    ctd_data = xr.Dataset(
        {
            "prDM": ("time", pressure),
            "temp": ("time", np.full(1000, 15.0) + np.random.normal(0, 0.01, 1000)),
        },
        coords={"time": times},
    )

    bottle_stops = cf.find_bottle_stops(ctd_data)

    # Should find at least 1 bottle stop
    assert len(bottle_stops) >= 1

    # Check first stop pressure is reasonable
    assert bottle_stops[0]["pressure"] == pytest.approx(100, abs=5)

    # Check duration is reasonable (at least 3 minutes)
    assert bottle_stops[0]["duration_seconds"] >= 180


def test_find_bottle_stops_no_stops():
    """Test with data that has no bottle stops."""
    times = pd.date_range("2024-01-01 12:00:00", periods=500, freq="1s")

    # Simple descent and ascent with no stops
    pressure = np.concatenate([np.linspace(0, 100, 250), np.linspace(100, 0, 250)])

    ctd_data = xr.Dataset({"prDM": ("time", pressure)}, coords={"time": times})

    bottle_stops = cf.find_bottle_stops(ctd_data)

    assert len(bottle_stops) == 0


def test_find_bottle_stops_pressure_variable_names():
    """Test bottle stop detection with different pressure variable names."""
    times = pd.date_range("2024-01-01 12:00:00", periods=600, freq="1s")

    pressure = np.concatenate(
        [
            np.linspace(0, 50, 200),
            np.full(200, 50),  # 200 second stop
            np.linspace(50, 0, 200),
        ]
    )

    # Test with 'pressure' instead of 'prDM'
    ctd_data = xr.Dataset({"pressure": ("time", pressure)}, coords={"time": times})

    bottle_stops = cf.find_bottle_stops(ctd_data)
    assert len(bottle_stops) == 1


def test_calculate_universal_statistics_workflow():
    """Test the main statistics workflow like in caldip_check_all.py."""
    # Create mock instrument data
    times = pd.date_range("2024-01-01 12:00:00", periods=1000, freq="1s")

    # Create instrument data
    instruments = {
        "12345": {
            "data": xr.Dataset(
                {
                    "temp": (
                        "time",
                        np.full(1000, 15.0) + np.random.normal(0, 0.01, 1000),
                    ),
                    "cond": (
                        "time",
                        np.full(1000, 35.0) + np.random.normal(0, 0.1, 1000),
                    ),
                },
                coords={"time": times},
            ),
            "config": {"instrument": "microcat", "label": "Test"},
            "type": "microcat",
        }
    }

    # Create reference CTD data with bottle stops
    pressure = np.concatenate(
        [
            np.linspace(0, 90, 400),  # descent
            np.full(200, 100),  # bottle stop at 100m for 200s
            np.linspace(100, 0, 400),  # ascent
        ]
    )

    reference_data = {
        "ctd": {
            "data": xr.Dataset(
                {
                    "prDM": ("time", pressure),
                    "temp1": (
                        "time",
                        np.full(1000, 15.05) + np.random.normal(0, 0.005, 1000),
                    ),
                    "c1mS/cm": (
                        "time",
                        np.full(1000, 35.05) + np.random.normal(0, 0.05, 1000),
                    ),
                },
                coords={"time": times},
            ),
            "config": {},
        }
    }

    # Config like in caldip_check_all.py
    config = {"name": "test_cast"}

    # Test the main workflow
    try:
        detailed_stats_df = cf.calculate_universal_statistics_by_bottle_stop(
            instruments, reference_data, config, ctd_sensor=1
        )

        # Should return a DataFrame with results
        assert not detailed_stats_df.empty
        assert len(detailed_stats_df) > 0

        # Check expected columns exist
        expected_cols = ["serial", "instrument_type", "temp_diff", "N"]
        for col in expected_cols:
            assert col in detailed_stats_df.columns

    except Exception as e:
        # If it fails, at least it shouldn't crash completely
        assert False, f"Function crashed unexpectedly: {e}"


def test_empty_dataset():
    """Test handling of empty datasets."""
    empty_data = xr.Dataset()

    # Should not crash, should return empty list
    bottle_stops = cf.find_bottle_stops(empty_data)
    assert bottle_stops == []


def test_missing_pressure_variable():
    """Test handling when pressure variable is missing."""
    times = pd.date_range("2024-01-01 12:00:00", periods=100, freq="1s")

    # Dataset with no pressure variable
    data = xr.Dataset({"temp": ("time", np.full(100, 15.0))}, coords={"time": times})

    bottle_stops = cf.find_bottle_stops(data)
    assert bottle_stops == []
