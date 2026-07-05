"""
Integration tests using real test fixture data.
"""

import pytest
from pathlib import Path
import yaml

from caldip import readers, caldip_functions as cf, tools


# Helper functions
def get_fixture_data_path():
    """Get path to test fixture data."""
    return (
        Path(__file__).parent
        / "test_fixtures"
        / "proc_calib"
        / "msm142_2026"
        / "cal_dip"
        / "castM4"
    )


def get_config_file():
    """Get test configuration file."""
    fixture_data_path = get_fixture_data_path()
    config_file = fixture_data_path / "castM4.caldip.yaml"
    if not config_file.exists():
        pytest.skip(f"Test fixture not found: {config_file}")
    return config_file


# Integration tests
def test_load_config_from_fixtures():
    """Test loading configuration from fixture data."""
    config_file = get_config_file()
    config = readers.load_caldip_config(config_file)

    assert "name" in config
    assert "instruments" in config
    assert config["name"] == "castM4"
    assert len(config["instruments"]) > 0
    assert "ctd_file" in config


def test_load_instruments_from_config():
    """Test loading instrument data from configuration."""
    config_file = get_config_file()
    fixture_data_path = get_fixture_data_path()
    config = readers.load_caldip_config(config_file)

    instruments = readers.load_instruments_from_config(config, fixture_data_path)

    assert len(instruments) > 0

    for serial, inst_info in instruments.items():
        assert "data" in inst_info
        assert "config" in inst_info
        assert "type" in inst_info
        assert isinstance(serial, str)
        assert hasattr(inst_info["data"], "coords")
        assert hasattr(inst_info["data"], "data_vars")


def test_load_reference_data():
    """Test loading reference CTD data."""
    config_file = get_config_file()
    fixture_data_path = get_fixture_data_path()
    config = readers.load_caldip_config(config_file)

    reference_data = readers.load_reference_data(config, fixture_data_path)

    assert len(reference_data) > 0

    for ref_name, ref_info in reference_data.items():
        assert "data" in ref_info
        assert "config" in ref_info or "file" in ref_info
        assert hasattr(ref_info["data"], "coords")
        assert hasattr(ref_info["data"], "data_vars")


def test_end_to_end_analysis():
    """Test complete analysis pipeline with fixture data."""
    config_file = get_config_file()
    fixture_data_path = get_fixture_data_path()
    config = readers.load_caldip_config(config_file)

    instruments = readers.load_instruments_from_config(config, fixture_data_path)
    reference_data = readers.load_reference_data(config, fixture_data_path)

    assert instruments, "No instruments loaded from fixture"
    assert reference_data, "No reference data loaded from fixture"

    detailed_stats_df = cf.calculate_universal_statistics_by_bottle_stop(
        instruments, reference_data, config, ctd_sensor=1
    )

    assert not detailed_stats_df.empty
    assert len(detailed_stats_df) > 0

    expected_cols = ["serial", "instrument_type", "bl_press", "temp_diff", "N"]
    for col in expected_cols:
        assert col in detailed_stats_df.columns

    summary_stats_df = tools.extract_summary_from_detailed_stats(
        detailed_stats_df, config
    )
    assert not summary_stats_df.empty
    assert len(summary_stats_df) <= len(detailed_stats_df)


def test_bottle_stop_detection_with_real_data():
    """Test bottle stop detection with real CTD data."""
    config_file = get_config_file()
    fixture_data_path = get_fixture_data_path()
    config = readers.load_caldip_config(config_file)

    reference_data = readers.load_reference_data(config, fixture_data_path)
    assert reference_data, "No reference data loaded from fixture"

    ctd_data = list(reference_data.values())[0]["data"]
    bottle_stops = cf.find_bottle_stops(ctd_data)

    assert len(bottle_stops) > 0

    for stop in bottle_stops:
        assert "start_time" in stop
        assert "end_time" in stop
        assert "pressure" in stop
        assert "duration_seconds" in stop
        assert stop["duration_seconds"] >= 180
        assert stop["pressure"] > 0


def test_bottle_stop_detection_castM4_five_stops():
    """castM4 CTD profile must yield exactly 5 bottle stops at known depths."""
    fixture = get_fixture_data_path()
    config_file = fixture / "castM4.caldip.yaml"
    if not config_file.exists():
        pytest.skip("castM4 fixture not available")

    config = readers.load_caldip_config(config_file)
    reference_data = readers.load_reference_data(config, fixture)
    ctd_data = list(reference_data.values())[0]["data"]

    stops = cf.find_bottle_stops(ctd_data)

    assert len(stops) == 5, f"Expected 5 bottle stops, got {len(stops)}"

    pressures = sorted([s["pressure"] for s in stops], reverse=True)
    assert pressures[0] == pytest.approx(2027, abs=20)  # deepest
    assert pressures[1] == pytest.approx(1522, abs=20)
    assert pressures[2] == pytest.approx(909, abs=20)
    assert pressures[3] == pytest.approx(355, abs=20)
    assert pressures[4] == pytest.approx(51, abs=10)  # shallowest

    for stop in stops:
        assert stop["duration_seconds"] >= 180
        assert stop["pressure"] > 0


# Config validation tests
def test_config_validation_missing_name(tmp_path):
    """Test that configs without 'name' are handled."""
    config_content = {"instruments": [], "reference": {"ctd": {"file": "test.cnv"}}}

    config_file = tmp_path / "test.yaml"
    config_file.write_text(yaml.dump(config_content))

    config = readers.load_caldip_config(config_file)
    assert config == config_content


def test_config_validation_empty_instruments(tmp_path):
    """Test handling of empty instruments list."""
    config_content = {
        "name": "test",
        "instruments": [],
        "reference": {"ctd": {"file": "test.cnv"}},
    }

    config_file = tmp_path / "test.yaml"
    config_file.write_text(yaml.dump(config_content))

    config = readers.load_caldip_config(config_file)
    instruments = readers.load_instruments_from_config(config, tmp_path)

    assert instruments == {}
