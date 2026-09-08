"""Tests for reading a ctdcast per-cast stage netCDF as the CTD reference.

Synthetic ctdcast-shaped datasets are used (acceptable for reader/parsing logic):
dual-sensor ``ctd_temperature_{1,2}`` / ``conductivity_{1,2}``, a ``pressure``,
per-variable ``_qc`` companions, a ``SENSOR_<TYPE>_<SERIAL>`` catalog linked via
each variable's ``sensor`` attribute, and the global provenance attributes. A
real-file integration test against ``msm_142_1_032_1sec_stage3.nc`` is a follow-up
(the file is 1.2 MB and lives outside the repo).
"""

import warnings

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from caldip import _writers as writers
from caldip.readers import (
    _is_ctdcast_nc,
    _normalize_conductivity,
    read_ctdcast_reference,
)

_THRESHOLDS = {"temp": 0.005, "cond": 0.02, "press": 5.0}
_CFG = {"name": "castM4", "cruise": "msm142", "ctd_sensor": 2, "instruments": [{}]}


def _stats_frame():
    """A one-instrument, one-stop stats frame for write_stats_netcdf."""
    t0 = pd.Timestamp("2026-04-03 12:00:00")
    return pd.DataFrame(
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
            "label": ["TR1050"],
            "temp_flag": [1],
            "cond_flag": [2],
            "press_flag": [2],
            "date": ["2026-04-03"],
            "time_start": ["12:00:00"],
            "time_end": ["12:02:00"],
        }
    )


def _ctdcast_ds(stage=3, data_mode="P", cruise="MSM142", slope=None, temp2_qc=None):
    """Build a small dual-sensor ctdcast-shaped stage dataset."""
    n = 5
    time = pd.date_range("2026-04-03T12:00:00", periods=n, freq="1s")
    ones = np.ones(n)
    ds = xr.Dataset(
        {
            "ctd_temperature_1": ("time", 5.0 * ones),
            "ctd_temperature_2": ("time", 6.0 * ones),
            "conductivity_1": ("time", 30.0 * ones),
            "conductivity_2": ("time", 31.0 * ones),
            "pressure": ("time", 1000.0 * ones),
            "ctd_temperature_2_qc": (
                "time",
                np.ones(n, dtype="int8") if temp2_qc is None else temp2_qc,
            ),
        },
        coords={"time": time},
    )
    ds["ctd_temperature_1"].attrs["sensor"] = "SENSOR_TEMPERATURE_1111"
    ds["ctd_temperature_2"].attrs["sensor"] = "SENSOR_TEMPERATURE_5808"
    ds["conductivity_1"].attrs["sensor"] = "SENSOR_CONDUCTIVITY_3333"
    ds["conductivity_2"].attrs["sensor"] = "SENSOR_CONDUCTIVITY_2452"
    if slope is not None:
        ds["conductivity_2"].attrs["calibration_slope"] = slope
    for name, serial, caldate in (
        ("SENSOR_TEMPERATURE_1111", "1111", "2020-Jan-01"),
        ("SENSOR_TEMPERATURE_5808", "5808", "2019-Apr-09"),
        ("SENSOR_CONDUCTIVITY_3333", "3333", "2020-Feb-02"),
        ("SENSOR_CONDUCTIVITY_2452", "2452", "2017-Aug-18"),
    ):
        ds[name] = xr.DataArray(0)
        ds[name].attrs["sensor_serial_number"] = serial
        ds[name].attrs["sensor_calibration_date"] = caldate
    ds.attrs.update(
        {
            "processing_stage": stage,
            "data_mode": data_mode,
            "cruise": cruise,
            "tracking_id": "11111111-2222-3333-4444-555555555555",
        }
    )
    return ds


def test_is_ctdcast_nc_discriminates():
    """A ctdcast stage nc is recognised; a caldip cache (canonical vars) is not."""
    assert _is_ctdcast_nc(_ctdcast_ds()) is True
    cache = xr.Dataset({"temperature": ("time", [5.0])}, coords={"time": [0]})
    cache.attrs["ctd_sensor"] = 2
    assert _is_ctdcast_nc(cache) is False


