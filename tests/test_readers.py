"""
Unit tests for readers.py data loading functionality.
"""

import pytest
import yaml
from pathlib import Path

from caldip import readers


def test_find_config_file_with_yaml_file(tmp_path):
    """Test finding config when given a .yaml file directly."""
    config_file = tmp_path / "test.caldip.yaml"
    config_file.write_text("name: test")

    result = readers.find_config_file(str(config_file))
    assert result == config_file


def test_find_config_file_with_directory(tmp_path):
    """Test finding config in a directory."""
    config_file = tmp_path / "cast1.caldip.yaml"
    config_file.write_text("name: cast1")

    result = readers.find_config_file(str(tmp_path))
    assert result == config_file


def test_find_config_file_not_found(tmp_path):
    """Test when no config file is found."""
    result = readers.find_config_file(str(tmp_path))
    assert result is None


def test_load_config_valid(tmp_path):
    """Test loading a valid YAML config."""
    config_content = {
        "name": "test_cast",
        "instruments": [
            {"serial": "12345", "instrument": "microcat", "file": "test.cnv"}
        ],
        "reference": {"ctd": {"file": "ctd.cnv"}},
    }

    config_file = tmp_path / "test.yaml"
    config_file.write_text(yaml.dump(config_content))

    result = readers.load_config(config_file)
    assert result == config_content
    assert result["name"] == "test_cast"


def test_load_config_invalid_yaml(tmp_path):
    """Test loading invalid YAML raises appropriate error."""
    config_file = tmp_path / "invalid.yaml"
    config_file.write_text("invalid: yaml: content: [")

    with pytest.raises(Exception):
        readers.load_config(config_file)


def test_load_instruments_from_config_empty():
    """Test loading instruments with empty config."""
    config = {"instruments": []}

    instruments = readers.load_instruments_from_config(config, Path("/tmp"))
    assert instruments == {}


def test_load_instruments_from_config_missing_file(tmp_path):
    """Per-instrument failures are caught internally; function returns an empty dict."""
    config = {
        "instruments": [
            {"serial": "12345", "filename": "nonexistent.cnv", "file_type": "sbe-cnv"}
        ]
    }

    instruments = readers.load_instruments_from_config(config, tmp_path)
    assert isinstance(instruments, dict)
    assert len(instruments) == 0
