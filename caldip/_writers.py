"""
Output formatting functions for caldip processing.

This module contains functions for formatting and writing caldip analysis results
to various output formats (console, CSV, NetCDF, etc.).

Currently Used Functions:
- save_instrument_nc() -> bool
  Save a normalized instrument Dataset to NetCDF, sanitizing un-serializable attrs
- stats_to_dataset() -> xr.Dataset
  Build the per-cast statistics Dataset (machine-readable output) from a stats frame
- write_stats_netcdf() -> Path
  Write the per-cast ``{cast}_caldip.nc`` file
- print_stats_report() -> None
  Print formatted statistics report to console
"""

import datetime
import uuid
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Dict, Optional, Union

import numpy as np
import pandas as pd
import xarray as xr

from caldip.config import parameters as params

# Raw SBE CNV time auxiliary variables dropped before NC write.
# These are raw columns passed through unchanged by seasenselib; the proper
# datetime coordinate is 'time'. timeS triggers an xarray FutureWarning
# (units='seconds' on a non-decoded variable will change semantics in a
# future xarray release).
_SBE_AUX_VARS: frozenset = frozenset({"timeS", "timeJ", "scan"})

#: Statistics-output schema version. Bump when the variable set or the global
#: attribute set of ``{cast}_caldip.nc`` changes in a way a reader must adapt to.
STATS_SCHEMA_VERSION = 1

#: Placeholder for a fact this branch cannot yet source. Populated by the
#: ``ctdcast-input`` branch from ctdcast reference attributes; never defaulted,
#: never a value that reads like real data.
UNK = "UNK"

#: Per-variable usability, a closed set shared with :func:`caldip.core.stats` via
#: ``config.parameters``. Encoded as a CF flag variable (``flag_values`` /
#: ``flag_meanings``).
_FLAG_VALUES = np.array(params.USABILITY_FLAG_VALUES, dtype="int8")
_FLAG_MEANINGS = params.USABILITY_FLAG_MEANINGS
_FLAG_UNKNOWN = params.USABILITY_FLAG_UNKNOWN
_FLAG_NO_DATA = params.USABILITY_FLAG_NO_DATA

#: netCDF dimension names: lowercase and singular so ``isel(stop=-1)`` reads as an
#: index label, not a plural count. Not the OceanSITES ``N_PROF`` styling, which is
#: a token for profile files this grid is not.
_DIM_INSTRUMENT = "instrument"
_DIM_STOP = "stop"
_GRID_DIMS = (_DIM_INSTRUMENT, _DIM_STOP)

#: Variables varying only along ``stop`` (the CTD reference and window bounds) and
#: only along ``instrument`` (instrument identity). Everything else is the grid.
_STOP_FLOAT_VARS = ("ctd_temp", "ctd_cond", "ctd_press")
_GRID_FLOAT_VARS = (
    "temp_diff",
    "temp_std",
    "cond_diff",
    "cond_std",
    "press_diff",
    "press_std",
    "inst_temp",
    "inst_cond",
    "inst_press",
)
_INSTRUMENT_STR_VARS = ("instrument_type", "label")

#: Sign convention carried on every ``*_diff`` variable.
_DIFF_COMMENT = "instrument minus CTD; corrected = measured - diff"

#: OceanSITES reference-table-3 processing_level string for the raw-CNV input path
#: (datcnv-converted, not post-recovery calibrated). Verbatim table-3 wording.
_CNV_PROCESSING_LEVEL = "Instrument data that has been converted to geophysical values"

#: Physical units per statistics column, by variable group.
_TEMP_COLS = ("temp_diff", "temp_std", "ctd_temp", "inst_temp")
_COND_COLS = ("cond_diff", "cond_std", "ctd_cond", "inst_cond")
_PRESS_COLS = ("press_diff", "press_std", "bl_press", "ctd_press", "inst_press")


def _caldip_version() -> str:
    """Return the installed caldip version, or ``UNK`` if it cannot be resolved."""
    try:
        return version("caldip")
    except PackageNotFoundError:  # pragma: no cover - package always installed in use
        return UNK