@pytest.mark.parametrize(
    ("sensor", "temp", "cond", "serial_t", "serial_c"),
    [(1, 5.0, 30.0, "1111", "3333"), (2, 6.0, 31.0, "5808", "2452")],
)
def test_sensor_selection(sensor, temp, cond, serial_t, serial_c):
    """ctd_sensor selects the matching temperature/conductivity pair and serials."""
    out, prov = read_ctdcast_reference(_ctdcast_ds(), ctd_sensor=sensor)
    assert set(out.data_vars) == {"temperature", "conductivity", "pressure"}
    assert float(out["temperature"].mean()) == pytest.approx(temp)
    assert float(out["conductivity"].mean()) == pytest.approx(cond)
    assert prov["ctd_temp_sensor_serial"] == serial_t
    assert prov["ctd_cond_sensor_serial"] == serial_c


def test_provenance_stage_and_data_mode():
    """ctd_stage copies processing_stage; data_mode is D only when the file is D."""
    _, prov_p = read_ctdcast_reference(_ctdcast_ds(stage=3, data_mode="P"), 2)
    assert prov_p["ctd_stage"] == "3" and prov_p["data_mode"] == "P"
    _, prov_d = read_ctdcast_reference(_ctdcast_ds(stage=3, data_mode="D"), 2)
    assert prov_d["data_mode"] == "D"


def test_conductivity_slope_present_and_absent():
    """calibration_slope drives ctd_conductivity_slope and the adjusted flag."""
    _, absent = read_ctdcast_reference(_ctdcast_ds(slope=None), 2)
    assert absent["ctd_conductivity_slope"] == "UNK"
    assert absent["ctd_cond_slope_adjusted"] == "false"
    _, present = read_ctdcast_reference(_ctdcast_ds(slope=1.0002), 2)
    assert present["ctd_conductivity_slope"] == "1.0002"
    assert present["ctd_cond_slope_adjusted"] == "true"


def test_cruise_verbatim_and_disagreement_warning():
    """Cruise is copied verbatim; a case-only difference does not warn."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # msm142 vs MSM142 agree case-insensitively
        _, prov = read_ctdcast_reference(
            _ctdcast_ds(cruise="MSM142"), 2, config={"cruise": "msm142"}
        )
    assert prov["cruise"] == "MSM142"  # verbatim, not normalised
    with pytest.warns(UserWarning, match="cruise disagreement"):
        read_ctdcast_reference(
            _ctdcast_ds(cruise="MSM142"), 2, config={"cruise": "dy174"}
        )


def test_qc_fail_is_masked():
    """A QARTOD fail (4) on the selected temperature masks that sample to NaN."""
    qc = np.array([1, 1, 4, 1, 1], dtype="int8")
    out, _ = read_ctdcast_reference(_ctdcast_ds(temp2_qc=qc), ctd_sensor=2)
    # One sample masked; the rest are the constant 6.0.
    assert int(np.isnan(out["temperature"].values).sum()) == 1


def test_provenance_fills_netcdf_attributes(tmp_path):
    """Provenance from the reader fills the ctd_* / cruise / data_mode nc attrs."""
    _, prov = read_ctdcast_reference(_ctdcast_ds(), ctd_sensor=2)
    out = writers.write_stats_netcdf(
        _stats_frame(),
        _CFG,
        tmp_path / "castM4_caldip.nc",
        thresholds=_THRESHOLDS,
        input_mode="netcdf",
        ctd_provenance=prov,
    )
    ds = xr.open_dataset(out, engine="netcdf4")
    assert ds.attrs["ctd_stage"] == "3"
    assert ds.attrs["data_mode"] == "P"
    assert ds.attrs["cruise"] == "MSM142"  # verbatim from the ctdcast file
    assert ds.attrs["ctd_temp_sensor_serial"] == "5808"
    assert ds.attrs["ctd_cond_sensor_serial"] == "2452"
    assert ds.attrs["source_tracking_id"] != "UNK"
    assert ds.attrs["cast_id"] == "castM4"  # unchanged in this branch


def test_data_mode_meaning_is_derived_not_stale():
    """data_mode_meaning tracks data_mode after the provenance overlay."""
    df = _stats_frame()
    for mode, meaning in (("P", "provisional"), ("D", "delayed-mode")):
        _, prov = read_ctdcast_reference(_ctdcast_ds(data_mode=mode), ctd_sensor=2)
        out = writers.write_stats_netcdf(
            df,
            _CFG,
            __import__("tempfile").mktemp(suffix=".nc"),
            thresholds=_THRESHOLDS,
            input_mode="netcdf",
            ctd_provenance=prov,
        )
        ds = xr.open_dataset(out, engine="netcdf4")
        assert ds.attrs["data_mode"] == mode
        assert ds.attrs["data_mode_meaning"] == meaning


def test_unk_provenance_does_not_clobber_config_cruise(tmp_path):
    """A ctdcast file with no cruise attr must not blank the config's cruise."""
    ds_no_cruise = _ctdcast_ds()
    del ds_no_cruise.attrs["cruise"]
    _, prov = read_ctdcast_reference(ds_no_cruise, ctd_sensor=2)
    assert prov["cruise"] == "UNK"  # nothing to source from the file
    out = writers.write_stats_netcdf(
        _stats_frame(),
        {"name": "castM4", "cruise": "msm142", "ctd_sensor": 2, "instruments": [{}]},
        tmp_path / "castM4_caldip.nc",
        thresholds=_THRESHOLDS,
        input_mode="netcdf",
        ctd_provenance=prov,
    )
    ds = xr.open_dataset(out, engine="netcdf4")
    assert ds.attrs["cruise"] == "msm142"  # config value survived, not UNK


