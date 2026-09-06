"""Build a per-cast page: bottle stops, summary, embedded figure, per-stop detail."""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd

from caldip.report._data import CastSummary
from caldip.report._figure import check_version_skew, extract_figure
from caldip.report._html import dataframe_to_table, figure_block, masthead, page
from caldip.report.status import FLAGGED_KIND, classify_status

_INDEX_HREF = "../index.html"
#: Stop-level columns repeated per instrument in the detailed CSV; lifted into a
#: separate bottle-stops table and dropped from the per-stop detail.
_STOP_COLUMNS = ("date", "time_start", "time_end")
_STATUS_COLUMNS = ("temp_status", "cond_status", "press_status")

#: Sign convention and notation, stated in every table caption that shows a diff.
_DIFF_NOTE = (
    "&Delta; = instrument &minus; CTD (positive: the instrument reads higher "
    "than the CTD; correct with measured &minus; &Delta;)."
)


def _read_csv(path: Path) -> pd.DataFrame:
    """Read a stats CSV as strings so values render exactly as caldip wrote them."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _bottle_stops(detail: pd.DataFrame) -> pd.DataFrame:
    """Return the unique bottle stops (pressure + times), deepest first.

    The detailed CSV repeats each stop's pressure and time window on every
    instrument's row; this collapses them to one row per stop.

    Parameters
    ----------
    detail : pandas.DataFrame
        The per-stop detail frame (read as strings).

    Returns
    -------
    pandas.DataFrame
        One row per stop with ``bl_press`` and any available time columns.
    """
    cols = [c for c in ("bl_press", *_STOP_COLUMNS) if c in detail.columns]
    stops = detail[cols].drop_duplicates().reset_index(drop=True)
    if "bl_press" in stops.columns:
        order = pd.to_numeric(stops["bl_press"], errors="coerce")
        stops = stops.assign(_p=order).sort_values("_p", ascending=False, kind="stable")
        stops = stops.drop(columns="_p").reset_index(drop=True)
    return stops


def _over_threshold(row: pd.Series) -> str | None:
    """Return ``"over-threshold"`` if any status in the row is a caldip flag."""
    for col in _STATUS_COLUMNS:
        if col in row and classify_status(row[col]).kind == FLAGGED_KIND:
            return "over-threshold"
    return None


def build_cast_page_html(
    summary: CastSummary, *, fallback_href: str | None, plotly_src: str
) -> str:
    """Build the HTML page for a single cast.

    Parameters
    ----------
    summary : CastSummary
        The cast's resolved paths and counts.
    fallback_href : str or None
        Relative href from this page to the saved plot file, used only if the
        figure cannot be embedded. ``None`` if no saved plot exists.
    plotly_src : str
        Relative href from this page to the shared ``plotly.min.js``.

    Returns
    -------
    str
        A complete HTML document for the cast page.
    """
    fragment = None
    skew_note = None
    if summary.plot_path is not None:
        fragment = extract_figure(summary.plot_path)
        if fragment is not None:
            skew_note = check_version_skew(fragment, cast_name=summary.name)

    head = masthead(
        summary.name,
        type_label="cast",
        sub=(
            f"{summary.date} · {summary.n_instruments} instrument(s) · "
            f"{summary.n_flagged} flagged by caldip"
        ),
    )
    parts = [
        head,
        f"<div class='jump-nav'><a href='{_INDEX_HREF}'>all casts</a></div>",
        "<h2>Instruments vs CTD</h2>",
    ]
    if skew_note is not None:
        parts.append(f"<p class='warn'>{escape(skew_note)}</p>")
    parts.append(figure_block(fragment, fallback_href=fallback_href))

    detail = _read_csv(summary.detailed_path)

    stops = _bottle_stops(detail)
    if not stops.empty:
        parts.append("<h2>Bottle stops</h2>")
        parts.append(
            "<p class='caption'>The stops held during this cast, deepest first. "
            "P<sub>bl</sub> is the pressure at the bottle stop; t<sub>start</sub> "
            "and t<sub>end</sub> bound the comparison period (dashed black in the "
            "figure), not the whole stop.</p>"
        )
        parts.append(dataframe_to_table(stops))

    if summary.summary_path is not None:
        parts.append("<h2>Summary (deepest stop only)</h2>")
        parts.append(
            "<p class='caption'>A single-stop snapshot at the deepest bottle "
            f"stop, not an average across stops. {_DIFF_NOTE} &langle;&middot;&rangle; "
            "is the mean over that stop's samples; &sigma; is their standard "
            "deviation.</p>"
        )
        parts.append(dataframe_to_table(_read_csv(summary.summary_path)))

    parts.append("<h2>Per-stop detail</h2>")
    parts.append(
        "<p class='caption'>One row per instrument per stop. P<sub>bl</sub> is the "
        f"pressure at the bottle stop (times are in the bottle-stops table above). "
        f"{_DIFF_NOTE} &sigma; is the within-stop standard deviation. Rows caldip "
        "flagged as reading out of tolerance are shaded amber.</p>"
    )
    detail_display = detail.drop(
        columns=[c for c in _STOP_COLUMNS if c in detail.columns]
    )
    parts.append(dataframe_to_table(detail_display, row_class=_over_threshold))

    body = "\n".join(parts)
    return page(
        f"{summary.name} — caldip report",
        body,
        plotly_src=plotly_src if fragment is not None else None,
    )
