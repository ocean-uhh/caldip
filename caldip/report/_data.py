"""Read a caldip results directory and reduce each cast to report-level facts.

A results directory is any folder holding the CSVs ``caldip stats`` writes, named
``{cast}_detailed_statistics.csv`` and ``{cast}_summary_statistics.csv`` (the
default is the cruise's ``cal_dip/`` directory). Casts are discovered by the
strict ``_detailed_statistics.csv`` suffix, so ``-old`` / ``_all`` variants are
ignored.

Flag counts are reduced to the *instrument* level: an instrument that stops at
several depths appears in several detailed rows, and counting flagged cells would
inflate the total, so an instrument counts once if any of its rows flags any
variable.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from caldip.report.status import FLAGGED_KIND, UNKNOWN_KIND, classify_status

_DETAILED_SUFFIX = "_detailed_statistics.csv"
_SUMMARY_SUFFIX = "_summary_statistics.csv"
_STATUS_COLUMNS = ("temp_status", "cond_status", "press_status")


@dataclass(frozen=True)
class CastSummary:
    """Report-level facts for one cast, derived from its detailed CSV.

    Parameters
    ----------
    name : str
        Cast name (the detailed-CSV filename with its suffix removed).
    cruise : str
        Cruise the cast belongs to, from a ``cruise`` column in the CSV, or
        ``"UNK"`` if the column is absent (caldip stats does not yet emit it).
    date : str
        Cast date from the CSV, or ``"UNK"`` if absent.
    n_instruments : int
        Distinct instrument serials in the cast.
    n_flagged : int
        Instruments with at least one flagged variable at any stop.
    n_unknown : int
        Non-empty status cells matching no known template (drives a warning).
    detailed_path : pathlib.Path
        Path to the detailed statistics CSV.
    summary_path : pathlib.Path or None
        Path to the summary statistics CSV, or ``None`` if absent.
    plot_path : pathlib.Path or None
        Path to the saved ``{cast}_plot.html``, or ``None`` if absent.
    """

    name: str
    cruise: str
    date: str
    n_instruments: int
    n_flagged: int
    n_unknown: int
    detailed_path: Path
    summary_path: Path | None
    plot_path: Path | None


def discover_casts(results_dir: Path) -> list[str]:
    """List cast names in a results directory, sorted.

    Parameters
    ----------
    results_dir : pathlib.Path
        Directory holding ``{cast}_detailed_statistics.csv`` files.

    Returns
    -------
    list of str
        Cast names, with the ``_detailed_statistics.csv`` suffix stripped.
    """
    names = [
        p.name[: -len(_DETAILED_SUFFIX)]
        for p in results_dir.glob(f"*{_DETAILED_SUFFIX}")
    ]
    return sorted(names)


def summarize_cast(results_dir: Path, cast_name: str) -> CastSummary:
    """Reduce one cast's detailed CSV to report-level facts.

    Parameters
    ----------
    results_dir : pathlib.Path
        Directory holding the cast's CSVs.
    cast_name : str
        Cast name (without suffix).

    Returns
    -------
    CastSummary
        Instrument and flag counts plus resolved paths for the cast.
    """
    detailed_path = results_dir / f"{cast_name}{_DETAILED_SUFFIX}"
    summary_path = results_dir / f"{cast_name}{_SUMMARY_SUFFIX}"
    plot_path = results_dir / f"{cast_name}_plot.html"

    df = pd.read_csv(detailed_path)

    date = "UNK"
    if "date" in df.columns and not df["date"].dropna().empty:
        date = str(df["date"].dropna().iloc[0])

    cruise = "UNK"
    if "cruise" in df.columns and not df["cruise"].dropna().empty:
        cruise = str(df["cruise"].dropna().iloc[0])

    n_instruments = int(df["serial"].nunique()) if "serial" in df.columns else 0

    flagged_serials: set[object] = set()
    unknown_values: list[str] = []
    status_cols = [c for c in _STATUS_COLUMNS if c in df.columns]
    for _, row in df.iterrows():
        serial = row.get("serial")
        for col in status_cols:
            result = classify_status(row[col])
            if result.kind == FLAGGED_KIND:
                flagged_serials.add(serial)
            elif result.kind == UNKNOWN_KIND:
                unknown_values.append(result.raw)

    if unknown_values:
        warnings.warn(
            f"{cast_name}: {len(unknown_values)} status cell(s) match no known "
            f"template and were not counted as flagged: "
            f"{sorted(set(unknown_values))}",
            stacklevel=2,
        )

    return CastSummary(
        name=cast_name,
        cruise=cruise,
        date=date,
        n_instruments=n_instruments,
        n_flagged=len(flagged_serials),
        n_unknown=len(unknown_values),
        detailed_path=detailed_path,
        summary_path=summary_path if summary_path.exists() else None,
        plot_path=plot_path if plot_path.exists() else None,
    )