def test_single_sensor_fallback_records_actual_sensor_and_warns():
    """Requesting sensor 2 on a single-sensor file warns and records sensor 1."""
    time = pd.date_range("2026-04-03T12:00:00", periods=3, freq="1s")
    ds = xr.Dataset(
        {
            "ctd_temperature": ("time", [5.0, 5.0, 5.0]),
            "conductivity": ("time", [30.0, 30.0, 30.0]),
            "pressure": ("time", [1000.0, 1000.0, 1000.0]),
        },
        coords={"time": time},
    )
    ds.attrs.update({"processing_stage": 1, "data_mode": "P", "cruise": "MSM142"})
    with pytest.warns(UserWarning, match="single-sensor"):
        _, prov = read_ctdcast_reference(ds, ctd_sensor=2)
    assert prov["ctd_sensor_used"] == "1"  # what was used, not what was requested


def test_qc_flags_honoured_false_when_no_qc_companion():
    """qc_flags_honoured reflects whether any masking actually ran."""
    ds = _ctdcast_ds()
    del ds["ctd_temperature_2_qc"]  # no qc companion for the selected sensor
    _, prov = read_ctdcast_reference(ds, ctd_sensor=2)
    assert prov["qc_flags_honoured"] == "false"
    assert prov["qc_masked_flag_values"] == "UNK"


@pytest.mark.parametrize(
    ("unit", "expect_scaled"),
    [("S m-1", True), (" Siemens/meter ", True), ("mS cm-1", False), ("mS/cm", False)],
)
def test_normalize_conductivity_units_driven(unit, expect_scaled):
    """S/m variants convert x10; mS/cm variants are left as is, both silently."""
    ds = xr.Dataset({"conductivity": ("t", np.array([3.0]))})
    ds["conductivity"].attrs["units"] = unit
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # recognised units must not warn
        out = _normalize_conductivity(ds)
    expected = 30.0 if expect_scaled else 3.0
    assert float(out["conductivity"][0]) == pytest.approx(expected)


