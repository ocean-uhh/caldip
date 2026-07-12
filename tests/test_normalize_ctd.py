"""Tests for CTD variable normalization, wild-edit, and resample pipeline."""

import numpy as np
import pandas as pd
import xarray as xr

from caldip.readers import (
    _normalize_ctd_vars,
    _wild_edit_ctd,
    _resample_1hz,
)


def _make_ds(variables: dict, freq_s: float = 1.0) -> xr.Dataset:
    """Build a minimal xr.Dataset with a time coordinate inferred from the first variable."""
    n = len(next(iter(variables.values())))
    start = pd.Timestamp("2026-07-11")
    times = pd.DatetimeIndex(
        [start + pd.Timedelta(seconds=i * freq_s) for i in range(n)]
    )
    data_vars = {k: xr.DataArray(v, dims=["time"]) for k, v in variables.items()}
    return xr.Dataset(data_vars, coords={"time": times})


# ---------------------------------------------------------------------------
# _normalize_ctd_vars
# ---------------------------------------------------------------------------


class TestNormalizeCTDVars:
    def test_renames_t090C_to_temperature(self):
        ds = _make_ds({"t090C": np.full(10, 5.0)})
        out = _normalize_ctd_vars(ds)
        assert "temperature" in out.data_vars
        assert "t090C" not in out.data_vars

    def test_renames_prDM_to_pressure(self):
        ds = _make_ds({"prDM": np.full(10, 100.0)})
        out = _normalize_ctd_vars(ds)
        assert "pressure" in out.data_vars
        assert "prDM" not in out.data_vars

    def test_renames_sal00_to_salinity(self):
        ds = _make_ds({"sal00": np.full(10, 35.0)})
        out = _normalize_ctd_vars(ds)
        assert "salinity" in out.data_vars
        assert "sal00" not in out.data_vars

    def test_converts_c0Sm_to_mScm(self):
        ds = _make_ds({"c0S/m": np.full(10, 3.5)})
        out = _normalize_ctd_vars(ds)
        assert "conductivity" in out.data_vars
        np.testing.assert_allclose(out["conductivity"].values, 35.0)

    def test_no_conversion_for_c0mScm(self):
        ds = _make_ds({"c0mS/cm": np.full(10, 35.0)})
        out = _normalize_ctd_vars(ds)
        assert "conductivity" in out.data_vars
        np.testing.assert_allclose(out["conductivity"].values, 35.0)

    def test_prefers_mScm_over_Sm(self):
        """c0mS/cm listed before c0S/m — no conversion should happen."""
        ds = _make_ds({"c0mS/cm": np.full(10, 35.0), "c0S/m": np.full(10, 3.5)})
        out = _normalize_ctd_vars(ds)
        np.testing.assert_allclose(out["conductivity"].values, 35.0)

    def test_unknown_vars_pass_through(self):
        ds = _make_ds({"scan": np.arange(10.0), "flag": np.zeros(10)})
        out = _normalize_ctd_vars(ds)
        assert "scan" in out.data_vars
        assert "flag" in out.data_vars

    def test_already_canonical_left_alone(self):
        ds = _make_ds({"temperature": np.full(10, 5.0)})
        out = _normalize_ctd_vars(ds)
        assert "temperature" in out.data_vars
        np.testing.assert_array_equal(out["temperature"].values, 5.0)

    def test_oxygen_renamed(self):
        ds = _make_ds({"sbeox0ML/L": np.full(10, 6.0)})
        out = _normalize_ctd_vars(ds)
        assert "oxygen" in out.data_vars

    def test_sensor2_prefers_t190C(self):
        ds = _make_ds({"t090C": np.full(10, 5.0), "t190C": np.full(10, 5.1)})
        out = _normalize_ctd_vars(ds, ctd_sensor=2)
        np.testing.assert_allclose(out["temperature"].values, 5.1)

    def test_sensor2_falls_back_to_t090C_if_no_secondary(self):
        ds = _make_ds({"t090C": np.full(10, 5.0)})
        out = _normalize_ctd_vars(ds, ctd_sensor=2)
        assert "temperature" in out.data_vars
        np.testing.assert_allclose(out["temperature"].values, 5.0)

    def test_full_sbe9_dataset(self):
        ds = _make_ds(
            {
                "t090C": np.full(10, 5.0),
                "c0S/m": np.full(10, 3.5),
                "prDM": np.full(10, 100.0),
                "sal00": np.full(10, 35.0),
                "sbeox0ML/L": np.full(10, 6.0),
                "scan": np.arange(10.0),
            }
        )
        out = _normalize_ctd_vars(ds)
        for canonical in [
            "temperature",
            "conductivity",
            "pressure",
            "salinity",
            "oxygen",
        ]:
            assert canonical in out.data_vars
        assert "scan" in out.data_vars
        np.testing.assert_allclose(out["conductivity"].values, 35.0)  # 3.5 S/m × 10


# ---------------------------------------------------------------------------
# _wild_edit_ctd
# ---------------------------------------------------------------------------


