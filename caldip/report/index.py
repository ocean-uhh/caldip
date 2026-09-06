"""Build the per-cruise index page: one row per cast, linking to its page."""

from __future__ import annotations

from html import escape

from caldip.report._data import CastSummary
from caldip.report._html import masthead, page

_CAST_SUBDIR = "casts"


def _row(summary: CastSummary, *, show_cruise: bool) -> str:
    """Return one ``<tr>`` for a cast, linking to its per-cast page."""
    href = f"{_CAST_SUBDIR}/{summary.name}.html"
    flagged = str(summary.n_flagged)
    if summary.n_unknown:
        flagged += f" (+{summary.n_unknown} unknown)"
    flag_class = "num flag" if summary.n_flagged else "num"
    cruise_cell = f"<td>{escape(summary.cruise)}</td>" if show_cruise else ""
    return (
        "<tr>"
        f"<td><a href='{escape(href)}'>{escape(summary.name)}</a></td>"
        f"{cruise_cell}"
        f"<td>{escape(summary.date)}</td>"
        f"<td class='num'>{summary.n_instruments}</td>"
        f"<td class='{flag_class}'>{escape(flagged)}</td>"
        "</tr>"
    )


def build_index_html(summaries: list[CastSummary], *, cruise_name: str) -> str:
    """Build the cruise index HTML from per-cast summaries.

    A Cruise column is shown only when the casts span more than one cruise (e.g. a
    directory mixing casts from different cruises); for a single cruise the label
    is in the masthead and the column would be redundant.

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
    show_cruise = len({s.cruise for s in summaries if s.cruise != "UNK"}) > 1
    rows = "\n".join(_row(s, show_cruise=show_cruise) for s in summaries)
    cruise_header = "<th>Cruise</th>" if show_cruise else ""
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
        f"<th>Cast</th>{cruise_header}<th>Date</th><th class='num'>Instruments</th>"
        "<th class='num'>Flagged by caldip</th>"
        "</tr></thead>\n<tbody>\n"
        f"{rows}\n</tbody>\n</table>"
    )
    return page(f"caldip report — {cruise_name}", body)
