"""Build per-cruise HTML calibration reports from caldip results.

``build_report`` reads a directory of ``caldip stats`` output CSVs (and the saved
``{cast}_plot.html`` figures beside them) and writes an index page plus one page
per cast. It adds no data model: everything comes from files already on disk, so
a report is reproducible from an archive of results without the raw instrument
data.

The report is a self-contained *folder* (an index, a ``casts/`` subfolder, and one
shared ``plotly.min.js``), not a set of self-contained files: the interactive
figures are Plotly and share the sibling bundle. This is the deliberate trade for
hover/zoom on bottle stops, but it means there is no PDF path — a headless
renderer such as WeasyPrint will not execute the Plotly script, so a cast page has
no figure in print. If PDF output is ever wanted, a static PNG must be produced
alongside the interactive figure (the shared design system's ``print_css`` and
``<figure><img>`` path already support that shape).
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

from caldip.report._data import discover_casts, summarize_cast
from caldip.report._html import PLOTLY_BUNDLE_FILENAME, write_plotly_bundle
from caldip.report.cast import build_cast_page_html
from caldip.report.index import build_index_html

__all__ = ["build_report"]

_CAST_SUBDIR = "casts"


def _infer_cruise_name(results_dir: Path) -> str | None:
    """Return a cruise label only for the case the path justifies, else None.

    The one defensible inference is the parent of a ``cal_dip/`` directory, which
    is how caldip lays out a cruise. Any other directory name (e.g. ``outputs/``)
    is not a cruise, so this returns ``None`` rather than stamping a guess.

    Parameters
    ----------
    results_dir : pathlib.Path
        The results directory.

    Returns
    -------
    str or None
        The inferred cruise name, or ``None`` if it cannot be justified.
    """
    if results_dir.name == "cal_dip":
        return results_dir.parent.name
    return None


def _resolve_cruise_name(results_dir: Path, summaries: list) -> str:
    """Resolve the masthead cruise label from the casts, then the path.

    Preference order: a single cruise recorded in the casts' CSVs; ``"multiple
    cruises"`` if the casts span more than one; else the path inference; else
    ``"UNK"`` with a warning (never a guess).

    Parameters
    ----------
    results_dir : pathlib.Path
        The results directory.
    summaries : list of CastSummary
        The per-cast summaries, carrying each cast's recorded cruise.

    Returns
    -------
    str
        The cruise label for the masthead.
    """
    known = sorted({s.cruise for s in summaries if s.cruise != "UNK"})
    if len(known) == 1:
        return known[0]
    if len(known) > 1:
        return "multiple cruises"
    inferred = _infer_cruise_name(results_dir)
    if inferred is not None:
        return inferred
    warnings.warn(
        f"cruise: UNK (not recorded in the CSVs and not inferable from the "
        f"results directory '{results_dir}'; pass --cruise to name it)",
        stacklevel=2,
    )
    return "UNK"


def build_report(
    results_dir: str | Path,
    out_dir: str | Path,
    *,
    cruise_name: str | None = None,
) -> Path:
    """Build a per-cruise HTML report from a directory of caldip results.

    Parameters
    ----------
    results_dir : str or pathlib.Path
        Directory holding ``{cast}_detailed_statistics.csv`` (and, ideally,
        ``{cast}_summary_statistics.csv`` and ``{cast}_plot.html``) for each cast.
    out_dir : str or pathlib.Path
        Directory to write the report into; created if absent. The index is
        written to ``out_dir/index.html`` and cast pages to
        ``out_dir/casts/{cast}.html``.
    cruise_name : str or None, optional
        Cruise label for the index heading. If omitted, it is inferred only when
        the results directory is a ``cal_dip/`` folder (from its parent); otherwise
        it is set to ``"UNK"`` with a warning rather than guessing.

    Returns
    -------
    pathlib.Path
        Path to the written index page.

    Raises
    ------
    FileNotFoundError
        If no ``*_detailed_statistics.csv`` files are found in ``results_dir``.
    """
    results_dir = Path(results_dir)
    out_dir = Path(out_dir)

    cast_names = discover_casts(results_dir)
    if not cast_names:
        raise FileNotFoundError(
            f"No '*_detailed_statistics.csv' files found in {results_dir}"
        )

    cast_dir = out_dir / _CAST_SUBDIR
    cast_dir.mkdir(parents=True, exist_ok=True)

    summaries = [summarize_cast(results_dir, name) for name in cast_names]

    if not cruise_name:
        cruise_name = _resolve_cruise_name(results_dir, summaries)

    write_plotly_bundle(out_dir)
    plotly_src = os.path.relpath(out_dir / PLOTLY_BUNDLE_FILENAME, cast_dir)

    for summary in summaries:
        fallback_href = None
        if summary.plot_path is not None:
            fallback_href = os.path.relpath(summary.plot_path, cast_dir)
        html = build_cast_page_html(
            summary, fallback_href=fallback_href, plotly_src=plotly_src
        )
        (cast_dir / f"{summary.name}.html").write_text(html, encoding="utf-8")

    index_html = build_index_html(summaries, cruise_name=cruise_name)
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    return index_path
