"""Reuse a saved caldip Plotly figure inside a report without reloading data.

``caldip plot`` writes ``{cast}_plot.html`` with the whole Plotly bundle inlined
(~5-10 MB per cast). Rebuilding the figure from source would re-tie the report to
the raw instrument files; instead this module lifts just the figure ``<div>`` and
its ``Plotly.newPlot(...)`` call out of the saved file, so the report reads only
the results directory. The bundle is loaded once per report (see
:func:`caldip.report._html.plotly_bundle_script`).

The fragment was produced by whatever Plotly version wrote the file, while the
report inlines the *installed* bundle. That skew is normally harmless because
reports are built from freshly generated plots, but a mismatch can silently yield
a blank figure, so :func:`extract_figure` captures the saved version and
:func:`check_version_skew` warns when it differs from the installed bundle.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

from plotly.offline import get_plotlyjs

_GRAPH_DIV_MARKER = 'class="plotly-graph-div"'
_VERSION_RE = re.compile(r"plotly\.js v([\d.]+)")
#: The saved figure's outer wrapper carries its intended pixel height (caldip plot
#: sets ``layout.height``); the inner graph div is ``height:100%`` of it.
_WRAPPER_HEIGHT_RE = re.compile(r"height:(\d+)px;\s*width:\s*100%")

_installed_version_cache: list[str | None] = []


@dataclass(frozen=True)
class FigureFragment:
    """A figure lifted from a saved caldip plot file.

    Parameters
    ----------
    html : str
        The ``<div>`` plus its ``Plotly.newPlot(...)`` ``<script>``, without the
        Plotly bundle.
    plotly_version : str or None
        The plotly.js version string found in the saved file, or ``None`` if the
        marker was absent.
    height_px : int or None
        The figure's intended pixel height, read from the saved outer wrapper, so
        the report container can match it. ``None`` if the saved file used a
        percentage height (the caller then falls back to a default).
    """

    html: str
    plotly_version: str | None
    height_px: int | None = None


def installed_plotlyjs_version() -> str | None:
    """Return the plotly.js version string of the installed bundle.

    Returns
    -------
    str or None
        The version parsed from :func:`plotly.offline.get_plotlyjs`, or ``None``
        if the marker is not present.
    """
    if not _installed_version_cache:
        match = _VERSION_RE.search(get_plotlyjs())
        _installed_version_cache.append(match.group(1) if match else None)
    return _installed_version_cache[0]


def extract_figure(html_path: Path) -> FigureFragment | None:
    """Lift the figure ``<div>`` and its data ``<script>`` from a saved plot file.

    The slice runs from the ``plotly-graph-div`` ``<div>`` to the file's final
    ``</script>``, which is the ``Plotly.newPlot(...)`` call; everything before it
    (including the inlined bundle) is discarded. Keying on the graph ``<div>``
    rather than on ``Plotly.newPlot`` avoids a false positive from the Mapbox
    error string inside the bundle.

    Parameters
    ----------
    html_path : pathlib.Path
        Path to a ``{cast}_plot.html`` written by ``caldip plot``.

    Returns
    -------
    FigureFragment or None
        The extracted fragment, or ``None`` if the file has no Plotly graph div.
    """
    html = html_path.read_text(encoding="utf-8")
    marker = html.find(_GRAPH_DIV_MARKER)
    if marker == -1:
        return None
    div_start = html.rfind("<div", 0, marker)
    script_end = html.rfind("</script>")
    if div_start == -1 or script_end < marker:
        return None
    fragment = html[div_start : script_end + len("</script>")]
    version_match = _VERSION_RE.search(html)
    height_match = _WRAPPER_HEIGHT_RE.search(html)
    return FigureFragment(
        fragment,
        version_match.group(1) if version_match else None,
        int(height_match.group(1)) if height_match else None,
    )


def skew_message(fragment: FigureFragment) -> str | None:
    """Return a version-skew message if saved and installed plotly.js differ.

    Parameters
    ----------
    fragment : FigureFragment
        The extracted figure, carrying the saved plotly.js version.

    Returns
    -------
    str or None
        A reader-facing message, or ``None`` if the versions match (or either is
        unknown).
    """
    saved = fragment.plotly_version
    installed = installed_plotlyjs_version()
    if saved and installed and saved != installed:
        return (
            f"figure generated with plotly.js v{saved}; report bundle is "
            f"v{installed} — regenerate this cast's plot if the figure is blank."
        )
    return None


def check_version_skew(fragment: FigureFragment, *, cast_name: str) -> str | None:
    """Warn (to the console) on version skew and return the reader-facing message.

    The console warning is read once, by whoever builds the report; the returned
    message is meant to be rendered on the cast page, where a later reader sees it
    (a blank Plotly figure otherwise looks like "no data", not an error).

    Parameters
    ----------
    fragment : FigureFragment
        The extracted figure, carrying the saved plotly.js version.
    cast_name : str
        Cast name, used only in the console warning.

    Returns
    -------
    str or None
        The reader-facing skew message, or ``None`` if the versions match.
    """
    message = skew_message(fragment)
    if message is not None:
        warnings.warn(f"{cast_name}: {message}", stacklevel=2)
    return message
