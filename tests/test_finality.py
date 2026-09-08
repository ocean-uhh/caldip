"""Tests for the per-cruise finality sweep (``caldip report --check``).

Each cast is classified by comparing its config to its output, its output to the
reference file, and the two finality gates (``data_mode = D``, ``preferred_pair``
declared). Only ``final`` is terminal; anything else exits non-zero.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from caldip import _writers as writers
from caldip.readers import read_ctdcast_reference
from caldip.report.finality import (
    FINAL,
    NOT_RUN,
    NO_REFERENCE,
    RERUN,
    WAITING,
    cast_state,
    check_cruise,
)

_THRESHOLDS = {"temp": 0.005, "cond": 0.02, "press": 5.0}


def _ctdcast(tmp_path, data_mode="P", preferred_pair=None, stem="ref"):
    """Write a minimal dual-sensor ctdcast stage-3 nc."""
    n = 4
    time = pd.date_range("2026-04-03T12:00:00", periods=n, freq="1s")
    ones = np.ones(n)
    plevel = "Instrument data that has been converted to geophysical values"
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
    ds["ctd_temperature_2"].attrs.update(
        {
            "sensor": "SENSOR_TEMPERATURE_5808",
            "units": "degree_Celsius",
            "processing_level": plevel,
        }
    )
    ds["conductivity_2"].attrs.update(
        {
            "sensor": "SENSOR_CONDUCTIVITY_2452",
            "units": "mS cm-1",
            "processing_level": plevel,
        }
    )
    ds["pressure"].attrs["processing_level"] = plevel
    for name, serial, caldate in (
        ("SENSOR_TEMPERATURE_5808", "5808", "2019-Apr-09"),
        ("SENSOR_CONDUCTIVITY_2452", "2452", "2017-Aug-18"),
    ):
        ds[name] = xr.DataArray(0)
        ds[name].attrs["sensor_serial_number"] = serial
        ds[name].attrs["sensor_calibration_date"] = caldate
    ds.attrs.update(
        {
            "processing_stage": 3,
            "data_mode": data_mode,
            "cruise": "MSM142",
            "tracking_id": f"tid-{data_mode}",
        }
    )
    if preferred_pair is not None:
        ds.attrs["preferred_pair"] = preferred_pair
    path = tmp_path / f"{stem}_stage3.nc"
    ds.to_netcdf(path, engine="netcdf4")
    return path


def _config(ctd_path, ctd_sensor=2):
    return {
        "name": "castA",
        "cruise": "msm142",
        "ctd_file": Path(ctd_path).name,
        "ctd_sensor": ctd_sensor,
        "instruments": [{}],
    }


def _output(tmp_path, ctd_path, recorded_overrides=None):
    """Write a caldip output nc whose recorded provenance points at ``ctd_path``."""
    with xr.open_dataset(ctd_path, engine="netcdf4") as ds:
        _, prov = read_ctdcast_reference(ds, 2)
    prov = dict(prov)
    prov.update(recorded_overrides or {})
    t0 = pd.Timestamp("2026-04-03 12:00:00")
    df = pd.DataFrame(
        {
            "serial": ["13874"],
            "instrument_type": ["tr1050"],
            "bl_press": [1000],
            "stop": [1],
            "time": [t0],
            "t_start": [t0],
            "t_end": [t0 + pd.Timedelta(minutes=2)],
            "temp_diff": [0.006],
            "temp_std": [0.001],
            "cond_diff": [np.nan],
            "cond_std": [np.nan],
            "press_diff": [np.nan],
            "press_std": [np.nan],
            "ctd_temp": [6.0],
            "ctd_cond": [np.nan],
            "ctd_press": [1000.0],
            "inst_temp": [6.006],
            "inst_cond": [np.nan],
            "inst_press": [np.nan],
            "N": [100],
            "label": ["x"],
            "temp_flag": [1],
            "cond_flag": [2],
            "press_flag": [2],
            "date": ["2026-04-03"],
            "time_start": ["12:00:00"],
            "time_end": ["12:02:00"],
        }
    )
    return writers.write_stats_netcdf(
        df,
        _config(ctd_path),
        tmp_path / "castA_caldip.nc",
        thresholds=_THRESHOLDS,
        input_mode="netcdf",
        ctd_provenance=prov,
        ctd_path=str(ctd_path),
    )


def test_state_not_run(tmp_path):
    """No output netCDF for a cast is 'not run'."""
    ctd = _ctdcast(tmp_path)
    state, _ = cast_state(_config(ctd), None)
    assert state == NOT_RUN


def test_state_waiting_on_reference(tmp_path):
    """Output current with a still-provisional (data_mode P) reference is waiting."""
    ctd = _ctdcast(tmp_path, data_mode="P")
    state, detail = cast_state(_config(ctd), _output(tmp_path, ctd))
    assert state == WAITING
    assert "data_mode not D" in detail


def test_state_final(tmp_path):
    """A finished reference (D + preferred_pair) with a current output is final."""
    ctd = _ctdcast(tmp_path, data_mode="D", preferred_pair="secondary")
    out = _output(
        tmp_path,
        ctd,
        recorded_overrides={"data_mode": "D", "preferred_pair": "secondary"},
    )
    state, _ = cast_state(_config(ctd), out)
    assert state == FINAL


def test_state_rerun_when_reference_advanced(tmp_path):
    """A reference that advanced P->D since the run needs a re-run."""
    ctd = _ctdcast(tmp_path, data_mode="D", preferred_pair="secondary")
    # recorded value is stale (P) while the file has advanced to D
    out = _output(tmp_path, ctd, recorded_overrides={"data_mode": "P"})
    state, detail = cast_state(_config(ctd), out)
    assert state == RERUN
    assert "data_mode" in detail


def test_state_rerun_when_config_repointed(tmp_path):
    """A config re-pointed at a different CTD file needs a re-run."""
    ctd = _ctdcast(tmp_path, data_mode="D", preferred_pair="secondary")
    out = _output(
        tmp_path,
        ctd,
        recorded_overrides={"data_mode": "D", "preferred_pair": "secondary"},
    )
    repointed = _config(ctd)
    repointed["ctd_file"] = "somewhere_else.nc"
    state, detail = cast_state(repointed, out)
    assert state == RERUN
    assert "ctd_file" in detail


def test_check_cruise_sweep_and_exit(tmp_path):
    """check_cruise sweeps a directory of configs; only 'final' avoids action."""
    import yaml

    ctd = _ctdcast(tmp_path, data_mode="P")
    cal_dip = tmp_path / "cal_dip"
    (cal_dip / "castA").mkdir(parents=True)
    (cal_dip / "castA" / "castA.caldip.yaml").write_text(
        yaml.safe_dump(_config(ctd)), encoding="utf-8"
    )
    _output(cal_dip, ctd)  # {cast}_caldip.nc beside the cast dir's parent
    results = check_cruise(cal_dip)
    assert len(results) == 1
    cast, state, _ = results[0]
    assert cast == "castA" and state == WAITING
    assert any(s != FINAL for _, s, _ in results)  # would exit non-zero


def test_state_no_reference_on_cnv_output(tmp_path):
    """A .cnv-sourced output (no ctdcast provenance) is 'no reference'."""
    t0 = pd.Timestamp("2026-04-03 12:00:00")
    df = pd.DataFrame(
        {
            "serial": ["13874"],
            "instrument_type": ["tr1050"],
            "bl_press": [1000],
            "stop": [1],
            "time": [t0],
            "t_start": [t0],
            "t_end": [t0 + pd.Timedelta(minutes=2)],
            "temp_diff": [0.006],
            "temp_std": [0.001],
            "cond_diff": [np.nan],
            "cond_std": [np.nan],
            "press_diff": [np.nan],
            "press_std": [np.nan],
            "ctd_temp": [6.0],
            "ctd_cond": [np.nan],
            "ctd_press": [1000.0],
            "inst_temp": [6.006],
            "inst_cond": [np.nan],
            "inst_press": [np.nan],
            "N": [100],
            "label": ["x"],
            "temp_flag": [1],
            "cond_flag": [2],
            "press_flag": [2],
            "date": ["2026-04-03"],
            "time_start": ["12:00:00"],
            "time_end": ["12:02:00"],
        }
    )
    cfg = {
        "name": "castA",
        "cruise": "msm142",
        "ctd_file": "x.cnv",
        "ctd_sensor": 2,
        "instruments": [{}],
    }
    out = writers.write_stats_netcdf(
        df, cfg, tmp_path / "castA_caldip.nc", thresholds=_THRESHOLDS
    )
    ds = xr.open_dataset(out, engine="netcdf4")
    assert ds.attrs["data_mode"] == "P" and ds.attrs["ctd_stage"] == "UNK"
    state, _ = cast_state(cfg, out)
    assert state == NO_REFERENCE
