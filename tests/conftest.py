"""
Shared pytest fixtures for caldip tests.
"""

import numpy as np
import pandas as pd
import pytest
import xarray as xr


@pytest.fixture
def ctd_one_stop():
    """CTD dataset with a single 6-minute bottle stop at 100 dbar."""
    times = pd.date_range("2024-01-01 12:00:00", periods=1000, freq="1s")
    pressure = np.concatenate(
        [
            np.linspace(0, 90, 300),
            np.full(400, 100.0),
            np.linspace(100, 0, 300),
        ]
    )
    return xr.Dataset(
        {
            "prDM": ("time", pressure),
            "t090C": ("time", np.full(1000, 15.0)),
            "c0mS/cm": ("time", np.full(1000, 35.0)),
        },
        coords={"time": times},
    )


@pytest.fixture
def ctd_no_stops():
    """CTD dataset with a simple descent/ascent and no bottle stops."""
    times = pd.date_range("2024-01-01 12:00:00", periods=500, freq="1s")
    pressure = np.concatenate([np.linspace(0, 100, 250), np.linspace(100, 0, 250)])
    return xr.Dataset({"prDM": ("time", pressure)}, coords={"time": times})


@pytest.fixture
def instrument_data_one_stop(ctd_one_stop):
    """Synthetic MicroCAT instrument dict aligned with ctd_one_stop."""
    times = ctd_one_stop.time.values
    return {
        "12345": {
            "data": xr.Dataset(
                {
                    "temp": ("time", np.full(len(times), 15.05)),
                    "cond": ("time", np.full(len(times), 35.05)),
                },
                coords={"time": times},
            ),
            "config": {"instrument": "sbe37", "label": "SBE37"},
            "type": "sbe37",
        }
    }


@pytest.fixture
def reference_data_one_stop(ctd_one_stop):
    """Reference data dict wrapping ctd_one_stop."""
    return {"ctd": {"data": ctd_one_stop, "config": {}}}


@pytest.fixture
def minimal_config():
    """Minimal caldip config dict."""
    return {"name": "test_cast"}
