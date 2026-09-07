"""Tests for the instrument-class vocabulary and serial normalisation.

The cruise-YAML ``instrument:`` field is normalised on load to an oceanarray
class name (``caldip.config.parameters.INSTRUMENT_CLASSES``), and serials are
normalised to their join-key form. Both happen in :func:`caldip.readers.load_config`.
"""

import warnings

import pytest
import xarray as xr
import yaml

from caldip import _writers as writers
from caldip.config import parameters as params
from caldip.readers import (
    load_config,
    normalize_serial,
    resolve_instrument_class,
)

# The nine classes, mirrored from oceanarray's INSTRUMENT_FILE_TYPES keys. This
# literal is the cross-package check: if oceanarray's set changes, this fails.
_EXPECTED_CLASSES = {
    "microcat",
    "sbe56",
    "sbe16",
    "aquadopp",
    "tr1050",
    "rbrsolo",
    "rbrduet",
    "seapoint",
    "adcp",
}


def test_instrument_classes_match_expected_set():
    """The vocabulary tuple carries exactly the nine oceanarray classes."""
    assert set(params.INSTRUMENT_CLASSES) == _EXPECTED_CLASSES
    assert len(params.INSTRUMENT_CLASSES) == len(_EXPECTED_CLASSES)


def test_class_variables_cover_every_class():
    """Every class has a measured-variable tuple; seapoint and adcp are empty."""
    assert set(params.INSTRUMENT_CLASS_VARIABLES) == set(params.INSTRUMENT_CLASSES)
    assert params.INSTRUMENT_CLASS_VARIABLES["seapoint"] == ()
    assert params.INSTRUMENT_CLASS_VARIABLES["adcp"] == ()
    assert params.INSTRUMENT_CLASS_VARIABLES["tr1050"] == ("temp",)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("013874", "13874"),
        ("13874", "13874"),
        ("9920*", "9920"),
        ("015571", "15571"),
        (13840, "13840"),
        ("0", "0"),
        ("000", "0"),
        ("0A123", "0A123"),  # non-numeric: leading zero is not padding, kept
    ],
)
def test_normalize_serial(value, expected):
    """Leading zeros and a trailing asterisk are stripped; all-zero stays '0'."""
    assert normalize_serial(value) == expected


@pytest.mark.parametrize("value", ["", "   ", None])
def test_normalize_serial_rejects_blank(value):
    """A blank or missing serial raises rather than becoming a bogus join key."""
    with pytest.raises(ValueError, match="serial is empty"):
        normalize_serial(value)


def test_resolve_known_class_passes_silently():
    """A value already in the vocabulary is returned unchanged, without warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert resolve_instrument_class("microcat") == "microcat"
        assert resolve_instrument_class("tr1050", "rbr-rsk") == "tr1050"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("TR1050", "tr1050"), ("RBRsolo", "rbrsolo"), ("MicroCAT", "microcat")],
)
def test_resolve_class_is_case_insensitive(value, expected):
    """A class named in the label's casing resolves to its canonical form."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a real class must not warn
        assert resolve_instrument_class(value) == expected


@pytest.mark.parametrize(
    ("instrument", "file_type", "expected"),
    [
        ("sbe", "sbe-cnv", "microcat"),
        ("sbe37", "sbe-cnv", "microcat"),
        ("nortek", "nortek-csv", "aquadopp"),
        ("rbr", "rbr-matlab-legacy", "tr1050"),
        ("rbr", "rbr-rsk", "rbrsolo"),
    ],
)
def test_resolve_legacy_alias_maps_and_warns(instrument, file_type, expected):
    """A legacy alias maps to its class and raises a deprecation warning."""
    with pytest.warns(UserWarning, match="legacy alias"):
        assert resolve_instrument_class(instrument, file_type) == expected


@pytest.mark.parametrize("value", ["seapoint", "adcp"])
def test_resolve_uncompared_class_is_refused(value):
    """A real class caldip compares nothing for is refused, named, not 'unknown'."""
    with pytest.raises(ValueError, match="does not compare"):
        resolve_instrument_class(value)


def test_resolve_unknown_raises():
    """An unrecognised value raises, listing the valid classes."""
    with pytest.raises(ValueError, match="not a known instrument class"):
        resolve_instrument_class("frobnicator")


def test_load_config_normalizes_instrument_and_serial(tmp_path):
    """load_config maps a legacy instrument to its class and strips the serial."""
    cfg_path = tmp_path / "castX.caldip.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "name": "castX",
                "instruments": [
                    {
                        "serial": "013874",
                        "instrument": "rbr",
                        "file_type": "rbr-matlab-legacy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.warns(UserWarning, match="legacy alias"):
        config = load_config(cfg_path)
    inst = config["instruments"][0]
    assert inst["instrument"] == "tr1050"
    assert inst["serial"] == "13874"


def _write_config(tmp_path, instruments):
    """Write a minimal cruise YAML with the given instruments and return its path."""
    cfg_path = tmp_path / "castX.caldip.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"name": "castX", "instruments": instruments}),
        encoding="utf-8",
    )
    return cfg_path


def test_load_config_leaves_blank_scaffold_stub(tmp_path):
    """A stub with a blank instrument/serial loads unchanged, to be filled later."""
    cfg_path = _write_config(
        tmp_path, [{"serial": "", "instrument": "", "file_type": "", "filename": "x"}]
    )
    config = load_config(cfg_path)  # must not raise
    inst = config["instruments"][0]
    assert inst["instrument"] == ""
    assert inst["serial"] == ""


def test_load_config_rejects_duplicate_serial(tmp_path):
    """Two instruments that share a serial after normalisation are rejected."""
    cfg_path = _write_config(
        tmp_path,
        [
            {"serial": "013874", "instrument": "microcat", "filename": "a.cnv"},
            {"serial": "13874", "instrument": "microcat", "filename": "b.cnv"},
        ],
    )
    with pytest.raises(ValueError, match="share serial"):
        load_config(cfg_path)


def _minimal_stats_frame():
    """One instrument, one stop, enough columns for write_stats_netcdf."""
    import numpy as np
    import pandas as pd

    t0 = pd.Timestamp("2024-01-01 12:00:00")
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
            "ctd_temp": [5.0],
            "ctd_cond": [np.nan],
            "ctd_press": [1000.0],
            "inst_temp": [5.006],
            "inst_cond": [np.nan],
            "inst_press": [np.nan],
            "N": [100],
            "label": ["TR1050"],
            "temp_flag": [1],
            "cond_flag": [2],
            "press_flag": [2],
            "date": ["2024-01-01"],
            "time_start": ["12:00:00"],
            "time_end": ["12:02:00"],
        }
    )


def test_netcdf_omits_dip_role_and_keeps_class_vocabulary(tmp_path):
    """The netCDF carries no dip_role attribute and a vocabulary instrument_type."""
    config = {"name": "castX", "cruise": "m", "ctd_sensor": 2, "instruments": [{}]}
    thresholds = {"temp": 0.005, "cond": 0.02, "press": 5.0}
    out = writers.write_stats_netcdf(
        _minimal_stats_frame(), config, tmp_path / "castX_caldip.nc", thresholds=thresholds
    )
    ds = xr.open_dataset(out, engine="netcdf4")
    assert "dip_role" not in ds.attrs
    value = str(ds["instrument_type"].values.ravel()[0])
    assert value == "tr1050"  # full class name, not truncated
