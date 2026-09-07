"""Tests for the netCDF inventory page (``caldip inspect``)."""

from pathlib import Path

import numpy as np
import pandas as pd

from caldip import _writers as writers
from caldip.report.inventory import build_inventory_html, read_nc_meta, write_inventory

_CONFIG = {
    "name": "castX",
    "cruise": "msm142",
    "ctd_file": "x.cnv",
    "ctd_sensor": 2,
    "instruments": [{"filename": "a.mat"}],
}
_THRESHOLDS = {"temp": 0.005, "cond": 0.02, "press": 5.0}


def _make_nc(tmp_path: Path) -> Path:
    """Write a small caldip netCDF to inventory."""
    t0 = pd.Timestamp("2024-01-01 12:00:00")
    t1 = pd.Timestamp("2024-01-01 12:30:00")
    df = pd.DataFrame(
        {
            "serial": ["S1", "S1"],
            "instrument_type": ["microcat", "microcat"],
            "bl_press": [1000, 500],
            "stop": [1, 2],
            "time": [t0, t1],
            "t_start": [t0, t1],
            "t_end": [t0 + pd.Timedelta(minutes=2), t1 + pd.Timedelta(minutes=2)],
            "temp_diff": [0.006, 0.001],
            "temp_std": [0.001, 0.001],
            "cond_diff": [np.nan, np.nan],
            "cond_std": [np.nan, np.nan],
            "press_diff": [np.nan, np.nan],
            "press_std": [np.nan, np.nan],
            "ctd_temp": [5.0, 6.0],
            "ctd_cond": [np.nan, np.nan],
            "ctd_press": [1000.0, 500.0],
            "inst_temp": [5.006, 6.001],
            "inst_cond": [np.nan, np.nan],
            "inst_press": [np.nan, np.nan],
            "N": [100, 100],
            "label": ["x", "x"],
            "temp_flag": [3, 1],
            "cond_flag": [4, 4],
            "press_flag": [4, 4],
            "date": ["2024-01-01", "2024-01-01"],
            "time_start": ["12:00:00", "12:30:00"],
            "time_end": ["12:02:00", "12:32:00"],
        }
    )
    return writers.write_stats_netcdf(
        df, _CONFIG, tmp_path / "castX_caldip.nc", thresholds=_THRESHOLDS
    )


def test_read_nc_meta(tmp_path):
    """The inventory metadata lists dims, variables and global attributes."""
    meta = read_nc_meta(_make_nc(tmp_path))
    assert meta["dims"] == {"instrument": 1, "stop": 2}
    names = {v["name"] for v in meta["data_vars"]}
    assert {"temp_diff", "temp_flag", "ctd_press"} <= names
    assert meta["global_attrs"]["data_mode"] == "P"
    assert meta["global_attrs"]["cruise_id"] == "msm142"


def test_inventory_html_sections_and_types(tmp_path):
    """The page carries the sections, dtypes, units, flag meanings and CTD attrs."""
    html = build_inventory_html(_make_nc(tmp_path))
    assert "netCDF inventory" in html
    assert "<h2>Dimensions</h2>" in html
    assert "<th>Shape</th>" in html
    assert "1 × 2" in html  # temp_diff over (instrument=1, stop=2)
    assert "<h2>Variables</h2>" in html
    assert "<h3>CTD reference</h3>" in html
    assert "degree_C" in html
    assert "int16" in html  # bl_press label
    assert "int8" in html  # flags
    assert "flags: ok no_data flagged missing unknown" in html
    assert "instrument minus CTD" in html  # sign-convention comment surfaced


def test_inventory_read_error_is_reported_not_raised(tmp_path):
    """A file that is not a netCDF yields an error page rather than an exception."""
    bad = tmp_path / "bad.nc"
    bad.write_text("not a netcdf", encoding="utf-8")
    html = build_inventory_html(bad)
    assert "could not be read" in html


def test_write_inventory(tmp_path):
    """write_inventory writes the HTML file and returns its path."""
    out = write_inventory(_make_nc(tmp_path), tmp_path / "inv" / "castX.html")
    assert out.exists()
    assert "netCDF inventory" in out.read_text(encoding="utf-8")
