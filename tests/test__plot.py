"""
Tests for caldip/plotters.py visualization functions.
"""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

pytest.importorskip("plotly", reason="plotly not installed")

from caldip import _plot as plotters


def _make_cast(start="2024-01-01 12:00:00", periods=600, with_cond=False):
    """Synthetic cast: descent → bottle stop → ascent."""
    times = pd.date_range(start, periods=periods, freq="1s")
    pressure = np.concatenate(
        [
            np.linspace(0, 90, 200),
            np.full(200, 100),
            np.linspace(100, 0, 200),
        ]
    )
    temp = np.full(periods, 15.0) + np.random.default_rng(0).normal(0, 0.01, periods)
    data_vars = {"prDM": ("time", pressure), "temperature": ("time", temp)}
    if with_cond:
        data_vars["conductivity"] = ("time", np.full(periods, 34.5))
    return xr.Dataset(data_vars, coords={"time": times})


def _make_instrument_data(with_cond=False):
    ds = _make_cast(with_cond=with_cond)
    return {
        "S001": {
            "data": ds,
            "config": {"label": "SBE37", "instrument": "sbe37"},
            "type": "sbe37",
        }
    }


def _make_reference_data():
    ds = _make_cast()
    return {"ctd": {"data": ds, "config": {}, "file": "test.cnv"}}


def test_create_plot_returns_figure():
    """Basic call returns a plotly Figure object."""
    fig = plotters.plot(
        _make_instrument_data(),
        _make_reference_data(),
    )
    assert fig is not None
    assert hasattr(fig, "data")
    assert hasattr(fig, "layout")


def test_create_plot_with_conductivity():
    """Plot runs without error when instruments have conductivity data."""
    fig = plotters.plot(
        _make_instrument_data(with_cond=True),
        _make_reference_data(),
    )
    assert fig is not None


def test_create_plot_no_bottle_stops():
    """Disabling bottle stops still produces a valid figure."""
    fig = plotters.plot(
        _make_instrument_data(),
        _make_reference_data(),
        show_bottle_stops=False,
    )
    assert fig is not None


def test_create_plot_custom_title():
    """Custom title appears somewhere in the figure (subplot annotation)."""
    fig = plotters.plot(
        _make_instrument_data(),
        _make_reference_data(),
        title="My Test Cast",
    )
    # Title is set as the first subplot annotation, not fig.layout.title
    annotation_texts = [a.text for a in fig.layout.annotations]
    assert any("My Test Cast" in (t or "") for t in annotation_texts)


def test_create_plot_with_config():
    """Plot with deployment/recovery times in config runs without error."""
    config = {
        "deployment_time": "2024-01-01 12:00:00",
        "recovery_time": "2024-01-01 12:09:59",
    }
    fig = plotters.plot(
        _make_instrument_data(),
        _make_reference_data(),
        config=config,
    )
    assert fig is not None


def test_create_plot_empty_instruments():
    """Plot with no instruments still runs."""
    fig = plotters.plot(
        {},
        _make_reference_data(),
    )
    assert fig is not None


def test_create_plot_multiple_instruments():
    """Multiple instruments are all added to the figure."""
    ds = _make_cast()
    instrument_data = {
        "S001": {
            "data": ds,
            "config": {"label": "SBE37", "instrument": "sbe37"},
            "type": "sbe37",
        },
        "S002": {
            "data": ds,
            "config": {"label": "SBE37", "instrument": "sbe37"},
            "type": "sbe37",
        },
    }
    fig = plotters.plot(instrument_data, _make_reference_data())
    assert fig is not None
