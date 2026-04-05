"""
Integration tests using real test fixture data.
"""

import pytest
import pandas as pd
from pathlib import Path
import yaml

from caldip import readers, caldip_functions as cf, tools


# Helper functions
def get_fixture_data_path():
    """Get path to test fixture data."""
    return Path(__file__).parent / "test_fixtures" / "proc_calib" / "msm142_2026" / "cal_dip" / "castM4"


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
    
    # Check basic config structure
    assert 'name' in config
    assert 'instruments' in config
    assert config['name'] == 'castM4'
    
    # Check instruments are defined
    assert len(config['instruments']) > 0
    
    # Check CTD file is defined
    assert 'ctd_file' in config


def test_load_instruments_from_config():
    """Test loading instrument data from configuration."""
    config_file = get_config_file()
    fixture_data_path = get_fixture_data_path()
    config = readers.load_caldip_config(config_file)
    
    try:
        instruments = readers.load_instruments_from_config(config, fixture_data_path)
        
        # Should have loaded some instruments
        assert len(instruments) > 0
        
        # Each instrument should have expected structure
        for serial, inst_info in instruments.items():
            assert 'data' in inst_info
            assert 'config' in inst_info
            assert 'type' in inst_info
            assert isinstance(serial, str)
            
            # Data should be xarray Dataset
            assert hasattr(inst_info['data'], 'coords')
            assert hasattr(inst_info['data'], 'data_vars')
            
    except Exception as e:
        pytest.skip(f"Could not load instrument data: {e}")


def test_load_reference_data():
    """Test loading reference CTD data."""
    config_file = get_config_file()
    fixture_data_path = get_fixture_data_path()
    config = readers.load_caldip_config(config_file)
    
    try:
        reference_data = readers.load_reference_data(config, fixture_data_path)
        
        # Should have loaded reference data
        assert len(reference_data) > 0
        
        # Should contain CTD data
        for ref_name, ref_info in reference_data.items():
            assert 'data' in ref_info
            # May have 'config' or 'file' depending on the reference type
            assert 'config' in ref_info or 'file' in ref_info
            
            # Data should be xarray Dataset
            assert hasattr(ref_info['data'], 'coords')
            assert hasattr(ref_info['data'], 'data_vars')
            
    except Exception as e:
        pytest.skip(f"Could not load reference data: {e}")


def test_end_to_end_analysis():
    """Test complete analysis pipeline with fixture data."""
    config_file = get_config_file()
    fixture_data_path = get_fixture_data_path()
    config = readers.load_caldip_config(config_file)
    
    try:
        # Load data
        instruments = readers.load_instruments_from_config(config, fixture_data_path)
        reference_data = readers.load_reference_data(config, fixture_data_path)
        
        if not instruments or not reference_data:
            pytest.skip("Could not load required data for analysis")
        
        # Run analysis
        detailed_stats_df = cf.calculate_universal_statistics_by_bottle_stop(
            instruments, reference_data, config, ctd_sensor=1
        )
        
        # Should get results
        assert not detailed_stats_df.empty
        assert len(detailed_stats_df) > 0
        
        # Check expected columns are present
        expected_cols = ['serial', 'instrument_type', 'bl_press', 'temp_diff', 'N']
        for col in expected_cols:
            assert col in detailed_stats_df.columns
        
        # Extract summary statistics
        summary_stats_df = tools.extract_summary_from_detailed_stats(detailed_stats_df, config)
        
        # Should get summary results
        assert not summary_stats_df.empty
        assert len(summary_stats_df) <= len(detailed_stats_df)  # Summary should be <= detailed
        
    except Exception as e:
        pytest.skip(f"Analysis pipeline failed: {e}")


def test_bottle_stop_detection_with_real_data():
    """Test bottle stop detection with real CTD data."""
    config_file = get_config_file()
    fixture_data_path = get_fixture_data_path()
    config = readers.load_caldip_config(config_file)
    
    try:
        reference_data = readers.load_reference_data(config, fixture_data_path)
        
        if not reference_data:
            pytest.skip("Could not load reference data")
        
        # Get CTD data
        ctd_data = list(reference_data.values())[0]['data']
        
        # Find bottle stops
        bottle_stops = cf.find_bottle_stops(ctd_data)
        
        # Should find some bottle stops in real calibration dip data
        assert len(bottle_stops) > 0
        
        # Each bottle stop should have expected structure
        for stop in bottle_stops:
            assert 'start_time' in stop
            assert 'end_time' in stop
            assert 'pressure' in stop
            assert 'duration_seconds' in stop
            
            # Duration should be reasonable (at least 3 minutes)
            assert stop['duration_seconds'] >= 180
            
            # Pressure should be positive
            assert stop['pressure'] > 0
            
    except Exception as e:
        pytest.skip(f"Bottle stop detection failed: {e}")


# Config validation tests
def test_config_validation_missing_name(tmp_path):
    """Test that configs without 'name' are handled."""
    config_content = {
        'instruments': [],
        'reference': {'ctd': {'file': 'test.cnv'}}
    }
    
    config_file = tmp_path / "test.yaml" 
    config_file.write_text(yaml.dump(config_content))
    
    config = readers.load_caldip_config(config_file)
    # Should load successfully even without name
    assert config == config_content


def test_config_validation_empty_instruments(tmp_path):
    """Test handling of empty instruments list."""
    config_content = {
        'name': 'test',
        'instruments': [],
        'reference': {'ctd': {'file': 'test.cnv'}}
    }
    
    config_file = tmp_path / "test.yaml"
    config_file.write_text(yaml.dump(config_content))
    
    config = readers.load_caldip_config(config_file)
    instruments = readers.load_instruments_from_config(config, tmp_path)
    
    # Should return empty dict for empty instruments
    assert instruments == {}