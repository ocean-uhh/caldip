#!/usr/bin/env python3
"""
Simple test for Nortek CSV reader functions.
"""
import pandas as pd
import numpy as np
import tempfile
import os

from caldip.readers import (
    _parse_nortek_csv_columns,
    _add_nortek_variable_attributes,
    load_nortek_csv_data,
)
import xarray as xr


def test_parse_nortek_csv_columns():
    """Test the CSV column parsing function."""
    print("Testing _parse_nortek_csv_columns...")

    # Create sample DataFrame
    df = pd.DataFrame(
        {
            "dateTime": ["2026-04-14T08:30:00.001", "2026-04-14T08:30:20.001"],
            "temperature": [3.51, 3.52],
            "pressure": [1807.456, 1829.611],
            "velBeam1#1": [0.383, 0.374],
            "velBeam2#1": [0.041, -0.168],
            "ampBeam1#1": [35.5, 36.0],
            "corrBeam1#1": [74, 95],
            "serialNumber": [400107, 400107],
        }
    )

    # Parse columns
    data_vars = _parse_nortek_csv_columns(df)

    # Check results
    assert "temperature" in data_vars
    assert "pressure" in data_vars
    assert "velocity_beam1" in data_vars
    assert "velocity_beam2" in data_vars
    assert "amplitude_beam1" in data_vars
    assert "correlation_beam1" in data_vars

    # Check values
    assert np.allclose(data_vars["temperature"][1], [3.51, 3.52])
    assert np.allclose(data_vars["pressure"][1], [1807.456, 1829.611])
    assert np.allclose(data_vars["velocity_beam1"][1], [0.383, 0.374])

    print("  ✅ _parse_nortek_csv_columns test passed!")


def test_add_nortek_variable_attributes():
    """Test the variable attributes function."""
    print("Testing _add_nortek_variable_attributes...")

    # Create simple dataset
    data = np.array([1.0, 2.0, 3.0])
    time = pd.date_range("2026-01-01", periods=3, freq="1s")

    ds = xr.Dataset(
        {
            "temperature": (["time"], data),
            "velocity_beam1": (["time"], data),
            "amplitude_beam1": (["time"], data),
        },
        coords={"time": time},
    )

    # Add attributes
    ds = _add_nortek_variable_attributes(ds)

    # Check attributes
    assert ds["temperature"].attrs["units"] == "degrees_C"
    assert ds["temperature"].attrs["long_name"] == "Water Temperature"
    assert ds["velocity_beam1"].attrs["units"] == "m/s"
    assert ds["velocity_beam1"].attrs["coordinate_system"] == "BEAM"
    assert ds["amplitude_beam1"].attrs["units"] == "counts"

    print("  ✅ _add_nortek_variable_attributes test passed!")


def test_load_nortek_csv_data():
    """Test the main CSV loading function with a temporary file."""
    print("Testing load_nortek_csv_data...")

    # Create sample CSV content
    csv_content = """idx;dateTime;serialNumber;temperature;pressure;velBeam1#1;velBeam2#1;ampBeam1#1;corrBeam1#1
1;2026-04-14T08:30:00.001;400107;3.51;1807.456;0.383;0.041;35.5;74
2;2026-04-14T08:30:20.001;400107;3.52;1829.611;0.374;-0.168;36.0;95
3;2026-04-14T08:30:40.001;400107;3.53;1849.204;0.576;-0.083;38.0;90"""

    # Write to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        temp_file = f.name

    try:
        # Load data
        ds = load_nortek_csv_data(temp_file)

        # Check basic structure
        assert "time" in ds.coords
        assert len(ds.time) == 3
        assert "temperature" in ds.data_vars
        assert "pressure" in ds.data_vars
        assert "velocity_beam1" in ds.data_vars

        # Check metadata
        assert ds.attrs["instrument_type"] == "Nortek_Aquadopp"
        assert ds.attrs["serial_number"] == "400107"
        assert ds.attrs["coordinate_system"] == "BEAM"

        # Check variable attributes
        assert ds["temperature"].attrs["units"] == "degrees_C"
        assert ds["velocity_beam1"].attrs["units"] == "m/s"

        # Check values
        assert np.allclose(ds["temperature"].values, [3.51, 3.52, 3.53])
        assert np.allclose(ds["velocity_beam1"].values, [0.383, 0.374, 0.576])

        print("  ✅ load_nortek_csv_data test passed!")

    finally:
        # Clean up
        os.unlink(temp_file)


def test_file_not_found():
    """Test error handling for missing file."""
    print("Testing file not found error...")

    try:
        load_nortek_csv_data("/nonexistent/file.csv")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        print("  ✅ FileNotFoundError test passed!")


if __name__ == "__main__":
    print("🧪 Running Nortek CSV reader tests...\n")

    test_parse_nortek_csv_columns()
    test_add_nortek_variable_attributes()
    test_load_nortek_csv_data()
    test_file_not_found()

    print("\n🎉 All tests passed!")
