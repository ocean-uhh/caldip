"""Tests for the cruise-level YAML: inheritance, drift override, cast discovery.

A ``caldip.cruise.yaml`` holds the per-cruise facts (``cruise``/``ship``/``year``)
that were repeated — and had drifted — across per-cast configs. A per-cast config
inherits them from the nearest cruise YAML, a disagreeing value warns and the
cruise value wins, and casts are discovered from the directory rather than a list.
"""

import warnings

import pytest
import yaml

from caldip.readers import (
    discover_cast_configs,
    find_cruise_config,
    load_config,
)


def _cruise_tree(tmp_path, per_cast, cruise=None):
    """Build a cruise tree; return the cal_dip dir and the castA config path."""
    cal_dip = tmp_path / "msm142_2026" / "cal_dip"
    (cal_dip / "castA").mkdir(parents=True)
    if cruise is not None:
        (tmp_path / "msm142_2026" / "caldip.cruise.yaml").write_text(
            yaml.safe_dump(cruise), encoding="utf-8"
        )
    cfg = cal_dip / "castA" / "castA.caldip.yaml"
    cfg.write_text(yaml.safe_dump(per_cast), encoding="utf-8")
    return cal_dip, cfg


def test_cruise_yaml_fills_missing_fields(tmp_path):
    """A per-cast config missing cruise/ship/year inherits them from the cruise YAML."""
    _, cfg = _cruise_tree(
        tmp_path,
        {"name": "castA", "instruments": []},
        cruise={"cruise": "msm142", "ship": "FS MSMerian", "year": 2026},
    )
    config = load_config(cfg)
    assert config["cruise"] == "msm142"
    assert config["ship"] == "FS MSMerian"
    assert config["year"] == 2026


def test_cruise_yaml_overrides_drift_with_warning(tmp_path):
    """A per-cast value disagreeing with the cruise YAML warns and is overridden."""
    _, cfg = _cruise_tree(
        tmp_path,
        {"name": "castA", "ship": "Merian", "instruments": []},
        cruise={"cruise": "msm142", "ship": "FS MSMerian", "year": 2026},
    )
    with pytest.warns(UserWarning, match="disagrees"):
        config = load_config(cfg)
    assert config["ship"] == "FS MSMerian"  # cruise value wins


def test_no_cruise_yaml_leaves_config_unchanged(tmp_path):
    """Without a cruise YAML, the per-cast config is used as written (no merge)."""
    _, cfg = _cruise_tree(
        tmp_path, {"name": "castA", "ship": "Merian", "instruments": []}, cruise=None
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        config = load_config(cfg)
    assert config["ship"] == "Merian"
    assert "cruise" not in config


def test_discover_cast_configs_excludes_cruise_yaml(tmp_path):
    """Casts are discovered from the directory; the cruise YAML is not a cast."""
    cal_dip, _ = _cruise_tree(
        tmp_path,
        {"name": "castA", "instruments": []},
        cruise={"cruise": "msm142", "ship": "FS MSMerian", "year": 2026},
    )
    (cal_dip / "castB").mkdir()
    (cal_dip / "castB" / "castB.caldip.yaml").write_text(
        yaml.safe_dump({"name": "castB", "instruments": []}), encoding="utf-8"
    )
    found = [p.name for p in discover_cast_configs(cal_dip)]
    assert found == ["castA.caldip.yaml", "castB.caldip.yaml"]
    assert all("cruise" not in n for n in found)


def test_find_cruise_config_climbs_to_nearest(tmp_path):
    """find_cruise_config returns the nearest cruise YAML above the start."""
    cal_dip, cfg = _cruise_tree(
        tmp_path,
        {"name": "castA", "instruments": []},
        cruise={"cruise": "msm142", "ship": "FS MSMerian", "year": 2026},
    )
    found = find_cruise_config(cfg.parent)
    assert found is not None and found.name == "caldip.cruise.yaml"
    assert find_cruise_config(tmp_path) is None  # above the cruise dir
