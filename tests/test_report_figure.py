"""Tests for caldip.report._figure using a real Plotly-generated HTML file.

The fixture HTML is written by Plotly itself (``fig.write_html`` with the bundle
inlined, exactly as ``caldip plot`` produces), so the extraction logic is tested
against a genuine plotly file rather than a hand-built string.
"""

import plotly.graph_objects as go
import pytest

from caldip.report._figure import (
    check_version_skew,
    extract_figure,
    installed_plotlyjs_version,
)


@pytest.fixture
def saved_plot(tmp_path):
    """Write a small but genuine plotly HTML file, as caldip plot would."""
    fig = go.Figure(go.Scatter(x=[0, 1, 2], y=[3.6, 3.7, 3.65], name="RBR"))
    path = tmp_path / "castX_plot.html"
    fig.write_html(path)
    return path


def test_extract_returns_fragment_without_bundle(saved_plot):
    """The fragment carries the graph div and newPlot call, not the 5 MB bundle."""
    fragment = extract_figure(saved_plot)
    assert fragment is not None
    assert "plotly-graph-div" in fragment.html
    assert "Plotly.newPlot" in fragment.html
    # The extracted fragment is a small slice, far below the full file size.
    assert len(fragment.html) < saved_plot.stat().st_size / 2


def test_extract_captures_plotly_version(saved_plot):
    """The saved file's plotly.js version is captured for the skew check."""
    fragment = extract_figure(saved_plot)
    assert fragment.plotly_version == installed_plotlyjs_version()


def test_extract_captures_pixel_height(tmp_path):
    """A figure with an explicit layout height exposes it, so the container matches.

    Reproduces the real caldip plot, whose ``layout.height`` (1000 px for the
    stacked panels) must drive the report container height — otherwise the figure
    overflows a fixed-height box and overlaps the table below it.
    """
    fig = go.Figure(go.Scatter(x=[0, 1], y=[3.6, 3.7]))
    fig.update_layout(height=800)
    path = tmp_path / "castH_plot.html"
    fig.write_html(path)
    assert extract_figure(path).height_px == 800


def test_extract_percentage_height_is_none(saved_plot):
    """A figure saved with a percentage height exposes None (caller uses default)."""
    assert extract_figure(saved_plot).height_px is None


def test_extract_missing_marker_returns_none(tmp_path):
    """A file without a plotly graph div yields None (drives graceful fallback)."""
    path = tmp_path / "not_a_plot.html"
    path.write_text("<html><body>no figure here</body></html>", encoding="utf-8")
    assert extract_figure(path) is None


def test_version_skew_warns_on_mismatch(saved_plot):
    """A fragment claiming a different plotly.js version warns."""
    fragment = extract_figure(saved_plot)
    skewed = type(fragment)(html=fragment.html, plotly_version="0.0.1")
    with pytest.warns(UserWarning, match="plotly.js"):
        check_version_skew(skewed, cast_name="castX")


def test_version_skew_silent_on_match(saved_plot, recwarn):
    """A matching version does not warn."""
    fragment = extract_figure(saved_plot)
    check_version_skew(fragment, cast_name="castX")
    assert not [w for w in recwarn if "plotly.js" in str(w.message)]
