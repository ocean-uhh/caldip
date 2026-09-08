"""Read a caldip results directory and reduce each cast to report-level facts.

A results directory is any folder holding the outputs ``caldip stats`` writes:
``{cast}_detailed_statistics.csv`` (human display) and ``{cast}_caldip.nc`` (the
machine-readable statistics, with the CF flag variables). Casts are discovered by
the strict ``_detailed_statistics.csv`` suffix, so ``-old`` / ``_all`` variants are
ignored.

Usability and the cruise come from the netCDF, not the CSV prose: the report reads
``temp_flag`` / ``cond_flag`` / ``press_flag`` and the ``cruise`` attribute
directly. Flag counts are reduced to the *instrument* level: an instrument that
stops at several depths appears in several rows, so it counts once if any of its
rows flags any variable. A cast without its netCDF cannot be counted (the prose
fallback is gone) and reports zero with a warning.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from caldip.config import parameters as params
from caldip._writers import flatten_stats_grid

_DETAILED_SUFFIX = "_detailed_statistics.csv"
_SUMMARY_SUFFIX = "_summary_statistics.csv"
_NC_SUFFIX = "_caldip.nc"
_FLAG_VARS = ("temp_flag", "cond_flag", "press_flag")

#: Human labels for the CTD-reference sensor number.
_SENSOR_LABELS = {"1": "primary", "2": "secondary"}

#: CTD-reference global attributes surfaced once per cast, in display order.
#: The sensor used and the reference data mode are always shown; the rest are
#: shown only when populated (the ctdcast-netCDF path fills the serials, cal
#: dates and slope; the raw-CNV path leaves them ``UNK`` and they are omitted).
_CTD_REF_FIELDS = (
    ("ctd_sensor_used", "CTD sensor used"),
    ("preferred_pair", "Preferred pair (reference)"),
    ("data_mode_meaning", "Reference data mode"),
    ("ctd_stage", "Reference processing stage"),
    ("ctd_temp_sensor_serial", "Temperature sensor S/N"),
    ("ctd_temp_sensor_caldate", "Temperature calibration date"),
    ("ctd_cond_sensor_serial", "Conductivity sensor S/N"),
    ("ctd_cond_sensor_caldate", "Conductivity calibration date"),
    ("ctd_conductivity_slope", "Conductivity slope applied"),
    ("ctd_cond_slope_adjusted", "Conductivity slope-adjusted"),
    ("ctd_temp_processing_level", "Temperature processing level"),
    ("ctd_cond_processing_level", "Conductivity processing level"),
    ("ctd_press_processing_level", "Pressure processing level"),
    ("ctd_path", "Reference file"),
    ("source_tracking_id", "Source tracking id"),
)

#: Fields always shown, even when their recorded value is a placeholder.
_CTD_REF_ALWAYS = frozenset({"ctd_sensor_used", "data_mode_meaning"})

#: Placeholder values that suppress an optional CTD-reference row.
_CTD_REF_PLACEHOLDER = frozenset({"", "UNK", "undeclared", "—"})


def _format_sensor_used(value: str) -> str:
    """Return e.g. ``"secondary (2)"`` for a CTD sensor number, or the raw value."""
    name = _SENSOR_LABELS.get(value)
    return f"{name} ({value})" if name else (value or "UNK")


def ctd_reference_rows(attrs: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """Reduce a cast netCDF's global attributes to display CTD-reference rows.

    Cast-level facts (the CTD sensor used and its provenance) that are constant
    for the whole cast, surfaced once rather than repeated per stop. The sensor
    used and the reference data mode are always included; optional provenance
    rows are dropped when their recorded value is a placeholder (``UNK`` etc.),
    so the raw-CNV path yields a short table and the ctdcast-netCDF path a full
    one.

    Parameters
    ----------
    attrs : dict of str to str
        The cast netCDF's global attributes (values as strings).

    Returns
    -------
    tuple of (str, str)
        Ordered ``(label, value)`` rows for :func:`caldip.report._html.key_value_table`.
    """
    rows = []
    for key, label in _CTD_REF_FIELDS:
        value = str(attrs.get(key, "")).strip()
        if key == "ctd_sensor_used":
            value = _format_sensor_used(value)
        if value in _CTD_REF_PLACEHOLDER and key not in _CTD_REF_ALWAYS:
            continue
        rows.append((label, value or "UNK"))
    return tuple(rows)


@dataclass(frozen=True)
class FlagData:
    """Per-row usability flags read from a cast's ``{cast}_caldip.nc``.

    Parameters
    ----------
    serial : numpy.ndarray
        Instrument serial per row (as strings).
    bl_press : numpy.ndarray
        Nominal bottle-stop pressure per row (integer dbar).
    flagged : numpy.ndarray
        Boolean per row: any variable flagged out of tolerance at that stop.
    n_unknown : int
        Count of flag cells that are ``unknown`` (drives a warning).
    cruise : str
        Cruise recovered from the netCDF ``cruise`` attribute, or ``"UNK"``.
    ctd_reference : tuple of (str, str)
        Cast-level CTD-reference rows (sensor used and provenance) from the
        netCDF global attributes; see :func:`ctd_reference_rows`.
    """

    serial: np.ndarray
    bl_press: np.ndarray
    flagged: np.ndarray
    n_unknown: int
    cruise: str
    ctd_reference: tuple[tuple[str, str], ...]


def load_flags(nc_path: Path) -> FlagData | None:
    """Read per-row usability flags and the cruise from a cast netCDF.

    The netCDF is caldip's machine-readable output; the report reads its flag
    variables directly rather than parsing the CSV's prose status. A per-row flag
    equal to the ``flagged`` value counts as out of tolerance; ``unknown`` cells
    are counted for a warning.

    Parameters
    ----------
    nc_path : pathlib.Path
        Path to ``{cast}_caldip.nc``.

    Returns
    -------
    FlagData or None
        The per-row flags and cruise, or ``None`` if the file is absent.
    """
    if not nc_path.exists():
        return None
    with xr.open_dataset(nc_path, engine="netcdf4") as ds:
        cruise = str(ds.attrs.get("cruise", "UNK"))
        ctd_reference = ctd_reference_rows(
            {str(k): str(v) for k, v in ds.attrs.items()}
        )
        # Same canonical melt the CSV export uses, so the flag rows align with the
        # detailed CSV rows the report displays.
        flat = flatten_stats_grid(ds)
    flagged = np.zeros(len(flat), dtype=bool)
    n_unknown = 0
    for var in _FLAG_VARS:
        if var in flat.columns:
            values = flat[var].to_numpy()
            flagged |= values == params.USABILITY_FLAG_FLAGGED
            n_unknown += int(np.sum(values == params.USABILITY_FLAG_UNKNOWN))
    return FlagData(
        flat["serial"].astype(str).to_numpy(),
        np.rint(flat["bl_press"].to_numpy()).astype(int),
        flagged,
        n_unknown,
        cruise,
        ctd_reference,
    )


@dataclass(frozen=True)
class CastSummary:
    """Report-level facts for one cast, from its detailed CSV and netCDF.

    Parameters
    ----------
    name : str
        Cast name (the detailed-CSV filename with its suffix removed).
    cruise : str
        Cruise the cast belongs to, from the netCDF ``cruise`` attribute, or
        ``"UNK"`` if the netCDF is absent.
    date : str
        Cast date from the CSV, or ``"UNK"`` if absent.
    n_instruments : int
        Distinct instrument serials in the cast.
    n_flagged : int
        Instruments with at least one flagged variable at any stop.
    n_unknown : int
        Flag cells with the ``unknown`` value (drives a warning).
    detailed_path : pathlib.Path
        Path to the detailed statistics CSV.
    nc_path : pathlib.Path or None
        Path to the ``{cast}_caldip.nc`` statistics file, or ``None`` if absent.
    flag_data : FlagData or None
        Per-row flags read from the netCDF, or ``None`` if it is absent. Carried
        here so the cast page reuses the one read rather than reopening the file.
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
    nc_path: Path | None
    flag_data: FlagData | None
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
    nc_path = results_dir / f"{cast_name}{_NC_SUFFIX}"
    plot_path = results_dir / f"{cast_name}_plot.html"

    df = pd.read_csv(detailed_path)

    date = "UNK"
    if "date" in df.columns and not df["date"].dropna().empty:
        date = str(df["date"].dropna().iloc[0])

    n_instruments = int(df["serial"].nunique()) if "serial" in df.columns else 0

    cruise = "UNK"
    n_flagged = 0
    n_unknown = 0
    flags = load_flags(nc_path)
    if flags is None:
        warnings.warn(
            f"{cast_name}: no {cast_name}{_NC_SUFFIX}; flag counts and cruise are "
            "unavailable and reported as zero / UNK. Re-run 'caldip stats'.",
            stacklevel=2,
        )
    else:
        cruise = flags.cruise
        n_flagged = len(set(flags.serial[flags.flagged]))
        n_unknown = flags.n_unknown
        if n_unknown:
            warnings.warn(
                f"{cast_name}: {n_unknown} flag cell(s) are 'unknown' and were not "
                "counted as flagged.",
                stacklevel=2,
            )

    return CastSummary(
        name=cast_name,
        cruise=cruise,
        date=date,
        n_instruments=n_instruments,
        n_flagged=n_flagged,
        n_unknown=n_unknown,
        detailed_path=detailed_path,
        nc_path=nc_path if nc_path.exists() else None,
        flag_data=flags,
        summary_path=summary_path if summary_path.exists() else None,
        plot_path=plot_path if plot_path.exists() else None,
    )