def _clean_attrs(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Drop None values and convert datetimes for NetCDF serialization.

    Parameters
    ----------
    attrs : dict
        Attribute dict from an xarray Dataset or DataArray.

    Returns
    -------
    dict
        Copy of attrs with None values removed and datetime.datetime values
        converted to ISO 8601 strings.
    """
    cleaned: Dict[str, Any] = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, datetime.datetime):
            cleaned[k] = v.isoformat()
        else:
            cleaned[k] = v
    return cleaned


def save_instrument_nc(ds: xr.Dataset, path: Union[str, Path], label: str) -> bool:
    """Save instrument Dataset to NetCDF, sanitizing un-serializable attributes.

    Drops SBE raw time auxiliary variables (timeS, timeJ, scan) which are
    superseded by the time coordinate and trigger an xarray FutureWarning.
    Cleans None values and datetime objects from variable and dataset attrs
    before writing.

    Parameters
    ----------
    ds : xr.Dataset
        Instrument Dataset as returned by sl.read() or loaded from NC cache.
    path : str or Path
        Output NetCDF file path.
    label : str
        Human-readable label for log messages (e.g. ``'SBE 13840 raw'``).

    Returns
    -------
    bool
        True on success, False if an error occurred during write.
    """
    try:
        vars_to_drop = [v for v in ds.data_vars if v in _SBE_AUX_VARS]
        out = ds.drop_vars(vars_to_drop)
        out.attrs = _clean_attrs(out.attrs)
        for var in list(out.data_vars) + list(out.coords):
            out[var].attrs = _clean_attrs(out[var].attrs)
        out.to_netcdf(path, engine="netcdf4")
        print(f"  💾 Saved {label} ({len(ds.time)} samples)")
        return True
    except (OSError, ValueError) as e:
        print(f"  ⚠️  {label} save failed: {e}")
        return False


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with a trailing ``Z``."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _units_for(column: str) -> Optional[str]:
    """Return the physical units for a statistics column, or ``None`` if unitless."""
    if column in _TEMP_COLS:
        return "degree_C"
    if column in _COND_COLS:
        return "mS cm-1"
    if column in _PRESS_COLS:
        return "dbar"
    return None


def _global_attrs(
    stats_df: pd.DataFrame,
    config: Dict,
    *,
    ctd_sensor_used: Optional[Union[int, str]],
    ctd_path: Optional[str],
    input_mode: str,
    date_created: str,
    date_modified: str,
) -> Dict[str, Any]:
    """Build the complete global-attribute block for ``{cast}_caldip.nc``.

    The full attribute set is written on every file; fields this branch cannot
    source are ``UNK`` and populated later by ``ctdcast-input`` (so a downstream
    reader builds against a schema that does not grow). ``data_mode`` is derived,
    not declared: a ``.cnv``-input run is provisional (``P``) because its CTD
    reference is not a finished product.

    Parameters
    ----------
    stats_df : pandas.DataFrame
        Per-stop statistics frame, used to recover ``ctd_sensor_used`` when the
        column is present.
    config : dict
        Cast configuration; supplies ``name``, ``cruise``, ``ctd_file`` and the
        instrument list.
    ctd_sensor_used : int or str or None
        Reference CTD sensor (1 or 2) caldip used; ``UNK`` if it cannot be
        resolved (never defaulted).
    ctd_path : str or None
        Path of the CTD reference file; falls back to ``config['ctd_file']``.
    input_mode : str
        How the CTD reference was read (``"cnv"`` on this branch).
    date_created : str
        Creation timestamp (preserved across rewrites).
    date_modified : str
        This-write timestamp.

    Returns
    -------
    dict
        Global attributes, with ``UNK`` where unsourced.
    """
    if ctd_sensor_used is None and "ctd_sensor_used" in stats_df.columns:
        vals = stats_df["ctd_sensor_used"].dropna()
        if not vals.empty:
            ctd_sensor_used = vals.iloc[0]
    if ctd_sensor_used is None:
        # The reference sensor is selected by ``ctd_sensor`` or the deprecated
        # plural ``ctd_sensors`` (see readers._read_ctd_sensor); read both so a
        # determinable sensor is not recorded as UNK. UNK only when neither is
        # set — never defaulted, so the record matches the sensor actually used.
        ctd_sensor_used = config.get("ctd_sensor", config.get("ctd_sensors", UNK))

    instrument_files = [
        str(inst.get("filename"))
        for inst in config.get("instruments", [])
        if inst.get("filename")
    ]
    source_instrument_files = " ".join(instrument_files) if instrument_files else UNK

    attrs: Dict[str, Any] = {
        "Conventions": "CF-1.8, ACDD-1.3",
        "title": f"caldip calibration-dip statistics for {config.get('name', UNK)}",
        "source": "caldip calibration-dip analysis",
        "tracking_id": str(uuid.uuid4()),
        "date_created": date_created,
        "date_modified": date_modified,
        "run_utc": date_modified,
        "schema_version": STATS_SCHEMA_VERSION,
        "caldip_version": _caldip_version(),
        "cast_id": str(config.get("name", UNK)),
        "cruise": str(config.get("cruise") or UNK),
        "input_mode": input_mode,
        # No QARTOD flags travel on the .cnv path, so none were excluded; the
        # ctdcast-input branch honours real stage-2/3 flags and sets this true.
        "qc_flags_honoured": "false",
        "data_mode": "P",
        "data_mode_meaning": "provisional",
        # Lineage. source_tracking_id is the *reference* root the staleness
        # protocol tracks (the ctdcast file's tracking_id, once ctdcast-input
        # lands); source_instrument_files is the *instrument* root.
        "source_tracking_id": UNK,
        "source_instrument_files": source_instrument_files,
        "ctd_path": str(ctd_path or config.get("ctd_file") or UNK),
        "ctd_stage": UNK,
        "ctd_conductivity_slope": UNK,
        "ctd_temp_sensor_serial": UNK,
        "ctd_cond_sensor_serial": UNK,
        "ctd_temp_sensor_caldate": UNK,
        "ctd_cond_sensor_caldate": UNK,
        "ctd_sensor_used": str(ctd_sensor_used),
        "ctd_cond_slope_adjusted": UNK,
        # OceanSITES table-3 processing_level, per reference variable. On the .cnv
        # path the CTD is datcnv-converted but not post-recovery calibrated, so the
        # applicable table-3 string is the conversion one ("as-received" is the
        # absence of a post-recovery-calibration string, not a value itself).
        "ctd_temp_processing_level": _CNV_PROCESSING_LEVEL,
        "ctd_cond_processing_level": _CNV_PROCESSING_LEVEL,
        "ctd_press_processing_level": _CNV_PROCESSING_LEVEL,
    }

    unsourced = sorted(k for k, v in attrs.items() if v == UNK)
    if unsourced:
        warnings.warn(
            f"{attrs['cast_id']}: {len(unsourced)} global attribute(s) unsourced on "
            f"the {input_mode} path, written as UNK: {unsourced}",
            stacklevel=2,
        )
    return attrs


def stats_to_dataset(
    stats_df: pd.DataFrame,
    config: Dict,
    *,
    thresholds: Optional[Dict[str, float]] = None,
    ctd_sensor_used: Optional[Union[int, str]] = None,
    ctd_path: Optional[str] = None,
    input_mode: str = "cnv",
    date_created: Optional[str] = None,
    date_modified: Optional[str] = None,
) -> xr.Dataset:
    """Build the machine-readable per-cast statistics Dataset.

    Cal-dip data is rectangular — every instrument is on the same wire for the
    whole cast, so all of them see every bottle stop — so the Dataset is a
    two-dimensional ``(instrument, stop)`` grid, not a flat row list. Three tiers,
    each declaring which axis a fact varies along: per-instrument (``serial``
    coordinate, ``instrument_type``, ``label``), per-stop (``bl_press`` and
    ``time`` coordinates, ``time_start`` / ``time_end``, the ``ctd_*`` reference),
    and the grid (the diffs, standard deviations, ``inst_*``, ``N`` and the
    ``*_flag`` variables). An instrument that missed a stop is a dense ``NaN`` cell
    with a ``no_data`` flag, never a ragged file. Select stops by value
    (``argmax(ctd_press)``), never by position; the order is not load-bearing.

    Every physical variable carries ``units``; every ``*_diff`` states the sign
    convention in its ``comment``; absent values are ``NaN`` with ``_FillValue``,
    never ``0``. Per-variable usability is a CF flag variable. The complete
    global-attribute block is written, ``UNK`` where unsourced.

    Parameters
    ----------
    stats_df : pandas.DataFrame
        Per-stop statistics as returned by :func:`caldip.core.stats`.
    config : dict
        Cast configuration.
    ctd_sensor_used : int or str or None, optional
        Reference CTD sensor caldip used; resolved from the frame or config when
        ``None``.
    ctd_path : str or None, optional
        CTD reference file path; falls back to ``config['ctd_file']``.
    input_mode : str, default "cnv"
        How the CTD reference was read.
    date_created : str or None, optional
        Creation timestamp to preserve across a rewrite; defaults to now.
    date_modified : str or None, optional
        This-write timestamp; defaults to now.

    Returns
    -------
    xarray.Dataset
        The ``{cast}_caldip.nc`` contents, one ``row`` per instrument-stop.
    """
    df = stats_df.reset_index(drop=True)
    modified = date_modified or _utc_now_iso()
    created = date_created or modified
    thresholds = thresholds or {}

    flag_map = {
        "temp_flag": ("temp", "degree_C"),
        "cond_flag": ("cond", "mS cm-1"),
        "press_flag": ("press", "dbar"),
    }
    missing = [c for c in ("stop", "ctd_press", *flag_map) if c not in df.columns]
    if missing:
        warnings.warn(
            f"{config.get('name', UNK)}: statistics frame is missing {missing}; "
            "stop derived from bl_press, ctd_press written as NaN and usability "
            "flags as 'unknown'. core.stats emits these for a complete file.",
            stacklevel=2,
        )

    # Resolve the (instrument, stop) axes. ``stop`` comes from core; a CSV-derived
    # frame without it falls back to one stop per distinct bl_press.
    df = df.assign(serial=df["serial"].astype(str) if "serial" in df.columns else UNK)
    if "stop" not in df.columns:
        # Factorizing bl_press would silently merge two real stops at the same
        # nominal pressure (ordinary practice), so refuse rather than fabricate a
        # lossy stop label — the caller must supply an explicit ``stop``.
        if "bl_press" in df.columns:
            repeats = df[df.duplicated(subset=["serial", "bl_press"], keep=False)]
            if not repeats.empty:
                pairs = sorted(
                    {(s, p) for s, p in zip(repeats["serial"], repeats["bl_press"])}
                )
                raise ValueError(
                    f"{config.get('name', UNK)}: cannot derive a stop index from "
                    f"bl_press — these (serial, bl_press) pairs repeat, so two stops "
                    f"share one nominal pressure: {pairs}. Supply a 'stop' column."
                )
        keys = (
            df["bl_press"] if "bl_press" in df.columns else pd.Series(0, index=df.index)
        )
        # 1-based to match core.stats' stop index (the label is not emitted — the
        # stop dimension carries bl_press/time as coordinates — but keep the two
        # conventions the same).
        df = df.assign(stop=pd.factorize(keys)[0] + 1)
    instruments = sorted(df["serial"].unique())
    stops = list(dict.fromkeys(df["stop"].tolist()))
    shape = (len(instruments), len(stops))

    def _grid(col: str) -> np.ndarray:
        """Pivot a per-(instrument, stop) column to a float64 grid, NaN for gaps."""
        if col not in df.columns:
            return np.full(shape, np.nan)
        try:
            pivot = df.pivot(index="serial", columns="stop", values=col)
        except ValueError as exc:
            # "unique by construction" has already been wrong once on this branch;
            # name the cast and the duplicate keys rather than let pandas' opaque
            # "cannot reshape" surface.
            repeats = df[df.duplicated(subset=["serial", "stop"], keep=False)]
            pairs = sorted(
                {(s, st) for s, st in zip(repeats["serial"], repeats["stop"])}
            )
            raise ValueError(
                f"{config.get('name', UNK)}: duplicate (serial, stop) keys {pairs} — "
                "each instrument must have at most one row per bottle stop to build "
                "the (instrument, stop) grid."
            ) from exc
        return pivot.reindex(index=instruments, columns=stops).to_numpy(dtype="float64")

    def _per_stop(col: str):
        """Return the per-stop value series, or ``None`` if the column is absent."""
        if col not in df.columns:
            return None
        return df.groupby("stop")[col].first().reindex(stops)

    def _per_instrument(col: str):
        """Return the per-instrument value series, or ``None`` if absent."""
        if col not in df.columns:
            return None
        return df.groupby("serial")[col].first().reindex(instruments)

    def _float_attrs(name: str) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {}
        units = _units_for(name)
        if units is not None:
            attrs["units"] = units
        if name.endswith("_diff"):
            attrs["comment"] = _DIFF_COMMENT
        return attrs

    data_vars: Dict[str, Any] = {}

    # Grid (instrument, stop): the differences, scatter, instrument means.
    for name in _GRID_FLOAT_VARS:
        da = xr.DataArray(_grid(name), dims=_GRID_DIMS, attrs=_float_attrs(name))
        da.encoding["_FillValue"] = np.nan
        data_vars[name] = da

    n_grid = _grid("N")
    data_vars["N"] = xr.DataArray(
        np.where(np.isnan(n_grid), 0, n_grid).astype("int32"),
        dims=_GRID_DIMS,
        attrs={"units": "1", "long_name": "samples in comparison window"},
    )

    for flag_col, (var, threshold_units) in flag_map.items():
        if flag_col in df.columns:
            # A gap in the grid (an instrument that missed a stop) is no_data.
            grid = _grid(flag_col)
            flags = np.where(np.isnan(grid), _FLAG_NO_DATA, grid).astype("int8")
        else:
            flags = np.full(shape, _FLAG_UNKNOWN, dtype="int8")
        flag_attrs: Dict[str, Any] = {
            "long_name": f"{var} usability flag",
            "flag_values": _FLAG_VALUES,
            "flag_meanings": _FLAG_MEANINGS,
            "conventions": "QARTOD",
            "valid_min": np.int8(_FLAG_VALUES.min()),
            "valid_max": np.int8(_FLAG_VALUES.max()),
        }
        threshold = thresholds.get(var)
        if threshold is not None:
            flag_attrs["flagging_threshold"] = float(threshold)
            flag_attrs["comment"] = (
                f"flagged when |instrument - CTD| exceeds flagging_threshold "
                f"({threshold_units})"
            )
        data_vars[flag_col] = xr.DataArray(flags, dims=_GRID_DIMS, attrs=flag_attrs)

    # Per stop: the CTD reference and the comparison-window bounds.
    for name in _STOP_FLOAT_VARS:
        series = _per_stop(name)
        values = (
            series.to_numpy(dtype="float64")
            if series is not None
            else np.full(len(stops), np.nan)
        )
        da = xr.DataArray(values, dims=(_DIM_STOP,), attrs=_float_attrs(name))
        da.encoding["_FillValue"] = np.nan
        data_vars[name] = da

    for nc_name, col in (("time_start", "t_start"), ("time_end", "t_end")):
        series = _per_stop(col)
        if series is not None:
            data_vars[nc_name] = xr.DataArray(
                pd.to_datetime(series).to_numpy(),
                dims=(_DIM_STOP,),
                attrs={"long_name": f"comparison window {nc_name.split('_')[1]}"},
            )

    # Per instrument: the instrument identity.
    for name in _INSTRUMENT_STR_VARS:
        series = _per_instrument(name)
        if series is not None:
            data_vars[name] = xr.DataArray(
                series.astype(str).to_numpy(), dims=(_DIM_INSTRUMENT,)
            )

    bl_series = _per_stop("bl_press")
    bl_press = (
        np.rint(bl_series.to_numpy()).astype("int16")
        if bl_series is not None
        else np.zeros(len(stops), dtype="int16")
    )
    coords: Dict[str, Any] = {
        "serial": (
            _DIM_INSTRUMENT,
            np.array(instruments),
            {"long_name": "instrument serial number"},
        ),
        "bl_press": (
            _DIM_STOP,
            bl_press,
            {
                "units": "dbar",
                "long_name": "nominal bottle-stop pressure",
                "comment": (
                    "integer stop label; the measured pressure is ctd_press. "
                    "Stop order is not meaningful: select stops by value "
                    "(e.g. deepest = argmax(ctd_press)), never by position."
                ),
            },
        ),
    }
    time_series = _per_stop("time")
    if time_series is not None:
        coords["time"] = (
            _DIM_STOP,
            pd.to_datetime(time_series).to_numpy(),
            {"long_name": "comparison-window mid-time"},
        )

    ds = xr.Dataset(data_vars=data_vars, coords=coords)
    ds.attrs = _global_attrs(
        df,
        config,
        ctd_sensor_used=ctd_sensor_used,
        ctd_path=ctd_path,
        input_mode=input_mode,
        date_created=created,
        date_modified=modified,
    )
    return ds


def write_stats_netcdf(
    stats_df: pd.DataFrame,
    config: Dict,
    path: Union[str, Path],
    *,
    thresholds: Optional[Dict[str, float]] = None,
    ctd_sensor_used: Optional[Union[int, str]] = None,
    ctd_path: Optional[str] = None,
    input_mode: str = "cnv",
) -> Path:
    """Write the per-cast ``{cast}_caldip.nc`` statistics file.

    Applies ctdcast's write-time rule: a fresh ``tracking_id`` and a new
    ``date_modified`` on every write, but ``date_created`` is preserved from an
    existing file at ``path`` and set to now only on the first write — never as a
    path to repair a missing value.

    Parameters
    ----------
    stats_df : pandas.DataFrame
        Per-stop statistics as returned by :func:`caldip.core.stats`.
    config : dict
        Cast configuration.
    path : str or pathlib.Path
        Output netCDF path.
    thresholds : dict or None, optional
        Per-variable quality-flag thresholds (``{"temp", "cond", "press"}``),
        recorded on the flag variables. Resolve with
        :func:`caldip.core.resolve_quality_thresholds`.
    ctd_sensor_used : int or str or None, optional
        Reference CTD sensor caldip used.
    ctd_path : str or None, optional
        CTD reference file path.
    input_mode : str, default "cnv"
        How the CTD reference was read.

    Returns
    -------
    pathlib.Path
        The path written.
    """
    path = Path(path)
    date_created = None
    if path.exists():
        try:
            with xr.open_dataset(path, engine="netcdf4") as existing:
                date_created = existing.attrs.get("date_created")
        except (OSError, ValueError):
            date_created = None

    ds = stats_to_dataset(
        stats_df,
        config,
        thresholds=thresholds,
        ctd_sensor_used=ctd_sensor_used,
        ctd_path=ctd_path,
        input_mode=input_mode,
        date_created=date_created,
    )
    ds.attrs = _clean_attrs(ds.attrs)
    for var in list(ds.data_vars) + list(ds.coords):
        ds[var].attrs = _clean_attrs(ds[var].attrs)
    ds.to_netcdf(path, engine="netcdf4")
    return path


#: Detailed-CSV column order, reproduced exactly from the pre-netCDF output so a
#: derived export matches column-for-column. The three provenance columns are
#: appended so a stray CSV is still traceable.
_CSV_COLUMNS = [
    "serial",
    "instrument_type",
    "bl_press",
    "temp_diff",
    "temp_std",
    "cond_diff",
    "cond_std",
    "press_diff",
    "press_std",
    "temp_status",
    "cond_status",
    "press_status",
    "date",
    "time_start",
    "time_end",
    "ctd_temp",
    "ctd_cond",
    "inst_temp",
    "inst_cond",
    "inst_press",
    "N",
    "label",
    "ctd_sensor_used",
]
_CSV_PROVENANCE_COLUMNS = ["cast_id", "schema_version", "tracking_id"]


def _round_keep_nan(values: np.ndarray, decimals: int) -> np.ndarray:
    """Round a float array to ``decimals`` places, leaving ``NaN`` untouched."""
    return np.round(values.astype("float64"), decimals)


def flatten_stats_grid(ds: xr.Dataset) -> pd.DataFrame:
    """Melt the ``(instrument, stop)`` grid to one row per instrument-stop.

    xarray broadcasts the per-stop and per-instrument variables across the grid.
    Gap cells (an instrument with no data at a stop, ``N == 0``) are dropped and
    the rows are ordered by serial then descending ``bl_press``. This is the one
    canonical row set and order that both the CSV export and the report's flag
    reader consume, so they stay aligned by construction rather than by two hand-
    maintained copies of the same melt.

    Parameters
    ----------
    ds : xarray.Dataset
        A per-cast statistics Dataset from :func:`stats_to_dataset`.

    Returns
    -------
    pandas.DataFrame
        One row per real instrument-stop, in the canonical CSV order.
    """
    flat = ds.to_dataframe().reset_index()
    if "N" in flat.columns:
        flat = flat[flat["N"] > 0]
    return flat.sort_values(
        ["serial", "bl_press"], ascending=[True, False]
    ).reset_index(drop=True)


def stats_dataset_to_frame(ds: xr.Dataset) -> pd.DataFrame:
    """Render the detailed-statistics CSV frame from a ``{cast}_caldip.nc`` Dataset.

    The CSV is a derived export, not a second source of truth: the prose
    ``*_status`` columns are re-rendered by :func:`caldip.core._format_status`
    from the authoritative diff and the flag variable's ``flagging_threshold`` —
    the same function and inputs that produced them originally, so the result is
    byte-identical rather than a stored second copy that could drift. The netCDF's
    flag and ``ctd_press`` variables are machine-only and do not appear here;
    ``cast_id`` / ``schema_version`` / ``tracking_id`` are appended so a stray CSV
    stays traceable.

    Parameters
    ----------
    ds : xarray.Dataset
        A per-cast statistics Dataset from :func:`stats_to_dataset`.

    Returns
    -------
    pandas.DataFrame
        The detailed-statistics table, columns and values matching the
        pre-netCDF output plus the three provenance columns.
    """
    from caldip import core

    flat = flatten_stats_grid(ds)

    m = len(flat)

    def column(name: str) -> np.ndarray:
        if name in flat.columns:
            return flat[name].to_numpy()
        return np.full(m, np.nan)

    def string_column(name: str) -> np.ndarray:
        if name in flat.columns:
            return flat[name].astype(str).to_numpy()
        return np.full(m, "", dtype=object)

    def times(name: str, fmt: str) -> np.ndarray:
        if name in flat.columns:
            return pd.to_datetime(flat[name]).dt.strftime(fmt).to_numpy()
        return np.full(m, "", dtype=object)

    thresholds = {
        "T": ("temp_flag", params.QUALITY_TEMP_THRESHOLD),
        "C": ("cond_flag", params.QUALITY_COND_THRESHOLD),
        "P": ("press_flag", params.QUALITY_PRESS_THRESHOLD),
    }
    diffs = {
        v: column(c)
        for v, c in (("T", "temp_diff"), ("C", "cond_diff"), ("P", "press_diff"))
    }
    status = {}
    for letter, (flag_col, default) in thresholds.items():
        threshold = float(
            ds[flag_col].attrs.get("flagging_threshold", default)
            if flag_col in ds
            else default
        )
        status[letter] = [
            core._format_status(d, threshold, letter) for d in diffs[letter]
        ]

    frame = pd.DataFrame(
        {
            "serial": string_column("serial"),
            "instrument_type": string_column("instrument_type"),
            "bl_press": np.rint(column("bl_press")).astype(int),
            # Per-variable export precision (CSV only; the netCDF keeps full
            # precision): temperature and conductivity to 4 dp, pressure to
            # 0.1 dbar, and each standard deviation one place finer than its value.
            "temp_diff": _round_keep_nan(diffs["T"], 4),
            "temp_std": _round_keep_nan(column("temp_std"), 5),
            "cond_diff": _round_keep_nan(diffs["C"], 4),
            "cond_std": _round_keep_nan(column("cond_std"), 5),
            "press_diff": _round_keep_nan(diffs["P"], 1),
            "press_std": _round_keep_nan(column("press_std"), 2),
            "temp_status": status["T"],
            "cond_status": status["C"],
            "press_status": status["P"],
            "date": times("time_start", "%Y-%m-%d"),
            "time_start": times("time_start", "%H:%M:%S"),
            "time_end": times("time_end", "%H:%M:%S"),
            "ctd_temp": _round_keep_nan(column("ctd_temp"), 4),
            "ctd_cond": _round_keep_nan(column("ctd_cond"), 4),
            "inst_temp": _round_keep_nan(column("inst_temp"), 4),
            "inst_cond": _round_keep_nan(column("inst_cond"), 4),
            "inst_press": _round_keep_nan(column("inst_press"), 1),
            "N": column("N").astype(int),
            "label": string_column("label"),
            "ctd_sensor_used": ds.attrs.get("ctd_sensor_used", UNK),
            "cast_id": ds.attrs.get("cast_id", UNK),
            "schema_version": ds.attrs.get("schema_version", STATS_SCHEMA_VERSION),
            "tracking_id": ds.attrs.get("tracking_id", UNK),
        }
    )
    # Rows already come from flatten_stats_grid in the canonical (serial asc,
    # bl_press desc) order, so no re-sort is needed here.
    return frame[_CSV_COLUMNS + _CSV_PROVENANCE_COLUMNS]


def print_stats_report(stats_df: pd.DataFrame, config: Dict):
    """Print formatted statistics report for universal instrument types."""

    print("\n" + "=" * 80)
    print(f"UNIVERSAL CALDIP CHECK REPORT - {config['name']}")
    print("=" * 80)

    # CTD statistics
    ctd_stats = stats_df.iloc[0]["ctd_stats"]

    # Timing information
    print("\nTiming Information:")

    # Show all bottle stops if available
    if "timing_info" in ctd_stats and "bottle_stops" in ctd_stats["timing_info"]:
        bottle_stops = ctd_stats["timing_info"]["bottle_stops"]
        print(f"  Found {len(bottle_stops)} bottle stop(s):")
        for i, stop in enumerate(bottle_stops, 1):
            print(f"\n  Bottle Stop {i}:")
            print(f"    Start: {stop['start_time']}")
            print(f"    End: {stop['end_time']}")
            print(f"    Duration: {stop['duration_seconds'] / 60:.1f} minutes")
            print(f"    Pressure: {stop['pressure']:.1f} dbar")
        print("\n  Using deepest bottle stop for comparison:")
    else:
        print("  Bottle stop period to compare:")

    print(f"    Start: {ctd_stats['comparison_start']}")
    print(f"    End: {ctd_stats['comparison_end']}")

    print("\nCTD Statistics during comparison period:")
    print(
        f"  Mean Pressure: {ctd_stats['bl_press']:.1f} dbar (std: {ctd_stats['press_std']:.2f})"
    )
    print(
        f"  Mean Temperature: {ctd_stats['ctd_temp']:.4f} °C (std: {ctd_stats['temp_std']:.5f})"
    )
    if "mean_cond" in ctd_stats:
        print(
            f"  Mean Conductivity: {ctd_stats['ctd_cond']:.3f} mS/cm (std: {ctd_stats['cond_std']:.4f})"
        )

    # Instrument statistics
    print(f"\nNumber of Instruments: {len(stats_df)}")

    # Group by instrument type
    type_counts = stats_df["instrument_type"].value_counts()
    print("Instrument Types:")
    for inst_type, count in type_counts.items():
        print(f"  {inst_type}: {count}")

    print("\nInstrument Comparison Statistics:")
    print("-" * 80)
    print(
        "Serial  Type    Samples  Temp Diff (°C)        Cond Diff (mS/cm)     Press Diff (dbar)"
    )
    print(
        "                         Mean      Std         Mean      Std         Mean      Std"
    )
    print("-" * 80)

    for _, row in stats_df.iterrows():
        # Format conductivity and pressure with proper handling of NaN
        cond_mean = (
            f"{row['cond_diff']:8.2f}" if not np.isnan(row["cond_diff"]) else "     N/A"
        )
        cond_std = (
            f"{row['cond_diff_std']:8.3f}"
            if not np.isnan(row["cond_diff_std"])
            else "     N/A"
        )
        press_mean = (
            f"{row['press_diff']:7.2f}"
            if not np.isnan(row["press_diff"])
            else "    N/A"
        )
        press_std = (
            f"{row['press_diff_std']:7.2f}"
            if not np.isnan(row["press_diff_std"])
            else "    N/A"
        )

        print(
            f"{row['serial']:6s}  {row['instrument_type']:6s}  {row['N']:6d}  "
            f"{row['temp_diff']:8.3f}  {row['temp_diff_std']:8.4f}  "
            f"{cond_mean}  {cond_std}  "
            f"{press_mean}  {press_std}"
        )

    print("=" * 80)