class TestWildEditCTD:
    def _config(self, max_pressure=None):
        return {"max_pressure": max_pressure}

    def test_no_bad_samples_unchanged(self):
        ds = _make_ds(
            {
                "pressure": np.full(10, 100.0),
                "temperature": np.full(10, 5.0),
                "salinity": np.full(10, 35.0),
            }
        )
        out = _wild_edit_ctd(ds, self._config())
        assert not np.any(np.isnan(out["temperature"].values))

    def test_negative_pressure_masked(self):
        p = np.array([-1.0] + [100.0] * 9)
        ds = _make_ds({"pressure": p, "temperature": np.full(10, 5.0)})
        out = _wild_edit_ctd(ds, self._config())
        assert np.isnan(out["temperature"].values[0])
        assert not np.any(np.isnan(out["temperature"].values[1:]))

    def test_max_pressure_masks_deep(self):
        p = np.array([100.0] * 9 + [2000.0])
        ds = _make_ds({"pressure": p, "temperature": np.full(10, 5.0)})
        out = _wild_edit_ctd(ds, self._config(max_pressure=1500))
        assert np.isnan(out["temperature"].values[-1])

    def test_high_temperature_masked(self):
        t = np.array([41.0] + [5.0] * 9)
        ds = _make_ds({"pressure": np.full(10, 100.0), "temperature": t})
        out = _wild_edit_ctd(ds, self._config())
        assert np.isnan(out["pressure"].values[0])

    def test_low_temperature_masked(self):
        t = np.array([-4.0] + [5.0] * 9)
        ds = _make_ds({"pressure": np.full(10, 100.0), "temperature": t})
        out = _wild_edit_ctd(ds, self._config())
        assert np.isnan(out["pressure"].values[0])

    def test_high_salinity_masked(self):
        s = np.array([43.0] + [35.0] * 9)
        ds = _make_ds(
            {
                "pressure": np.full(10, 100.0),
                "temperature": np.full(10, 5.0),
                "salinity": s,
            }
        )
        out = _wild_edit_ctd(ds, self._config())
        assert np.isnan(out["temperature"].values[0])

    def test_missing_pressure_skipped(self):
        ds = _make_ds({"temperature": np.full(10, 5.0)})
        out = _wild_edit_ctd(ds, self._config(max_pressure=1500))
        assert not np.any(np.isnan(out["temperature"].values))

    def test_all_bad_all_nan(self):
        p = np.full(10, -5.0)
        ds = _make_ds({"pressure": p, "temperature": np.full(10, 5.0)})
        out = _wild_edit_ctd(ds, self._config())
        assert np.all(np.isnan(out["temperature"].values))


# ---------------------------------------------------------------------------
# _resample_1hz
# ---------------------------------------------------------------------------


class TestResample1Hz:
    def test_24hz_downsampled(self):
        n = 24 * 60  # 1 minute at 24 Hz
        ds = _make_ds({"temperature": np.random.rand(n)}, freq_s=1 / 24)
        out = _resample_1hz(ds)
        assert len(out.time) == 60

    def test_already_1hz_unchanged(self):
        ds = _make_ds({"temperature": np.arange(60.0)}, freq_s=1.0)
        out = _resample_1hz(ds)
        assert len(out.time) == 60

    def test_median_used(self):
        """Two 24 Hz samples per second: [1, 3] → median 2."""
        times = pd.to_datetime(["2026-07-11 00:00:00.000", "2026-07-11 00:00:00.500"])
        ds = xr.Dataset(
            {"temperature": xr.DataArray([1.0, 3.0], dims=["time"])},
            coords={"time": times},
        )
        out = _resample_1hz(ds)
        assert len(out.time) == 1
        np.testing.assert_allclose(out["temperature"].values[0], 2.0)


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class TestNormalizePipeline:
    def test_full_pipeline_produces_canonical_vars(self):
        n = 240  # 10 seconds at 24 Hz
        ds = _make_ds(
            {
                "t090C": np.full(n, 5.0),
                "c0S/m": np.full(n, 3.5),
                "prDM": np.full(n, 100.0),
                "sal00": np.full(n, 35.0),
            },
            freq_s=1 / 24,
        )

        ds = _normalize_ctd_vars(ds)
        ds = _wild_edit_ctd(ds, {"max_pressure": 1500})
        ds = _resample_1hz(ds)

        assert "temperature" in ds.data_vars
        assert "conductivity" in ds.data_vars
        assert "pressure" in ds.data_vars
        assert "salinity" in ds.data_vars
        assert len(ds.time) == 10
        np.testing.assert_allclose(ds["conductivity"].values, 35.0)

    def test_pipeline_masks_propagate(self):
        n = 240
        temp = np.full(n, 5.0)
        temp[0:24] = 50.0  # first second — bad temperature
        ds = _make_ds(
            {
                "t090C": temp,
                "prDM": np.full(n, 100.0),
            },
            freq_s=1 / 24,
        )

        ds = _normalize_ctd_vars(ds)
        ds = _wild_edit_ctd(ds, {})
        ds = _resample_1hz(ds)

        assert np.isnan(ds["temperature"].values[0])
        assert not np.any(np.isnan(ds["temperature"].values[1:]))
