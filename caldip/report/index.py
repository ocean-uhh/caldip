"""Build the per-cruise index page: one row per cast, linking to its page."""

from __future__ import annotations

from html import escape

from caldip.report._data import CastSummary
from caldip.report._html import masthead, page

_CAST_SUBDIR = "casts"


def _row(summary: CastSummary) -> str:
    """Return one ``<tr>`` for a cast, linking to its per-cast page."""
    href = f"{_CAST_SUBDIR}/{summary.name}.html"
    flagged = str(summary.n_flagged)
    if summary.n_unknown:
        flagged += f" (+{summary.n_unknown} unknown)"
    flag_class = "num flag" if summary.n_flagged else "num"
    return (
        "<tr>"
        f"<td><a href='{escape(href)}'>{escape(summary.name)}</a></td>"
        f"<td>{escape(summary.cruise)}</td>"
        f"<td>{escape(summary.date)}</td>"
        f"<td class='num'>{summary.n_instruments}</td>"
        f"<td class='{flag_class}'>{escape(flagged)}</td>"
        "</tr>"
    )


def build_index_html(summaries: list[CastSummary], *, cruise_name: str) -> str:
    """Build the cruise index HTML from per-cast summaries.

    The per-cast cruise (read from each ``{cast}_caldip.nc``) is always shown as a
    column: it is the cruise recorded with the cast, which need not match the
    report heading when a directory mixes casts from more than one cruise.

    Parameters
    ----------
    summaries : list of CastSummary
        One entry per cast, in display order.
    cruise_name : str
        Cruise label shown in the heading and title.

    Returns
    -------
    str
        A complete HTML document for the index page.
    """
    rows = "\n".join(_row(s) for s in summaries)
    head = masthead(
        "Calibration report",
        type_label=cruise_name,
        sub=f"{len(summaries)} cast(s)",
    )
    body = (
        f"{head}\n"
        "<p class='caption'>&ldquo;Flagged by caldip&rdquo; counts instruments "
        "caldip marked as reading high or low, using its configured thresholds; "
        "it is not an absolute pass/fail. Variables an instrument does not measure "
        "are not counted.</p>\n"
        "<table>\n<thead><tr>"
        "<th>Cast</th><th>Cruise</th><th>Date</th><th class='num'>Instruments</th>"
        "<th class='num'>Flagged by caldip</th>"
        "</tr></thead>\n<tbody>\n"
        f"{rows}\n</tbody>\n</table>"
    )
    return page(f"caldip report — {cruise_name}", body)