def test_normalize_conductivity_warns_on_unknown_unit():
    """A non-empty unrecognised unit warns rather than silently assuming mS/cm."""
    ds = xr.Dataset({"conductivity": ("t", np.array([3.0]))})
    ds["conductivity"].attrs["units"] = "microS/cm"
    with pytest.warns(UserWarning, match="unrecognised units"):
        out = _normalize_conductivity(ds)
    assert float(out["conductivity"][0]) == pytest.approx(3.0)  # left unconverted


def test_every_provenance_key_is_a_seeded_nc_attribute(tmp_path):
    """Guard the seed/overlay coupling: no provenance key silently vanishes.

    The overlay in ``_global_attrs`` only applies keys already seeded in the
    attribute block, so a provenance field added in ``read_ctdcast_reference``
    but not seeded there would be dropped without error. This asserts every
    provenance key is a written attribute, failing CI on that drift.
    """
    _, prov = read_ctdcast_reference(_ctdcast_ds(slope=1.0002), ctd_sensor=2)
    out = writers.write_stats_netcdf(
        _stats_frame(),
        _CFG,
        tmp_path / "castM4_caldip.nc",
        thresholds=_THRESHOLDS,
        input_mode="netcdf",
        ctd_provenance=prov,
    )
    ds = xr.open_dataset(out, engine="netcdf4")
    missing = [k for k in prov if k not in ds.attrs]
    assert not missing, f"provenance keys not seeded in _global_attrs: {missing}"


def test_preferred_pair_read_from_file_and_recorded(tmp_path):
    """preferred_pair is copied from the ctdcast file (undeclared until it ships)."""
    ds = _ctdcast_ds()
    _, prov = read_ctdcast_reference(ds, ctd_sensor=2)
    assert prov["preferred_pair"] == "undeclared"  # fixture has no such attr yet
    ds.attrs["preferred_pair"] = "secondary"
    _, prov2 = read_ctdcast_reference(ds, ctd_sensor=2)
    assert prov2["preferred_pair"] == "secondary"
    out = writers.write_stats_netcdf(
        _stats_frame(),
        _CFG,
        tmp_path / "castM4_caldip.nc",
        thresholds=_THRESHOLDS,
        input_mode="netcdf",
        ctd_provenance=prov2,
    )
    assert xr.open_dataset(out, engine="netcdf4").attrs["preferred_pair"] == "secondary"


def test_config_digest_ignores_cosmetics_tracks_clock_offset():
    """config_digest is stable to comment/label/depth but changes on clock_offset."""
    from caldip._writers import _config_digest

    base = {
        "instruments": [
            {
                "serial": "13874",
                "instrument": "tr1050",
                "file_type": "rbr-matlab-legacy",
                "filename": "a.mat",
                "clock_offset": 7175,
            },
        ]
    }
    cosmetic = {
        "instruments": [
            {
                "serial": "13874",
                "instrument": "tr1050",
                "file_type": "rbr-matlab-legacy",
                "filename": "a.mat",
                "clock_offset": 7175,
                "label": "x",
                "depth": 0,
            },
        ]
    }
    shifted = {
        "instruments": [
            {
                "serial": "13874",
                "instrument": "tr1050",
                "file_type": "rbr-matlab-legacy",
                "filename": "a.mat",
                "clock_offset": 9999,
            },
        ]
    }
    assert _config_digest(base) == _config_digest(cosmetic)
    assert _config_digest(base) != _config_digest(shifted)


def test_config_digest_written_to_netcdf(tmp_path):
    """Every output carries a config_digest attribute (both input paths)."""
    _, prov = read_ctdcast_reference(_ctdcast_ds(), ctd_sensor=2)
    out = writers.write_stats_netcdf(
        _stats_frame(),
        _CFG,
        tmp_path / "castM4_caldip.nc",
        thresholds=_THRESHOLDS,
        input_mode="netcdf",
        ctd_provenance=prov,
    )
    digest = xr.open_dataset(out, engine="netcdf4").attrs["config_digest"]
    assert len(digest) == 16 and digest != "UNK"
