"""Tests for the per-cast statistics netCDF writer (``{cast}_caldip.nc``).

Uses a real caldip statistics CSV as the fixture, augmented with the ``stop``
index, comparison-window timestamps, ``ctd_press`` and per-variable flags that
``core.stats`` emits, so the writer is exercised against real diffs, values and a
temperature-only logger on the two-dimensional ``(instrument, stop)`` grid.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from caldip import _writers as writers

_REAL_CSV = (
    Path(__file__).resolve().parents[1] / "outputs" / "castM6_detailed_statistics.csv"
)
_THRESHOLDS = {"temp": 0.005, "cond": 0.02, "press": 5.0}


def _fixture_frame() -> pd.DataFrame:
    """Load the real castM6 stats and add the columns core.stats emits."""
    df = pd.read_csv(_REAL_CSV)
    df["ctd_press"] = df["bl_press"].astype(float)
    df["stop"] = pd.factorize(df["bl_press"])[0] + 1
    t_start = pd.to_datetime(df["date"] + " " + df["time_start"])
    t_end = pd.to_datetime(df["date"] + " " + df["time_end"])
    df["t_start"] = t_start
    df["t_end"] = t_end
    df["time"] = t_start + (t_end - t_start) / 2
    df["temp_flag"] = np.where(
        df["temp_status"].str.contains("reads", na=False), 3, 1
    ).astype("int8")
    df["cond_flag"] = np.where(
        df["cond_status"].str.contains("NO DATA", na=False), 2, 1
    ).astype("int8")
    df["press_flag"] = np.where(
        df["press_status"].str.contains("NO DATA", na=False), 2, 1
    ).astype("int8")
    return df


_CONFIG = {
    "name": "castM6",
    "cruise": "msm142",
    "ctd_file": "msm_142_1_054_1sec.cnv",
    "ctd_sensor": 2,
    "instruments": [{"filename": "a.mat"}, {"filename": "b.cnv"}],
}


def test_dataset_is_instrument_stop_grid():
    """The Dataset is a 2D (instrument, stop) grid with the right tier per variable."""
    df = _fixture_frame()
    ds = writers.stats_to_dataset(df, _CONFIG, thresholds=_THRESHOLDS)
    assert set(ds.sizes) == {"instrument", "stop"}
    assert ds.sizes["instrument"] == df["serial"].nunique()
    assert ds.sizes["stop"] == df["bl_press"].nunique()
    assert ds["serial"].dims == ("instrument",)
    assert ds["bl_press"].dims == ("stop",)
    assert ds["ctd_temp"].dims == ("stop",)  # per-stop reference, deduplicated
    assert ds["temp_diff"].dims == ("instrument", "stop")  # the grid
    assert "argmax(ctd_press)" in ds["bl_press"].attrs["comment"]


def test_time_coordinate_is_datetime():
    """A real per-stop time coordinate is written, not reassembled strings."""
    ds = writers.stats_to_dataset(_fixture_frame(), _CONFIG, thresholds=_THRESHOLDS)
    assert np.issubdtype(ds["time"].dtype, np.datetime64)
    assert ds["time"].dims == ("stop",)
    assert np.issubdtype(ds["time_start"].dtype, np.datetime64)


def test_variable_units_and_sign_convention():
    """Physical variables carry units and every *_diff states the sign convention."""
    ds = writers.stats_to_dataset(_fixture_frame(), _CONFIG, thresholds=_THRESHOLDS)
    assert ds["temp_diff"].attrs["units"] == "degree_C"
    assert ds["cond_diff"].attrs["units"] == "mS cm-1"
    assert ds["press_diff"].attrs["units"] == "dbar"
    assert ds["ctd_press"].attrs["units"] == "dbar"
    for diff in ("temp_diff", "cond_diff", "press_diff"):
        assert ds[diff].attrs["comment"] == (
            "instrument minus CTD; corrected = measured - diff"
        )


def test_usability_is_a_cf_flag_variable():
    """Usability is encoded as a CF flag variable with values and meanings."""
    ds = writers.stats_to_dataset(_fixture_frame(), _CONFIG, thresholds=_THRESHOLDS)
    assert (
        ds["cond_flag"].attrs["flag_meanings"] == "ok no_data flagged missing unknown"
    )
    np.testing.assert_array_equal(
        ds["cond_flag"].attrs["flag_values"], np.array([1, 2, 3, 4, 9], dtype="int8")
    )


def test_variable_dtypes():
    """Derived diffs are float64; flags int8 (QARTOD shape); bl_press an integer label."""
    ds = writers.stats_to_dataset(_fixture_frame(), _CONFIG, thresholds=_THRESHOLDS)
    assert ds["temp_diff"].dtype == np.float64
    assert ds["ctd_press"].dtype == np.float64
    assert ds["temp_flag"].dtype == np.int8
    assert ds["bl_press"].dtype == np.int16
    assert ds["temp_flag"].attrs["conventions"] == "QARTOD"
    assert int(ds["temp_flag"].attrs["valid_min"]) == 1
    assert int(ds["temp_flag"].attrs["valid_max"]) == 9


def test_temperature_only_logger_conductivity_is_nan_not_zero(tmp_path):
    """An RBR temperature logger has NaN conductivity across all its stops."""
    df = _fixture_frame()
    rbr_serial = str(df[df["instrument_type"] == "rbr"]["serial"].iloc[0])
    out = writers.write_stats_netcdf(
        df, _CONFIG, tmp_path / "castM6_caldip.nc", thresholds=_THRESHOLDS
    )
    with xr.open_dataset(out, engine="netcdf4") as ds:
        serials = ds["serial"].to_numpy().astype(str)
        idx = int(np.where(serials == rbr_serial)[0][0])
        row = ds["cond_diff"].isel(instrument=idx).to_numpy()
        assert bool(np.isnan(row).all())


def test_flag_variable_carries_threshold():
    """The flag variable records the threshold used, so a reader can re-render."""
    ds = writers.stats_to_dataset(_fixture_frame(), _CONFIG, thresholds=_THRESHOLDS)
    assert ds["temp_flag"].attrs["flagging_threshold"] == pytest.approx(0.005)
    assert ds["press_flag"].attrs["flagging_threshold"] == pytest.approx(5.0)


def test_global_attributes_complete_with_unk_where_unsourced():
    """The full attribute block is present; ctdcast-sourced fields are UNK, data_mode P."""
    with pytest.warns(UserWarning, match="unsourced"):
        ds = writers.stats_to_dataset(_fixture_frame(), _CONFIG, thresholds=_THRESHOLDS)
    assert ds.attrs["data_mode"] == "P"
    assert ds.attrs["data_mode_meaning"] == "provisional"
    assert ds.attrs["schema_version"] == 1
    assert ds.attrs["caldip_version"] != "UNK"
    assert ds.attrs["cruise_id"] == "msm142"
    assert ds.attrs["cast_id"] == "castM6"
    assert ds.attrs["ctd_sensor_used"] == "2"
    assert ds.attrs["ctd_temp_processing_level"] == (
        "Instrument data that has been converted to geophysical values"
    )
    for unsourced in (
        "ctd_cond_slope_adjusted",
        "ctd_temp_sensor_serial",
        "source_tracking_id",
        "ctd_stage",
    ):
        assert ds.attrs[unsourced] == "UNK"


def test_source_instrument_files_recorded():
    """The instrument lineage root lists the configured instrument files."""
    ds = writers.stats_to_dataset(_fixture_frame(), _CONFIG, thresholds=_THRESHOLDS)
    assert ds.attrs["source_instrument_files"] == "a.mat b.cnv"


def test_ctd_sensor_used_reads_deprecated_plural_key():
    """ctd_sensor_used resolves the deprecated `ctd_sensors` key, not just `ctd_sensor`."""
    df = _fixture_frame().drop(columns=["ctd_sensor_used"], errors="ignore")
    config = {k: v for k, v in _CONFIG.items() if k != "ctd_sensor"}
    config["ctd_sensors"] = 2  # the deprecated spelling the msm142 configs use
    ds = writers.stats_to_dataset(df, config, thresholds=_THRESHOLDS)
    assert ds.attrs["ctd_sensor_used"] == "2"


def test_date_created_preserved_across_rewrite(tmp_path):
    """date_created is fixed on first write; date_modified and tracking_id change."""
    df = _fixture_frame()
    out = tmp_path / "castM6_caldip.nc"
    writers.write_stats_netcdf(df, _CONFIG, out, thresholds=_THRESHOLDS)
    with xr.open_dataset(out, engine="netcdf4") as first:
        created1, tid1 = first.attrs["date_created"], first.attrs["tracking_id"]
    writers.write_stats_netcdf(df, _CONFIG, out, thresholds=_THRESHOLDS)
    with xr.open_dataset(out, engine="netcdf4") as second:
        assert second.attrs["date_created"] == created1
        assert second.attrs["tracking_id"] != tid1


def test_missing_derived_columns_warns_and_fills():
    """Without stop/ctd_press/flags, the writer warns and fills NaN / unknown, not zero."""
    df = pd.read_csv(_REAL_CSV)  # no stop, ctd_press or flag columns
    with pytest.warns(UserWarning, match="missing"):
        ds = writers.stats_to_dataset(df, _CONFIG)
    assert bool(np.isnan(ds["ctd_press"].to_numpy()).all())
    assert bool((ds["temp_flag"].to_numpy() == 9).all())


_PROSE_COLUMNS = ["temp_status", "cond_status", "press_status"]


def test_exported_csv_matches_today_column_for_column(tmp_path):
    """netCDF -> export CSV reproduces the real detailed CSV, plus 3 provenance columns.

    Prose ``*_status`` columns are excluded from the byte-comparison: the fixture
    already stores rounded diffs, so their prose was rendered from full precision
    the fixture no longer has; the full-precision path is checked separately.
    """
    original = pd.read_csv(_REAL_CSV)
    out = writers.write_stats_netcdf(
        _fixture_frame(), _CONFIG, tmp_path / "castM6_caldip.nc", thresholds=_THRESHOLDS
    )
    with xr.open_dataset(out, engine="netcdf4") as ds:
        exported = writers.stats_dataset_to_frame(ds)

    assert list(exported.columns) == list(original.columns) + [
        "cast_id",
        "schema_version",
        "tracking_id",
    ]

    shared = [c for c in original.columns if c not in _PROSE_COLUMNS]
    exported[shared].to_csv(tmp_path / "exp.csv", index=False)
    reexported = pd.read_csv(tmp_path / "exp.csv")
    pd.testing.assert_frame_equal(reexported, original[shared])

    assert (exported["cast_id"] == "castM6").all()
    assert (exported["schema_version"] == 1).all()


def test_prose_rendered_from_authoritative_diff(tmp_path):
    """Prose is re-rendered from the full-precision diff, not the rounded column."""
    from caldip import core

    full = 0.00751
    assert core._format_status(full, 0.005, "T") != core._format_status(
        round(full, 4), 0.005, "T"
    )
    start = pd.Timestamp("2024-01-01 12:00:00")
    df = pd.DataFrame(
        {
            "serial": ["S1"],
            "instrument_type": ["sbe37"],
            "bl_press": [1000],
            "stop": [1],
            "temp_diff": [full],
            "temp_std": [0.001],
            "cond_diff": [np.nan],
            "cond_std": [np.nan],
            "press_diff": [np.nan],
            "press_std": [np.nan],
            "ctd_temp": [5.0],
            "ctd_cond": [np.nan],
            "ctd_press": [1000.0],
            "inst_temp": [5.00751],
            "inst_cond": [np.nan],
            "inst_press": [np.nan],
            "N": [100],
            "label": ["x"],
            "temp_flag": [3],
            "cond_flag": [4],
            "press_flag": [4],
            "date": ["2024-01-01"],
            "time_start": ["12:00:00"],
            "time_end": ["12:02:00"],
            "time": [start + pd.Timedelta(minutes=1)],
            "t_start": [start],
            "t_end": [start + pd.Timedelta(minutes=2)],
        }
    )
    out = writers.write_stats_netcdf(
        df, _CONFIG, tmp_path / "syn_caldip.nc", thresholds=_THRESHOLDS
    )
    with xr.open_dataset(out, engine="netcdf4") as ds:
        exported = writers.stats_dataset_to_frame(ds)
    assert exported["temp_diff"].iloc[0] == pytest.approx(round(full, 4))
    assert exported["temp_status"].iloc[0] == core._format_status(full, 0.005, "T")
    assert exported["date"].iloc[0] == "2024-01-01"
    assert exported["time_start"].iloc[0] == "12:00:00"
