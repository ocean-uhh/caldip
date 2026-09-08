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
    assert meta["global_attrs"]["cruise"] == "msm142"


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


def _ctdcast_file(tmp_path, data_mode="P", stem="ref"):
    """Write a minimal ctdcast stage-3 nc that read_ctdcast_reference can read."""
    import xarray as xr

    n = 4
    time = pd.date_range("2026-04-03T12:00:00", periods=n, freq="1s")
    ones = np.ones(n)
    ds = xr.Dataset(
        {
            "ctd_temperature_1": ("time", 5.0 * ones),
            "ctd_temperature_2": ("time", 6.0 * ones),
            "conductivity_1": ("time", 30.0 * ones),
            "conductivity_2": ("time", 31.0 * ones),
            "pressure": ("time", 1000.0 * ones),
        },
        coords={"time": time},
    )
    _plevel = "Instrument data that has been converted to geophysical values"
    ds["ctd_temperature_2"].attrs.update(
        {
            "sensor": "SENSOR_TEMPERATURE_5808",
            "units": "degree_Celsius",
            "processing_level": _plevel,
        }
    )
    ds["conductivity_2"].attrs.update(
        {
            "sensor": "SENSOR_CONDUCTIVITY_2452",
            "units": "mS cm-1",
            "processing_level": _plevel,
        }
    )
    ds["pressure"].attrs["processing_level"] = _plevel
    for name, serial, caldate in (
        ("SENSOR_TEMPERATURE_5808", "5808", "2019-Apr-09"),
        ("SENSOR_CONDUCTIVITY_2452", "2452", "2017-Aug-18"),
    ):
        ds[name] = xr.DataArray(0)
        ds[name].attrs["sensor_serial_number"] = serial
        ds[name].attrs["sensor_calibration_date"] = caldate
    ds.attrs.update(
        {"processing_stage": 3, "data_mode": data_mode, "cruise": "MSM142",
         "tracking_id": f"tid-{data_mode}"}
    )
    path = tmp_path / f"{stem}_stage3.nc"
    ds.to_netcdf(path, engine="netcdf4")
    return path


def _caldip_nc_with_ref(tmp_path, ctd_path, recorded_data_mode="P"):
    """Write a caldip nc whose recorded provenance points at ``ctd_path``."""
    import xarray as xr

    from caldip.readers import read_ctdcast_reference

    with xr.open_dataset(ctd_path, engine="netcdf4") as ds:
        _, prov = read_ctdcast_reference(ds, 2)
    prov = dict(prov)
    prov["data_mode"] = recorded_data_mode  # what was recorded at run time
    t0 = pd.Timestamp("2026-04-03 12:00:00")
    df = pd.DataFrame(
        {
            "serial": ["13874"], "instrument_type": ["tr1050"], "bl_press": [1000],
            "stop": [1], "time": [t0], "t_start": [t0],
            "t_end": [t0 + pd.Timedelta(minutes=2)], "temp_diff": [0.006],
            "temp_std": [0.001], "cond_diff": [np.nan], "cond_std": [np.nan],
            "press_diff": [np.nan], "press_std": [np.nan], "ctd_temp": [6.0],
            "ctd_cond": [np.nan], "ctd_press": [1000.0], "inst_temp": [6.006],
            "inst_cond": [np.nan], "inst_press": [np.nan], "N": [100], "label": ["x"],
            "temp_flag": [1], "cond_flag": [2], "press_flag": [2],
            "date": ["2026-04-03"], "time_start": ["12:00:00"],
            "time_end": ["12:02:00"],
        }
    )
    return writers.write_stats_netcdf(
        df, _CONFIG, tmp_path / "castX_caldip.nc", thresholds=_THRESHOLDS,
        input_mode="netcdf", ctd_provenance=prov, ctd_path=str(ctd_path),
    )


def test_no_reference_state_on_cnv_output(tmp_path):
    """A .cnv-sourced output has no recorded/now comparison; the plain table shows."""
    meta = read_nc_meta(_make_nc(tmp_path))
    assert meta["reference_state"] is None
    assert "as recorded / now" not in build_inventory_html(_make_nc(tmp_path))


def test_reference_recorded_now_matches(tmp_path):
    """When the reference is unchanged, the pair shows and no row is flagged."""
    ctd = _ctdcast_file(tmp_path, data_mode="P")
    meta = read_nc_meta(_caldip_nc_with_ref(tmp_path, ctd, recorded_data_mode="P"))
    state = meta["reference_state"]
    assert state["now_available"] is True
    assert not [r["field"] for r in state["rows"] if r["changed"]]


def test_reference_recorded_now_flags_a_change(tmp_path):
    """A reference that advanced P->D marks the data_mode row and the finality gate."""
    ctd = _ctdcast_file(tmp_path, data_mode="D")
    html = build_inventory_html(
        _caldip_nc_with_ref(tmp_path, ctd, recorded_data_mode="P")
    )
    meta = read_nc_meta(_caldip_nc_with_ref(tmp_path, ctd, recorded_data_mode="P"))
    state = meta["reference_state"]
    assert "data_mode" in [r["field"] for r in state["rows"] if r["changed"]]
    assert state["data_mode_final"] is True  # the current reference is delayed-mode
    assert "over-threshold" in html  # the changed row is highlighted
    assert "Reference finished:" in html
