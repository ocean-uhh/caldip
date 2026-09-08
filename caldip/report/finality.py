"""Per-cruise finality sweep for ``caldip report --check``.

Answers, for a cruise, "should the operator re-run any casts?" — one line per cast,
exit-coded. The question is whether each cast's CTD reference has *finished*
(``data_mode = D`` and ``preferred_pair`` declared), not whether output is stale;
offsets are measurements, not a cache. Three comparisons per cast, all
recorded-values-versus-current, never mtime: the config against the output, the
output against the reference file, and the two finality gates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import xarray as xr

from caldip._writers import _config_digest
from caldip.core import resolve_quality_thresholds
from caldip.readers import (
    _read_ctd_sensor,
    discover_cast_configs,
    load_config,
    load_cruise_config,
)
from caldip.report.inventory import read_nc_meta

# States (three-way note Item G) — positions, not degrees of decay. Only FINAL is
# terminal-done; every other state is "unfinished" and drives a non-zero exit.
FINAL = "final"
WAITING = "waiting on reference"
RERUN = "rerun needed"
NOT_RUN = "not run"
NO_REFERENCE = "no reference (cnv input)"
UNKNOWN = "unknown"

_FLAG_THRESHOLD_VARS = {"temp": "temp_flag", "cond": "cond_flag", "press": "press_flag"}


def _recorded_thresholds(nc_path: Path) -> dict[str, float]:
    """Read the flagging thresholds recorded on the flag variables."""
    out: dict[str, float] = {}
    try:
        with xr.open_dataset(nc_path, engine="netcdf4") as ds:
            for key, var in _FLAG_THRESHOLD_VARS.items():
                if var in ds and "flagging_threshold" in ds[var].attrs:
                    out[key] = float(ds[var].attrs["flagging_threshold"])
    except (OSError, ValueError):
        pass
    return out


def _config_vs_output(config: dict, attrs: dict, nc_path: Path) -> list[str]:
    """Return the result-affecting config keys that differ from the recorded output.

    This is the comparison an output-versus-reference check cannot make: a config
    re-pointed at a different CTD file, sensor, thresholds, or instrument list is
    invisible to it. ``config_digest`` is the backstop for the instrument list and
    per-instrument ``clock_offset``.
    """
    diffs = []
    cfg_ctd = str(config.get("ctd_file", ""))
    recorded_ctd = Path(str(attrs.get("ctd_path", ""))).name
    if cfg_ctd and recorded_ctd and cfg_ctd != recorded_ctd:
        diffs.append("ctd_file")
    if str(_read_ctd_sensor(config)) != str(attrs.get("ctd_sensor_used", "")):
        diffs.append("ctd_sensor")
    if _config_digest(config) != str(attrs.get("config_digest", "")):
        diffs.append("config")
    current = resolve_quality_thresholds(config)
    recorded = _recorded_thresholds(nc_path)
    for key in _FLAG_THRESHOLD_VARS:
        if key in recorded and abs(float(current[key]) - recorded[key]) > 1e-12:
            diffs.append(f"{key}_threshold")
    return diffs


def cast_state(config: dict, nc_path: Optional[Path]) -> tuple[str, str]:
    """Classify one cast: its output against its config, its reference, and the gates.

    Parameters
    ----------
    config : dict
        The cast's loaded configuration.
    nc_path : pathlib.Path or None
        The cast's ``{cast}_caldip.nc`` output, or ``None`` if not found.

    Returns
    -------
    tuple of str
        ``(state, detail)`` — one of the module's state constants and a one-line reason.
    """
    if nc_path is None or not Path(nc_path).exists():
        return NOT_RUN, "no output netCDF found"
    meta = read_nc_meta(nc_path)
    if "error" in meta:
        return UNKNOWN, f"output unreadable: {meta['error']}"
    attrs = meta["global_attrs"]
    ref = meta["reference_state"]
    if ref is None:
        if attrs.get("input_mode") == "cnv" or str(attrs.get("ctd_path", "")).endswith(
            ".cnv"
        ):
            return NO_REFERENCE, "reference was a raw .cnv (provisional)"
        return UNKNOWN, "no CTD-reference provenance recorded"
    if not ref["now_available"]:
        return UNKNOWN, "recorded reference not reachable"

    config_diffs = _config_vs_output(config, attrs, Path(nc_path))
    ref_changed = [r["field"] for r in ref["rows"] if r["changed"]]
    if config_diffs or ref_changed:
        return RERUN, "changed since run: " + ", ".join(config_diffs + ref_changed)

    if ref["data_mode_final"] and ref["preferred_pair_declared"]:
        return FINAL, "reference finished and output current"
    missing = []
    if not ref["data_mode_final"]:
        missing.append("data_mode not D")
    if not ref["preferred_pair_declared"]:
        missing.append("preferred_pair undeclared")
    return WAITING, "; ".join(missing)


def _find_output_nc(
    cast: str, config_path: Path, results_dir: Optional[Path]
) -> Optional[Path]:
    """Locate ``{cast}_caldip.nc`` in the results dir, the cast's parent, or its dir."""
    name = f"{cast}_caldip.nc"
    candidates = []
    if results_dir is not None:
        candidates.append(Path(results_dir) / name)
    candidates.append(config_path.parent.parent / name)  # default stats output
    candidates.append(config_path.parent / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def check_cruise(
    path: Path, results_dir: Optional[Path] = None
) -> list[tuple[str, str, str]]:
    """Sweep every cast under a cruise YAML or a directory of per-cast configs.

    Parameters
    ----------
    path : pathlib.Path
        A ``caldip.cruise.yaml`` (casts discovered under its ``cal_dip`` directory)
        or a directory of per-cast configs.
    results_dir : pathlib.Path or None, optional
        Where the ``{cast}_caldip.nc`` outputs live, if not beside the configs.

    Returns
    -------
    list of tuple
        ``(cast, state, detail)`` per discovered cast, in discovery order.
    """
    path = Path(path)
    if path.is_file():
        cruise = load_cruise_config(path)
        cal_dip = path.parent / str(cruise.get("cal_dip", "."))
        configs = discover_cast_configs(cal_dip)
    else:
        configs = discover_cast_configs(path)

    results = []
    for config_path in configs:
        config = load_config(config_path)
        cast = str(config.get("name") or config_path.stem.split(".")[0])
        nc_path = _find_output_nc(cast, config_path, results_dir)
        state, detail = cast_state(config, nc_path)
        results.append((cast, state, detail))
    return results
