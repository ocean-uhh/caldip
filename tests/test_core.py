"""
Unit tests for caldip/core.py functionality.
"""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from caldip import core as cf


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
            "temp": (
                "time",
                np.full(1000, 15.0) + np.random.default_rng(0).normal(0, 0.01, 1000),
            ),
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


def test_stats_workflow():
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
                        np.full(1000, 15.0)
                        + np.random.default_rng(0).normal(0, 0.01, 1000),
                    ),
                    "cond": (
                        "time",
                        np.full(1000, 35.0)
                        + np.random.default_rng(0).normal(0, 0.1, 1000),
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
                    "pressure": ("time", pressure),
                    "temperature": (
                        "time",
                        np.full(1000, 15.05)
                        + np.random.default_rng(0).normal(0, 0.005, 1000),
                    ),
                    "conductivity": (
                        "time",
                        np.full(1000, 35.05)
                        + np.random.default_rng(0).normal(0, 0.05, 1000),
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
    detailed_stats_df = cf.stats(instruments, reference_data, config)

    # Should return a DataFrame with results
    assert not detailed_stats_df.empty
    assert len(detailed_stats_df) > 0

    # Check expected columns exist
    expected_cols = ["serial", "instrument_type", "temp_diff", "N"]
    for col in expected_cols:
        assert col in detailed_stats_df.columns


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


def test_find_bottle_stops_multiple_stops():
    """Multiple bottle stops are detected and all exceed minimum duration."""
    # Between stops and on ascent use steep transitions (>10 dbar/min per sample)
    # so the sample-to-sample rate exceeds the threshold and stops are kept separate.
    # Transition between stops is 20 samples (> 10-sample merge threshold)
    times = pd.date_range("2024-01-01 12:00:00", periods=1130, freq="1s")
    pressure = np.concatenate(
        [
            np.linspace(0, 90, 200),  # descent
            np.full(400, 100),  # first stop ~6.5 min at 100 dbar
            np.linspace(
                100, 60, 20
            ),  # fast drop (120 dbar/min >> 10 threshold, 20-sample gap)
            np.full(400, 60),  # second stop ~6.5 min at 60 dbar
            np.linspace(60, 0, 110),  # fast ascent (33 dbar/min >> 10 threshold)
        ]
    )
    ctd_data = xr.Dataset({"prDM": ("time", pressure)}, coords={"time": times})

    bottle_stops = cf.find_bottle_stops(ctd_data)

    assert len(bottle_stops) >= 2
    pressures = [s["pressure"] for s in bottle_stops]
    assert max(pressures) == pytest.approx(100, abs=5)
    assert min(pressures) == pytest.approx(60, abs=5)


def test_find_bottle_stops_trailing_nan_pressure():
    """A trailing NaN pressure sample (e.g. from wild-edit masking a genuine
    negative-pressure reading near surface recovery) must not break detection of
    the real bottle stops earlier in the cast. Regression test for a bug where
    np.argmax picked the NaN's own index as the "deepest" point (since any
    comparison against NaN is False, argmax still returns an index - here, the
    last one before it, by np.argmax's left-to-right tie-breaking once every
    other comparison evaluates False), collapsing the deep-enough search window
    to empty and silently returning zero stops for an otherwise normal cast.
    """
    times = pd.date_range("2024-01-01 12:00:00", periods=1001, freq="1s")

    pressure = np.concatenate(
        [
            np.linspace(0, 90, 300),  # descent to 90m
            np.full(400, 100),  # stop at 100m for 6+ minutes
            np.linspace(100, 0, 300),  # ascent
            [np.nan],  # trailing NaN, e.g. a wild-edited negative-pressure sample
        ]
    )

    ctd_data = xr.Dataset({"prDM": ("time", pressure)}, coords={"time": times})

    bottle_stops = cf.find_bottle_stops(ctd_data)

    assert len(bottle_stops) >= 1
    assert bottle_stops[0]["pressure"] == pytest.approx(100, abs=5)


def test_find_bottle_stops_all_nan_pressure():
    """All-NaN pressure must return an empty list, not raise."""
    times = pd.date_range("2024-01-01 12:00:00", periods=100, freq="1s")
    pressure = np.full(100, np.nan)
    ctd_data = xr.Dataset({"prDM": ("time", pressure)}, coords={"time": times})

    bottle_stops = cf.find_bottle_stops(ctd_data)
    assert bottle_stops == []


def test_stats_for_time_period_basic():
    """Stats are calculated correctly over a simple time window."""
    times = pd.date_range("2024-01-01 12:00:00", periods=300, freq="1s")
    data = xr.Dataset(
        {
            "temperature": ("time", np.full(300, 5.0)),
            "pressure": ("time", np.full(300, 100.0)),
        },
        coords={"time": times},
    )

    # Derive start/end from the data timestamps to avoid timezone offset issues
    start_time = pd.Timestamp(times[60])
    end_time = pd.Timestamp(times[180])

    stats = cf.stats_for_time_period(
        data,
        start_time=start_time,
        end_time=end_time,
        variables=["temperature", "pressure"],
    )

    assert stats["mean_temperature"] == pytest.approx(5.0)
    assert stats["mean_pressure"] == pytest.approx(100.0)
    assert stats["std_temperature"] == pytest.approx(0.0, abs=1e-10)
    assert stats["n_samples"] > 0


def test_stats_for_time_period_no_overlap():
    """Returns NaN means when time window has no data."""
    times = pd.date_range("2024-01-01 12:00:00", periods=60, freq="1s")
    data = xr.Dataset(
        {"temperature": ("time", np.full(60, 5.0))}, coords={"time": times}
    )

    stats = cf.stats_for_time_period(
        data,
        start_time=pd.Timestamp("2024-01-01 14:00:00"),
        end_time=pd.Timestamp("2024-01-01 14:05:00"),
        variables=["temperature"],
    )

    assert stats["n_samples"] == 0
    assert np.isnan(stats["mean_temperature"])


def test_format_status_reads_high():
    """Instrument that reads above CTD triggers the 'reads high' branch."""
    times = pd.date_range("2024-01-01 12:00:00", periods=1000, freq="1s")
    pressure = np.concatenate(
        [
            np.linspace(0, 90, 400),
            np.full(200, 100),
            np.linspace(100, 0, 400),
        ]
    )
    # Instrument temperature is HIGHER than CTD — triggers format_status "reads high"
    instruments = {
        "S001": {
            "data": xr.Dataset(
                {
                    "temperature": ("time", np.full(1000, 15.10)),
                },
                coords={"time": times},
            ),
            "config": {"instrument": "microcat", "label": "Test"},
            "type": "sbe37",
        }
    }
    reference_data = {
        "ctd": {
            "data": xr.Dataset(
                {
                    "pressure": ("time", pressure),
                    "temperature": ("time", np.full(1000, 15.00)),
                    "conductivity": ("time", np.full(1000, 34.5)),
                },
                coords={"time": times},
            ),
            "config": {},
        }
    }
    df = cf.stats(instruments, reference_data, {"name": "test"})
    assert not df.empty


def test_stats_emits_ctd_press_and_usability_flags():
    """stats() emits ctd_press and numeric flags: flagged temperature, missing conductivity."""
    times = pd.date_range("2024-01-01 12:00:00", periods=1000, freq="1s")
    pressure = np.concatenate(
        [np.linspace(0, 90, 400), np.full(200, 100), np.linspace(100, 0, 400)]
    )
    # Temperature-only logger reading well above CTD: temp flagged, no conductivity sensor.
    instruments = {
        "S001": {
            "data": xr.Dataset(
                {"temperature": ("time", np.full(1000, 15.10))},
                coords={"time": times},
            ),
            "config": {"instrument": "rbrsolo", "label": "Test"},
            "type": "rbr",
        }
    }
    reference_data = {
        "ctd": {
            "data": xr.Dataset(
                {
                    "pressure": ("time", pressure),
                    "temperature": ("time", np.full(1000, 15.00)),
                    "conductivity": ("time", np.full(1000, 34.5)),
                },
                coords={"time": times},
            ),
            "config": {},
        }
    }
    row = cf.stats(instruments, reference_data, {"name": "test"}).iloc[0]
    assert row["ctd_press"] == pytest.approx(100, abs=2)
    assert row["temp_flag"] == 3  # flagged: reads high beyond threshold
    assert row["cond_flag"] == 4  # missing: RBR has no conductivity sensor
    assert row["press_flag"] == 4  # missing: RBR has no pressure sensor


def test_cond_flag_is_no_data_when_ctd_lacks_conductivity():
    """An instrument with a conductivity sensor but no CTD reference is no_data, not missing."""
    times = pd.date_range("2024-01-01 12:00:00", periods=1000, freq="1s")
    pressure = np.concatenate(
        [np.linspace(0, 90, 400), np.full(200, 100), np.linspace(100, 0, 400)]
    )
    instruments = {
        "S001": {
            "data": xr.Dataset(
                {
                    "temperature": ("time", np.full(1000, 15.0)),
                    "conductivity": ("time", np.full(1000, 35.0)),
                },
                coords={"time": times},
            ),
            "config": {"instrument": "microcat", "label": "Test"},
            "type": "sbe37",
        }
    }
    reference_data = {
        "ctd": {
            "data": xr.Dataset(
                {
                    "pressure": ("time", pressure),
                    "temperature": ("time", np.full(1000, 15.0)),
                },  # CTD reference has no conductivity
                coords={"time": times},
            ),
            "config": {},
        }
    }
    row = cf.stats(instruments, reference_data, {"name": "test"}).iloc[0]
    assert row["cond_flag"] == 2  # no_data: sensor present, CTD reference absent


def test_stats_with_canonical_variable_names():
    """stats() works when reference data uses canonical variable names."""
    times = pd.date_range("2024-01-01 12:00:00", periods=1000, freq="1s")
    pressure = np.concatenate(
        [
            np.linspace(0, 90, 400),
            np.full(200, 100),
            np.linspace(100, 0, 400),
        ]
    )
    instruments = {
        "S001": {
            "data": xr.Dataset(
                {"temperature": ("time", np.full(1000, 4.0))},
                coords={"time": times},
            ),
            "config": {"instrument": "microcat", "label": "Test"},
            "type": "sbe37",
        }
    }
    reference_data = {
        "ctd": {
            "data": xr.Dataset(
                {
                    "pressure": ("time", pressure),
                    "temperature": ("time", np.full(1000, 4.0)),
                    "conductivity": ("time", np.full(1000, 34.5)),
                },
                coords={"time": times},
            ),
            "config": {},
        }
    }
    df = cf.stats(instruments, reference_data, {"name": "test"})
    assert not df.empty


# --- caldip_uncertainties: covariance-corrected paired-diff stats ---------


def test_estimate_sample_interval_basic():
    """Empirical dt matches the real spacing of a regular time series."""
    times = np.arange(0.0, 120.0, 10.0)  # 10 s interval, like a MicroCAT
    dt = cf._estimate_sample_interval(times)
    assert dt == pytest.approx(10.0)


def test_estimate_sample_interval_too_few_samples_raises():
    """A single timestamp can't yield an interval - should raise, not
    silently return a NaN that would poison every downstream calculation."""
    with pytest.raises(ValueError):
        cf._estimate_sample_interval(np.array([0.0]))


def test_check_sample_coverage_full_window():
    """A complete, gap-free window is sufficient, with observed_n matching
    expected_n exactly."""
    times = np.arange(0.0, 121.0, 1.0)  # 121 samples, 1 Hz, 120 s span
    values = np.full(len(times), 10.0)
    result = cf._check_sample_coverage(times, values, 0.0, 120.0, dt=1.0)
    assert result["sufficient"] is True
    assert result["observed_n"] == 121
    assert result["expected_n"] == pytest.approx(121.0)


def test_check_sample_coverage_clipped_edge_not_flagged():
    """A window that's merely clipped at the edge (data starts late, but is
    complete where it exists) must not be treated as a gap - expected_n is
    based on the window's own actual span, not its nominal length."""
    times = np.arange(60.0, 121.0, 1.0)  # starts at t=60, not t=0
    values = np.full(len(times), 10.0)
    result = cf._check_sample_coverage(times, values, 0.0, 120.0, dt=1.0)
    assert result["sufficient"] is True


def test_check_sample_coverage_real_gap_flagged():
    """A genuine gap in the middle of the window - not just edge clipping -
    is correctly flagged as insufficient."""
    times = np.concatenate([np.arange(0.0, 20.0, 1.0), np.arange(100.0, 121.0, 1.0)])
    values = np.full(len(times), 10.0)
    result = cf._check_sample_coverage(times, values, 0.0, 120.0, dt=1.0)
    assert result["sufficient"] is False


def test_check_sample_coverage_excludes_nan_values():
    """A sample that is in-window by timestamp but NaN (e.g. wild-edit
    masked) must not count toward observed_n - this is what lets the check
    catch a wild-edit-masked stretch, not just a missing timestamp."""
    times = np.arange(0.0, 13.0, 1.0)
    values = np.full(len(times), 10.0)
    values[5] = np.nan
    result = cf._check_sample_coverage(times, values, 0.0, 12.0, dt=1.0)
    assert result["observed_n"] == len(times) - 1
    assert result["mask"][5] == np.False_


def test_match_resolution_averages_fine_onto_coarse():
    """Each coarse sample is paired with the mean of the fine series'
    samples in its own dt-wide sub-window."""
    fine_times = np.arange(0.0, 20.0, 1.0)
    fine_values = np.full(len(fine_times), 10.0)
    coarse_times = np.array([5.0])
    coarse_values = np.array([10.5])

    result = cf._match_resolution(
        fine_times, fine_values, coarse_times, coarse_values, coarse_dt=10.0
    )
    assert result["n_dropped"] == 0
    assert result["fine_matched"][0] == pytest.approx(10.0)
    assert result["coarse_matched"][0] == pytest.approx(10.5)


def test_match_resolution_drops_pair_with_insufficient_subwindow():
    """A coarse sample whose own sub-window lacks enough fine coverage is
    dropped - not averaged over too few points - rather than discarding
    every other good pair in the window alongside it."""
    fine_times = np.array([5.0])  # one fine sample, below the floor
    fine_values = np.array([10.0])
    coarse_times = np.array([5.0])
    coarse_values = np.array([10.5])

    result = cf._match_resolution(
        fine_times, fine_values, coarse_times, coarse_values,
        coarse_dt=10.0, min_sub_window_samples=2,
    )
    assert result["n_dropped"] == 1
    assert len(result["coarse_matched"]) == 0


def test_paired_offset_stats_basic():
    """mean/std of the paired differences, ddof=1 (sample, not population,
    std - these samples estimate the sensor's true variability)."""
    coarse = np.array([10.1, 10.2, 10.0, 10.3])
    fine = np.array([10.0, 10.0, 10.0, 10.0])
    result = cf._paired_offset_stats(coarse, fine)
    diffs = coarse - fine
    assert result["mean_offset"] == pytest.approx(np.mean(diffs))
    assert result["std_offset"] == pytest.approx(np.std(diffs, ddof=1))
    assert result["n"] == 4


def test_paired_offset_stats_single_pair_has_nan_std():
    """A single matched pair gives an offset but not a std - variability
    cannot be estimated from one point."""
    result = cf._paired_offset_stats(np.array([10.5]), np.array([10.0]))
    assert result["mean_offset"] == pytest.approx(0.5)
    assert np.isnan(result["std_offset"])
    assert result["n"] == 1


def test_stats_includes_paired_columns():
    """stats() output includes the new covariance-corrected paired columns
    alongside the existing ones, for a realistic coarse instrument interval
    (10 s, like a MicroCAT) against a 1 Hz CTD reference."""
    n_ctd = 1000
    times = pd.date_range("2024-01-01 12:00:00", periods=n_ctd, freq="1s")
    pressure = np.concatenate(
        [
            np.linspace(0, 90, 400),
            np.full(200, 100),  # 200 s bottle stop
            np.linspace(100, 0, 400),
        ]
    )
    rng = np.random.default_rng(0)
    reference_data = {
        "ctd": {
            "data": xr.Dataset(
                {
                    "pressure": ("time", pressure),
                    "temperature": (
                        "time", np.full(n_ctd, 15.0) + rng.normal(0, 0.005, n_ctd)
                    ),
                },
                coords={"time": times},
            ),
            "config": {},
        }
    }
    inst_times = pd.date_range("2024-01-01 12:00:00", periods=100, freq="10s")
    instruments = {
        "12345": {
            "data": xr.Dataset(
                {
                    "temperature": (
                        "time", np.full(100, 15.01) + rng.normal(0, 0.002, 100)
                    )
                },
                coords={"time": inst_times},
            ),
            "config": {"instrument": "microcat", "label": "Test"},
            "type": "microcat",
        }
    }

    df = cf.stats(instruments, reference_data, {"name": "test_cast"})
    assert not df.empty
    for col in ["temp_diff_paired", "temp_std_paired", "temp_n_matched", "temp_n_dropped"]:
        assert col in df.columns
    row = df.iloc[0]
    assert not np.isnan(row["temp_diff_paired"])
    assert row["temp_n_matched"] > 0
