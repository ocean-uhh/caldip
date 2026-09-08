"""
Data loading functions for caldip processing.

Public API
----------
find_config_file(path) -> Path
    Locate a .caldip.yaml config file given a file or directory path.
load_config(path) -> Dict
    Parse a .caldip.yaml configuration file.
load_instruments_from_config(config, data_dir) -> Dict[str, Dict]
    Load all instruments listed in a config.  Priority per instrument:
    _use.nc → _raw.nc (creates _use.nc if absent) → source file
    (normalizes, applies clock offset, saves both _raw.nc and _use.nc).
load_reference_data(config, data_dir) -> Dict[str, Dict]
    Load CTD reference data; reads pre-processed .nc if present.
resolve_data_dir(config_file, config, override) -> Path
    Resolve the data directory from config or an explicit override.

Internal helpers
----------------
load_instrument_data()     — dispatch to format-specific loaders
_normalize_instrument_vars() — rename raw variables to canonical names
_normalize_ctd_vars()      — rename CTD variables; selects primary/secondary sensor
_wild_edit_ctd()           — apply SeaBird wild-edit spike removal
_resample_1hz()            — resample CTD to 1 Hz medians
"""

import json
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import xarray as xr
import yaml

if TYPE_CHECKING:
    import xml.etree.ElementTree as ET

from caldip.config import parameters as params

try:
    import seasenselib as sl

    SEASENSELIB_AVAILABLE = True
except ImportError:
    SEASENSELIB_AVAILABLE = False

# Note: AQD binary files are supported via CSV export from AquaPro software
# Use nortek-csv file type for exported CSV data

# Import seabirdscientific if available
try:
    import seabirdscientific.instrument_data as id

    SEABIRD_AVAILABLE = True
except ImportError:
    SEABIRD_AVAILABLE = False
    warnings.warn(
        "seabirdscientific not available. Some features will be limited.",
        stacklevel=2,
    )

# Import tools for shared utilities
from caldip._writers import save_instrument_nc
from caldip.tools import to_xarray

# Import SBE hex readers
from .sbe_hex_reader import sbe37_hex_reader

# Conductivity source names that are in S/m and require ×10 to reach mS/cm
_CONDUCTIVITY_S_PER_M = frozenset({"c0S/m", "c1S/m", "cond0S/m", "cond1S/m"})

# Conductivity *unit strings*, normalised (stripped, lowercased, whitespace
# collapsed) for a units-driven S/m→mS/cm conversion. Anything non-empty that is
# in neither set is an unrecognised unit and must warn, not be assumed mS/cm.
_CONDUCTIVITY_SPM_UNITS = frozenset(
    {"s/m", "s m-1", "s m^-1", "siemens/m", "siemens/meter", "s·m-1"}
)
_CONDUCTIVITY_MSCM_UNITS = frozenset(
    {"ms/cm", "ms cm-1", "ms cm^-1", "ms·cm-1", "millisiemens/cm"}
)

# Map caldip YAML file_type keys to seasenselib format keys where they differ.
# 'sbe-asc' is a deprecated caldip alias for the seasenselib 'sbe-ascii' key;
# kept here so existing YAML configs don't break. Use 'sbe-ascii' in new configs.
_SL_FORMAT_MAP: dict[str, str] = {"sbe-asc": "sbe-ascii"}

# Caldip-specific source names not in seasenselib's parameters.py default_mappings.
# These supplement (never override) the seasenselib mapping.
_CALDIP_SUPPLEMENT = {
    "conductivity": ["cond0S/m", "cond1S/m"],  # seasenselib only has c0S/m, c1S/m
}


def _normalize_conductivity(ds: xr.Dataset) -> xr.Dataset:
    """Convert conductivity to mS/cm, units-driven, warning on an unknown unit.

    The ``conductivity`` variable's ``units`` attribute is normalised (stripped,
    lowercased, whitespace collapsed) and matched against the known S/m and
    mS/cm unit strings. S/m is multiplied by ten; mS/cm is left as is; any other
    **non-empty** unit warns loudly and is left unconverted (rather than silently
    assumed to be mS/cm — a 10× error). An empty unit is left unconverted without
    a warning, since it carries no claim to check.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with a ``conductivity`` variable (e.g. from ``sl.read()`` or a
        ctdcast stage file), or without one.

    Returns
    -------
    xr.Dataset
        Dataset with conductivity in mS/cm where the unit was S/m, otherwise
        unchanged.
    """
    if "conductivity" not in ds.data_vars:
        return ds
    raw = ds["conductivity"].attrs.get("units", "")
    unit = " ".join(str(raw).strip().lower().split())
    if unit in _CONDUCTIVITY_SPM_UNITS:
        ds["conductivity"] = ds["conductivity"] * 10.0
        ds["conductivity"].attrs["units"] = "mS/cm"
    elif unit and unit not in _CONDUCTIVITY_MSCM_UNITS:
        warnings.warn(
            f"conductivity has unrecognised units {raw!r}; leaving it unconverted "
            f"and assuming mS/cm. Confirm the file's conductivity unit.",
            UserWarning,
            stacklevel=2,
        )
    return ds


def _read_ctd_sensor(config: dict) -> int:
    """Return the CTD sensor number from config, accepting the deprecated plural key.

    The canonical key is ``ctd_sensor`` (integer, 1 or 2). Older YAML files use
    ``ctd_sensors`` (plural); that key is read with a DeprecationWarning and
    will be removed in a future release. Defaults to 1 (primary sensor) if
    neither key is present.

    Parameters
    ----------
    config : dict
        Parsed YAML config dict.

    Returns
    -------
    int
        CTD sensor number (1 = primary, 2 = secondary).
    """
    if "ctd_sensor" in config:
        return int(config["ctd_sensor"])
    if "ctd_sensors" in config:
        warnings.warn(
            "YAML key 'ctd_sensors' is deprecated; rename to 'ctd_sensor'.",
            DeprecationWarning,
            stacklevel=2,
        )
        return int(config["ctd_sensors"])
    return 1


def _normalize_instrument_vars(ds: xr.Dataset) -> xr.Dataset:
    """Rename raw instrument variable names to canonical names using parameters.py mappings.

    Uses caldip/parameters.py (copied from seasenselib) so the mapping stays in sync
    by copying that file. _CALDIP_SUPPLEMENT fills gaps not yet covered by seasenselib.
    Conductivity sources in S/m are multiplied by 10 → mS/cm.
    Any remaining '/' in variable names is replaced with '_per_'.
    """
    from caldip.parameters import default_mappings

    # Merge seasenselib mapping with caldip supplement (supplement appended, not prepended)
    combined = {
        canonical: list(sources) + _CALDIP_SUPPLEMENT.get(canonical, [])
        for canonical, sources in default_mappings.items()
    }
    # Add any supplement keys that aren't in default_mappings at all
    for canonical, sources in _CALDIP_SUPPLEMENT.items():
        if canonical not in combined:
            combined[canonical] = sources

    renames = {}
    for canonical, sources in combined.items():
        if canonical in ds.data_vars:
            continue  # already canonical
        for src in sources:
            if src in ds.data_vars and src not in renames:
                if src in _CONDUCTIVITY_S_PER_M:
                    ds = ds.assign({src: ds[src] * 10.0})
                renames[src] = canonical
                break

    if renames:
        ds = ds.rename(renames)

    # Sanitize any remaining '/' (e.g. residual raw names that didn't map)
    slash_renames = {v: v.replace("/", "_per_") for v in ds.data_vars if "/" in v}
    if slash_renames:
        ds = ds.rename(slash_renames)

    return ds


def find_config_file(path: str | Path) -> Path | None:
    """
    Find caldip configuration file in directory or use provided file.

    Parameters
    ----------
    path : str or Path
        Directory path or direct path to .yaml config file

    Returns
    -------
    Path or None
        Path to config file, or None if not found
    """
    path = Path(path)

    # If it's a YAML file, use it directly
    if path.is_file() and path.suffix in [".yaml", ".yml"]:
        return path

    # If it's a directory, look for .caldip.yaml files
    if path.is_dir():
        config_files = list(path.glob("*.caldip.yaml"))
        if config_files:
            return config_files[0]  # Use first config file found

        # Also check for .yaml files
        config_files = list(path.glob("*.yaml"))
        if config_files:
            return config_files[0]

    return None


def normalize_serial(value: str | int) -> str:
    """Normalise an instrument serial to its join-key form.

    A trailing marker asterisk is stripped, and leading zeros are stripped from
    an all-digit serial, so ``013874`` and ``9920*`` become ``"13874"`` and
    ``"9920"`` while an all-zero serial collapses to ``"0"``. A non-numeric
    serial keeps its leading zeros (they are not padding). The serial is the
    join key shared with oceanarray, which normalises the same way.

    Parameters
    ----------
    value : str or int
        The raw ``serial`` field from a cruise YAML or a filename.

    Returns
    -------
    str
        The normalised serial.

    Raises
    ------
    ValueError
        If the serial is ``None`` or blank; a serial cannot be defaulted.
    """
    if value is None or not str(value).strip():
        raise ValueError("serial is empty; a serial is required as the join key.")
    text = str(value).strip().rstrip("*")
    if text.isdigit():
        text = text.lstrip("0") or "0"
    return text


def resolve_instrument_class(
    instrument: str | None, file_type: str | None = None
) -> str:
    """Resolve a cruise-YAML ``instrument`` value to an oceanarray class name.

    A value that matches :data:`caldip.config.parameters.INSTRUMENT_CLASSES`
    case-insensitively is returned in its canonical (lowercase) form; a
    documented legacy alias is mapped to its class with a deprecation warning
    (aliases are removed at v1.0.0); a real class caldip compares nothing for
    (empty ``INSTRUMENT_CLASS_VARIABLES``, e.g. ``seapoint``) is refused with a
    distinct message; anything else raises.

    Parameters
    ----------
    instrument : str or None
        The ``instrument:`` field from the cruise YAML.
    file_type : str or None, optional
        The instrument's ``file_type``; disambiguates ``rbr``
        (``rbr-matlab-legacy`` -> ``tr1050``, ``rbr-rsk`` -> ``rbrsolo``).

    Returns
    -------
    str
        A class name from :data:`caldip.config.parameters.INSTRUMENT_CLASSES`.

    Raises
    ------
    ValueError
        If the value is a real class caldip does not compare, or is neither a
        known class nor a documented alias.
    """
    value = str(instrument or "").strip()
    lower = value.lower()
    if lower in params.INSTRUMENT_CLASSES:
        if not params.INSTRUMENT_CLASS_VARIABLES.get(lower, ()):
            raise ValueError(
                f"instrument: {value!r} is a real instrument class caldip does "
                f"not compare against the CTD; it cannot appear on a calibration "
                f"cast."
            )
        return lower

    ft = str(file_type).lower() if file_type else None
    alias = params.LEGACY_INSTRUMENT_ALIASES.get(
        (lower, ft)
    ) or params.LEGACY_INSTRUMENT_ALIASES.get((lower, None))
    if alias is not None:
        warnings.warn(
            f"instrument: {value!r} is a legacy alias for the oceanarray class "
            f"{alias!r}; update the cruise YAML. Aliases are removed at v1.0.0.",
            UserWarning,
            stacklevel=3,
        )
        return alias

    raise ValueError(
        f"instrument: {value!r} is not a known instrument class. Valid classes: "
        f"{', '.join(params.INSTRUMENT_CLASSES)}."
    )


#: Fixed name of the cruise-level YAML, distinct from the per-cast ``*.caldip.yaml``.
CRUISE_CONFIG_NAME = "caldip.cruise.yaml"

#: Cruise-level facts a per-cast config inherits from the cruise YAML.
_CRUISE_INHERITED = ("cruise", "ship", "year")


def find_cruise_config(start: str | Path) -> Path | None:
    """Return the nearest ``caldip.cruise.yaml`` at or above ``start``, or ``None``.

    Parameters
    ----------
    start : str or pathlib.Path
        A directory (or file) to search from, climbing toward the filesystem root.

    Returns
    -------
    pathlib.Path or None
        The nearest cruise YAML, or ``None`` if none is found.
    """
    start = Path(start)
    for parent in (start, *start.parents):
        candidate = parent / CRUISE_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_cruise_config(path: str | Path) -> dict:
    """Parse a cruise-level YAML (``cruise``/``ship``/``year`` + ``cal_dip`` dir).

    Parameters
    ----------
    path : str or pathlib.Path
        Path to a ``caldip.cruise.yaml`` file.

    Returns
    -------
    dict
        The parsed cruise configuration (empty dict if the file is empty).
    """
    with open(path) as f:
        return yaml.safe_load(f) or {}


def discover_cast_configs(cal_dip_dir: str | Path) -> list:
    """Return the per-cast ``*.caldip.yaml`` configs discovered under a directory.

    The cruise sweep discovers casts from the directory rather than a hand-kept
    list, so it cannot drift from what is on disk. The cruise YAML itself
    (``caldip.cruise.yaml``) does not match ``*.caldip.yaml`` and is not returned.

    Parameters
    ----------
    cal_dip_dir : str or pathlib.Path
        The ``cal_dip`` directory holding one subdirectory per cast.

    Returns
    -------
    list of pathlib.Path
        The per-cast config paths, sorted.
    """
    cal_dip_dir = Path(cal_dip_dir)
    configs = []
    for sub in sorted(p for p in cal_dip_dir.iterdir() if p.is_dir()):
        configs.extend(sorted(sub.glob("*.caldip.yaml")))
    return configs


def _merge_cruise_defaults(config: dict, config_path: Path) -> None:
    """Fill/override ``cruise``/``ship``/``year`` from the nearest cruise YAML.

    The cruise YAML is the source of truth for these shared facts (they had drifted
    across per-cast configs); a disagreeing per-cast value warns and the cruise
    value wins. No-op when no cruise YAML is present, so existing configs are
    unchanged.
    """
    cruise_file = find_cruise_config(config_path.parent)
    if cruise_file is None:
        return
    cruise = load_cruise_config(cruise_file)
    for key in _CRUISE_INHERITED:
        if key not in cruise:
            continue
        existing = config.get(key)
        if (
            existing not in (None, "")
            and str(existing).strip().lower() != str(cruise[key]).strip().lower()
        ):
            warnings.warn(
                f"{key}={existing!r} in {config_path.name} disagrees with "
                f"{cruise_file.name} ({cruise[key]!r}); using the cruise value.",
                UserWarning,
                stacklevel=3,
            )
        config[key] = cruise[key]


def load_config(yaml_file: str | Path) -> dict:
    """Load caldip configuration from YAML file.

    Each instrument's ``instrument:`` field is normalised in place to an
    oceanarray class name (see :func:`resolve_instrument_class`) and its serial
    to the shared join key, so every downstream consumer and the
    ``instrument_type`` written to the netCDF use the single controlled
    vocabulary. Blank ``instrument:``/``serial:`` fields (an unfinished scaffold
    stub) are left untouched to be filled in later; a serial that two
    instruments share after normalisation is rejected. ``cruise``/``ship``/``year``
    are inherited from the nearest ``caldip.cruise.yaml`` when one is present.
    """
    with open(yaml_file) as f:
        config = yaml.safe_load(f) or {}
    _merge_cruise_defaults(config, Path(yaml_file))
    seen_serials: dict[str, str] = {}
    for instrument in config.get("instruments", []) or []:
        if instrument.get("instrument"):
            instrument["instrument"] = resolve_instrument_class(
                instrument.get("instrument"), instrument.get("file_type")
            )
        if instrument.get("serial") not in (None, ""):
            serial = normalize_serial(instrument["serial"])
            if serial in seen_serials:
                raise ValueError(
                    f"two instruments share serial {serial!r} after normalisation "
                    f"({seen_serials[serial]} and "
                    f"{instrument.get('filename', '?')}); serials are the join key "
                    f"and must be unique."
                )
            seen_serials[serial] = str(instrument.get("filename", "?"))
            instrument["serial"] = serial
    if config.get("process_serials") is not None:
        config["process_serials"] = [
            normalize_serial(s) for s in config["process_serials"]
        ]
    return config


def resolve_data_dir(
    config_file: Path,
    config: dict,
    override: str | None = None,
) -> Path:
    """Return the data directory for a cast, with optional CLI override.

    Priority: explicit override > config 'directory' key > parent of config file.
    For config files sitting inside a cast directory (name starts with 'cast'),
    the config file's parent is used directly.
    """
    if override:
        return Path(override)
    if config_file.parent.name.startswith("cast"):
        return config_file.parent
    return Path(config.get("directory", config_file.parent))


def load_instrument_data(
    file_path: str | Path, file_type: str, **kwargs: object
) -> xr.Dataset:
    """
    Load instrument data using the appropriate loader based on file_type.

    Parameters
    ----------
    file_path : str or Path
        Path to the data file
    file_type : str
        Seasenselib format key (e.g. 'sbe-cnv', 'sbe-ascii', 'sbe-hex', 'rbr-rsk',
        'nortek-csv'). 'sbe-asc' is accepted as a deprecated alias for 'sbe-ascii'.
    **kwargs
        Additional arguments passed to the specific loader

    Returns
    -------
    xr.Dataset
        Dataset with standardized variable names and metadata

    Raises
    ------
    ValueError
        If file_type is not supported
    FileNotFoundError
        If file does not exist
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Data file not found: {file_path}")

    # Route to appropriate loader based on file_type
    if file_type == "ctd-cnv":
        return load_ctd_data(file_path, **kwargs)

    if not SEASENSELIB_AVAILABLE:
        raise ImportError(f"seasenselib is required for '{file_type}' data loading")
    sl_format = _SL_FORMAT_MAP.get(file_type, file_type)
    ds = sl.read(str(file_path), file_format=sl_format, **kwargs)
    return _normalize_conductivity(ds)


def load_instruments_from_config(
    config: dict, data_dir: str | Path | None = None
) -> dict[str, dict]:
    """
    Load all instruments specified in a caldip configuration.

    Parameters
    ----------
    config : dict
        Caldip configuration dictionary
    data_dir : str or Path, optional
        Base directory for data files. If None, uses config['directory']

    Returns
    -------
    dict
        Instrument serial numbers as keys; each value is a dict with ``data``
        (``xr.Dataset``), ``config`` (the instrument's YAML config dict),
        ``type`` (``str``, the file type) and ``file`` (``str``, the full path).
    """
    if data_dir is None:
        data_dir = config.get("directory", ".")

    data_dir = Path(data_dir)
    instruments = {}

    process_serials = config.get("process_serials")
    process_set = (
        {str(s) for s in process_serials} if process_serials is not None else None
    )

    for instrument in config.get("instruments", []):
        if process_set is not None and str(instrument["serial"]) not in process_set:
            continue
        serial = str(instrument["serial"])
        filename = instrument["filename"]
        file_type = instrument["file_type"]

        # Construct full file path
        file_path = data_dir / filename

        print(
            f"Loading {instrument.get('label', 'Unknown')} {serial} ({file_type.upper()})..."
        )

        try:
            load_kwargs = {}
            if "header_file" in instrument:
                header_file_path = data_dir / instrument["header_file"]
                load_kwargs["header_file"] = str(header_file_path)

            instr_type = instrument.get("instrument", file_type).lower()
            nc_use = data_dir / f"caldip_{instr_type}_{serial}_use.nc"
            nc_raw = data_dir / f"caldip_{instr_type}_{serial}_raw.nc"

            def _trim_and_save_use(ds: xr.Dataset, nc_use_path: Path = nc_use) -> None:
                deploy = config.get("deployment_time")
                recover = config.get("recovery_time")
                if not (deploy and recover):
                    return
                dep_np = pd.to_datetime(deploy).to_datetime64()
                rec_np = pd.to_datetime(recover).to_datetime64()
                mask = (ds.time.values >= dep_np) & (ds.time.values <= rec_np)
                if mask.any():
                    save_instrument_nc(ds.sel(time=mask), nc_use_path, "_use.nc")

            # Priority: _use.nc → _raw.nc (if newer than source) → source
            if nc_use.exists():
                dataset = xr.open_dataset(nc_use, engine="netcdf4")
                print(f"  📦 Loaded from _use.nc ({len(dataset.time)} samples)")
            elif (
                nc_raw.exists()
                and file_path.exists()
                and nc_raw.stat().st_mtime > file_path.stat().st_mtime
            ):
                dataset = xr.open_dataset(nc_raw, engine="netcdf4")
                print(f"  📦 Loaded from _raw.nc ({len(dataset.time)} samples)")
                # Create _use.nc from _raw.nc if not yet present
                _trim_and_save_use(dataset)
            else:
                # Load from source, normalize, apply clock offset, then save both
                dataset = load_instrument_data(file_path, file_type, **load_kwargs)
                dataset = _normalize_instrument_vars(dataset)

                clock_offset_val = instrument.get("clock_offset", 0)
                if clock_offset_val:
                    print(
                        f"  ⏰ Applying clock offset: {clock_offset_val:+.0f} seconds"
                    )
                    dataset = dataset.assign_coords(
                        time=dataset.time + pd.Timedelta(seconds=clock_offset_val)
                    )

                save_instrument_nc(dataset, nc_raw, "_raw.nc")
                _trim_and_save_use(dataset)

            # Warn if the serial number embedded in the dataset differs from the YAML
            dataset_serial = None
            if hasattr(dataset, "attrs") and "raw_metadata" in dataset.attrs:
                try:
                    raw_meta = json.loads(dataset.attrs["raw_metadata"])
                    if "blocks" in raw_meta and "other" in raw_meta["blocks"]:
                        global_attrs = raw_meta["blocks"]["other"].get(
                            "global_attributes", {}
                        )
                        dataset_serial = global_attrs.get("rbr_serial_number")
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

            instruments[serial] = {
                "data": dataset,
                "config": instrument,
                "type": file_type,
                "file": str(file_path),
            }

            if len(dataset.time) > 0:
                start_time = pd.to_datetime(dataset.time.values[0])
                end_time = pd.to_datetime(dataset.time.values[-1])
                duration_hours = (end_time - start_time).total_seconds() / 3600
                print(f"  ✅ Loaded: {len(dataset.time)} samples")
                print(f"     📅 Start: {start_time}")
                print(f"     📅 End:   {end_time}")
                print(f"     ⏱️  Duration: {duration_hours:.1f} hours")
                if dataset_serial and normalize_serial(dataset_serial) != serial:
                    print(
                        f"     ⚠️  YAML serial {serial} != Dataset serial {dataset_serial}"
                    )
            else:
                print(f"  ✅ Loaded: {len(dataset.time)} samples (no data)")

        except Exception as e:  # noqa: BLE001  # per-instrument load: skip failures, continue loop
            print(f"  ❌ Failed to load {serial}: {e}")

    return instruments


def load_reference_data(
    config: dict, data_dir: str | Path | None = None
) -> dict[str, dict]:
    """Load CTD reference data from config.

    If a pre-processed NetCDF cache (``{ctd_file}.nc``) exists, it is loaded
    directly. The cached file must have been built with the same ``ctd_sensor``
    value as the current config; if the stored ``ctd_sensor`` attribute
    disagrees with the requested value, a ``ValueError`` is raised so the
    user knows to delete the cache and re-run ``caldip ctd``.

    Parameters
    ----------
    config : dict
        Caldip configuration dictionary. The ``ctd_sensor`` key (integer,
        1 = primary, 2 = secondary) selects the CTD sensor pair; the
        deprecated ``ctd_sensors`` key is accepted with a warning.
    data_dir : str or Path, optional
        Base directory for data files. If None, uses ``config['directory']``.

    Returns
    -------
    dict
        Dictionary with CTD data keyed by CTD file stem:
        ``{ctd_name: {'data': xr.Dataset, 'file': str}}``.

    Raises
    ------
    ValueError
        If a cached NetCDF exists but was built with a different
        ``ctd_sensor`` than requested.
    """
    if data_dir is None:
        data_dir = config.get("directory", ".")

    data_dir = Path(data_dir)
    reference_data = {}

    # Load CTD data if specified
    ctd_file = config.get("ctd_file")
    if ctd_file:
        ctd_path = data_dir / ctd_file
        ctd_name = Path(ctd_file).stem

        print(f"Loading CTD reference {ctd_name}...")

        nc_path = ctd_path.with_suffix(".nc")
        requested_sensor = _read_ctd_sensor(config)

        try:
            if nc_path.exists():
                dataset = xr.open_dataset(nc_path, engine="netcdf4")
                if _is_ctdcast_nc(dataset):
                    source = dataset
                    dataset, provenance = read_ctdcast_reference(
                        source, requested_sensor, config
                    )
                    source.close()  # the resampled reference is independent of it
                    print(
                        f"  ✅ Loaded ctdcast reference from {nc_path.name} "
                        f"(stage {provenance['ctd_stage']}, {len(dataset.time)} samples)"
                    )
                    reference_data[ctd_name] = {
                        "data": dataset,
                        "file": str(ctd_path),
                        "provenance": provenance,
                    }
                else:
                    cached_sensor = int(dataset.attrs.get("ctd_sensor", 1))
                    if cached_sensor != requested_sensor:
                        raise ValueError(
                            f"Cached CTD '{nc_path.name}' was built with ctd_sensor={cached_sensor} "
                            f"but config (or --ctd-sensor) requests sensor {requested_sensor}. "
                            f"Delete {nc_path.name} and re-run 'caldip ctd' to rebuild."
                        )
                    print(
                        f"  ✅ Loaded pre-processed CTD from {nc_path.name} ({len(dataset.time)} samples)"
                    )
                    reference_data[ctd_name] = {"data": dataset, "file": str(ctd_path)}
            else:
                dataset = load_instrument_data(ctd_path, "ctd-cnv")
                dataset = _normalize_ctd_vars(dataset, ctd_sensor=requested_sensor)
                dataset = _wild_edit_ctd(dataset, config)
                dataset = _resample_1hz(dataset)
                print(f"  ✅ Loaded: {len(dataset.time)} samples")
                reference_data[ctd_name] = {"data": dataset, "file": str(ctd_path)}

        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001  # CTD file load: report failure, return what loaded
            print(f"  ❌ Failed to load CTD: {e}")

    return reference_data


_CTDCAST_UNK = "UNK"

# QARTOD "fail" flag value; a compared reference sample carrying it is masked.
_QARTOD_FAIL = 4


def _is_ctdcast_nc(ds: xr.Dataset) -> bool:
    """Return ``True`` if ``ds`` is a ctdcast per-cast stage netCDF.

    Distinguishes a ctdcast product (declares its own ``processing_stage`` and
    carries the ``ctd_temperature`` / ``conductivity`` naming) from caldip's own
    CTD cache (canonical ``temperature`` plus a ``ctd_sensor`` attribute).

    Parameters
    ----------
    ds : xarray.Dataset
        A dataset opened from the configured ``ctd_file`` path.

    Returns
    -------
    bool
        Whether to route ``ds`` to :func:`read_ctdcast_reference`.
    """
    if "processing_stage" not in ds.attrs:
        return False
    markers = ("ctd_temperature_1", "ctd_temperature", "conductivity_1", "conductivity")
    return any(name in ds.data_vars for name in markers)


def _ctdcast_sensor_meta(ds: xr.Dataset, var: str | None) -> tuple[str, str]:
    """Return ``(serial, calibration_date)`` for the sensor behind ``var``.

    The data variable links to its ``SENSOR_<TYPE>_<SERIAL>`` catalog entry via a
    ``sensor`` attribute; ``UNK`` is returned where the link or field is absent.

    Parameters
    ----------
    ds : xarray.Dataset
        The ctdcast stage dataset.
    var : str or None
        The measured variable whose sensor is wanted.

    Returns
    -------
    tuple of str
        The sensor serial number and calibration date, or ``UNK`` each.
    """
    if not var or var not in ds:
        return _CTDCAST_UNK, _CTDCAST_UNK
    sensor_name = ds[var].attrs.get("sensor")
    if not sensor_name or sensor_name not in ds:
        return _CTDCAST_UNK, _CTDCAST_UNK
    attrs = ds[sensor_name].attrs
    return (
        str(attrs.get("sensor_serial_number", _CTDCAST_UNK)),
        str(attrs.get("sensor_calibration_date", _CTDCAST_UNK)),
    )


def read_ctdcast_reference(
    ds: xr.Dataset, ctd_sensor: int, config: dict | None = None
) -> tuple[xr.Dataset, dict]:
    """Map a ctdcast stage netCDF to caldip's CTD reference, with provenance.

    The dual-sensor ctdcast variables (``ctd_temperature_1``/``_2``,
    ``conductivity_1``/``_2``, or the single-sensor forms) are mapped to caldip's
    canonical ``temperature`` / ``conductivity`` / ``pressure`` for the requested
    ``ctd_sensor``, honouring each compared variable's QARTOD ``_qc`` companion
    (a ``fail`` flag masks that sample). Provenance is copied from the file's
    global attributes and the ``SENSOR_*`` catalog; ``cruise`` is taken verbatim.

    Parameters
    ----------
    ds : xarray.Dataset
        A ctdcast per-cast stage dataset (see :func:`_is_ctdcast_nc`).
    ctd_sensor : int
        Which CTD sensor (1 or 2) to use as the reference.
    config : dict, optional
        The cast configuration; used only to warn when its ``cruise`` disagrees
        case-insensitively with the file's ``cruise``.

    Returns
    -------
    tuple
        ``(dataset, provenance)`` — the canonical-named CTD reference resampled
        to 1 Hz, and a dict of provenance attributes with ``UNK`` where unsourced.
    """

    def _pick(base: str) -> tuple[str | None, int | None]:
        exact = f"{base}_{ctd_sensor}"
        if exact in ds.data_vars:
            return exact, ctd_sensor
        if base in ds.data_vars:  # single-sensor file (stage 1 strips the _1)
            return base, 1
        return None, None

    temp_var, temp_sensor = _pick("ctd_temperature")
    cond_var, _ = _pick("conductivity")
    press_var = "pressure" if "pressure" in ds.data_vars else None

    # Record the sensor actually used, not the one requested; warn on a fallback
    # so the serials recorded below are not silently attributed to the wrong sensor.
    sensor_used = temp_sensor if temp_sensor is not None else ctd_sensor
    if temp_var is not None and temp_sensor != ctd_sensor:
        warnings.warn(
            f"ctd_sensor={ctd_sensor} requested but only a single-sensor "
            f"temperature is present; recording ctd_sensor_used={sensor_used}.",
            UserWarning,
            stacklevel=2,
        )

    # Build the canonical reference, honouring QARTOD on the compared variables
    # in the same pass: a `fail` masks that sample. Pressure is left intact so
    # bottle-stop detection is not broken by gaps.
    data_vars = {}
    qc_applied = False
    for canonical, src in (("temperature", temp_var), ("conductivity", cond_var)):
        if src is None:
            continue
        da = ds[src]
        qc_name = f"{src}_qc"
        if qc_name in ds:
            da = da.where(ds[qc_name] != _QARTOD_FAIL)
            qc_applied = True
        data_vars[canonical] = da
    if press_var is not None:
        data_vars["pressure"] = ds[press_var]
    out = xr.Dataset(data_vars)

    # Conductivity to mS/cm is units-driven and lives in one place; a ctdcast file
    # may write either unit under the same variable name, so the name-driven cnv
    # scaling is not applicable here.
    out = _normalize_conductivity(out)
    out = _resample_1hz(out)

    temp_serial, temp_caldate = _ctdcast_sensor_meta(ds, temp_var)
    cond_serial, cond_caldate = _ctdcast_sensor_meta(ds, cond_var)
    slope = ds[cond_var].attrs.get("calibration_slope") if cond_var else None
    file_cruise = str(ds.attrs.get("cruise", _CTDCAST_UNK))

    yaml_cruise = str((config or {}).get("cruise") or "")
    if (
        yaml_cruise
        and file_cruise not in ("", _CTDCAST_UNK)
        and yaml_cruise.lower() != file_cruise.lower()
    ):
        warnings.warn(
            f"cruise disagreement: cruise-YAML {yaml_cruise!r} vs ctdcast file "
            f"{file_cruise!r}; the file's value is recorded verbatim.",
            UserWarning,
            stacklevel=2,
        )

    def _plevel(var: str | None) -> str:
        if var and var in ds:
            return str(ds[var].attrs.get("processing_level", _CTDCAST_UNK))
        return _CTDCAST_UNK

    provenance = {
        "source_tracking_id": str(ds.attrs.get("tracking_id", _CTDCAST_UNK)),
        "ctd_stage": str(ds.attrs.get("processing_stage", _CTDCAST_UNK)),
        "data_mode": "D" if str(ds.attrs.get("data_mode", "")).upper() == "D" else "P",
        "ctd_sensor_used": str(sensor_used),
        "qc_flags_honoured": "true" if qc_applied else "false",
        "qc_masked_flag_values": str(_QARTOD_FAIL) if qc_applied else _CTDCAST_UNK,
        "ctd_temp_sensor_serial": temp_serial,
        "ctd_temp_sensor_caldate": temp_caldate,
        "ctd_cond_sensor_serial": cond_serial,
        "ctd_cond_sensor_caldate": cond_caldate,
        "ctd_conductivity_slope": (str(slope) if slope is not None else _CTDCAST_UNK),
        "ctd_cond_slope_adjusted": "true" if slope is not None else "false",
        "ctd_temp_processing_level": _plevel(temp_var),
        "ctd_cond_processing_level": _plevel(cond_var),
        "ctd_press_processing_level": _plevel(press_var),
        "preferred_pair": str(ds.attrs.get("preferred_pair", "undeclared")),
        "cruise": file_cruise,
    }
    return out, provenance


def _resample_1hz(ds: "xr.Dataset") -> "xr.Dataset":
    """Downsample CTD data to 1 Hz using a per-second median."""
    resampled = ds.resample(time="1s").median(keep_attrs=True)
    n_in, n_out = len(ds.time), len(resampled.time)
    if n_in != n_out:
        print(f"  📉 Resampled {n_in} → {n_out} samples (1 Hz median)")
    return resampled


# Canonical CTD variable mapping: (canonical_name, [(source_name, scale_factor), ...])
# Selected-sensor variables map to 'temperature'/'conductivity'.
# The other sensor maps to 'temperature_2'/'conductivity_2'.
# scale_factor converts to canonical units (S/m → mS/cm = ×10).
_CTD_CANONICAL_S1 = [
    ("temperature", [("t090C", 1.0), ("t190C", 1.0)]),
    ("temperature_2", [("t190C", 1.0)]),
    (
        "conductivity",
        [("c0mS/cm", 1.0), ("c0S/m", 10.0), ("c1mS/cm", 1.0), ("c1S/m", 10.0)],
    ),
    ("conductivity_2", [("c1mS/cm", 1.0), ("c1S/m", 10.0)]),
    ("pressure", [("prDM", 1.0), ("prdM", 1.0), ("press", 1.0), ("PRES", 1.0)]),
    ("salinity", [("sal00", 1.0), ("sal11", 1.0), ("PSAL", 1.0)]),
    ("oxygen", [("sbeox0ML/L", 1.0), ("sbeox1ML/L", 1.0)]),
]
_CTD_CANONICAL_S2 = [
    ("temperature", [("t190C", 1.0), ("t090C", 1.0)]),
    ("temperature_2", [("t090C", 1.0)]),
    (
        "conductivity",
        [("c1mS/cm", 1.0), ("c1S/m", 10.0), ("c0mS/cm", 1.0), ("c0S/m", 10.0)],
    ),
    ("conductivity_2", [("c0mS/cm", 1.0), ("c0S/m", 10.0)]),
    ("pressure", [("prDM", 1.0), ("prdM", 1.0), ("press", 1.0), ("PRES", 1.0)]),
    ("salinity", [("sal00", 1.0), ("sal11", 1.0), ("PSAL", 1.0)]),
    ("oxygen", [("sbeox0ML/L", 1.0), ("sbeox1ML/L", 1.0)]),
]
# Keep _CTD_CANONICAL as an alias used by tests
_CTD_CANONICAL = _CTD_CANONICAL_S1


def _normalize_ctd_vars(ds: "xr.Dataset", ctd_sensor: int = 1) -> "xr.Dataset":
    """
    Rename CTD variables to canonical names and convert units where needed.

    ctd_sensor=1 (default) uses primary sensor (t090C, c0*) as 'temperature'/'conductivity';
    secondary sensor becomes 'temperature_2'/'conductivity_2'.
    ctd_sensor=2 reverses this.
    Conductivity in S/m is multiplied by 10 to convert to mS/cm.
    Any remaining variable names containing '/' are sanitized to '_per_'.
    """
    canonical = _CTD_CANONICAL_S2 if ctd_sensor == 2 else _CTD_CANONICAL_S1
    renames = {}
    conversions = {}
    for canon_name, sources in canonical:
        if canon_name in ds.data_vars:
            continue  # already canonical
        for src, scale in sources:
            if src in ds.data_vars and src not in renames:
                renames[src] = canon_name
                if scale != 1.0:
                    conversions[src] = scale
                break

    # Sanitize any remaining variable names containing '/' (not valid in NetCDF)
    for var in ds.data_vars:
        if var not in renames and "/" in var:
            renames[var] = var.replace("/", "_per_")

    if not renames:
        return ds

    # Apply unit conversions before renaming
    updates = {}
    for src, scale in conversions.items():
        arr = ds[src].values.astype(float) * scale
        updates[src] = xr.DataArray(
            arr, coords=ds[src].coords, dims=ds[src].dims, attrs=ds[src].attrs
        )
    if updates:
        ds = ds.assign(updates)

    ds = ds.rename(renames)

    canonical_renames = {
        s: d for s, d in renames.items() if not d.endswith("_per_") and "_per_" not in d
    }
    parts = [
        f"{src}→{dst}" + (f" (×{conversions[src]})" if src in conversions else "")
        for src, dst in canonical_renames.items()
    ]
    if parts:
        print(f"  🔤 Normalized: {', '.join(parts)}")
    return ds


def _wild_edit_ctd(ds: "xr.Dataset", config: dict) -> "xr.Dataset":
    """
    Apply global range checks to CTD reference data (wild-edit / gross-error removal).

    Checks applied (any failure NaNs all variables at that sample):
      - pressure < 0 or > max_pressure (max_pressure from config, if set)
      - temperature < -3 or > 40
      - salinity > 42
    """
    bad = np.zeros(len(ds.time), dtype=bool)
    reasons = []

    # Pressure check (canonical name after _normalize_ctd_vars)
    if "pressure" in ds.data_vars:
        pressure = ds["pressure"].values.astype(float)
        p_bad = pressure < 0
        max_p = config.get("max_pressure")
        if max_p is not None:
            p_bad |= pressure > float(max_p)
        n = int(p_bad.sum())
        if n:
            bad |= p_bad
            reasons.append(
                f"{n} pressure < 0"
                if max_p is None
                else f"{n} pressure out of range [0, {max_p}]"
            )

    # Temperature check
    if "temperature" in ds.data_vars:
        temp = ds["temperature"].values.astype(float)
        t_bad = (temp < -3) | (temp > 40)
        n = int(t_bad.sum())
        if n:
            bad |= t_bad
            reasons.append(f"{n} temperature out of range [-3, 40]")

    # Salinity check
    if "salinity" in ds.data_vars:
        sal = ds["salinity"].values.astype(float)
        s_bad = sal > 42
        n = int(s_bad.sum())
        if n:
            bad |= s_bad
            reasons.append(f"{n} salinity > 42")

    n_bad = int(bad.sum())
    if n_bad == 0:
        return ds

    masked = {}
    for var in ds.data_vars:
        arr = ds[var].values.copy().astype(float)
        arr[bad] = float("nan")
        masked[var] = xr.DataArray(
            arr, coords=ds[var].coords, dims=ds[var].dims, attrs=ds[var].attrs
        )

    result = ds.assign(masked)
    result.attrs.update(ds.attrs)
    print(f"  ⚠️  Wild-edit: {n_bad} samples masked — " + "; ".join(reasons))
    return result


def load_ctd_data(file_path: str | Path) -> xr.Dataset:
    """
    Load CTD 911 data from SeaBird hex/cnv file.

    Parameters
    ----------
    file_path : str or Path
        Path to CTD data file (.hex or .cnv format)

    Returns
    -------
    xarray.Dataset
        CTD data with standardized variable names and metadata
    """
    file_path = Path(file_path)

    if file_path.suffix.lower() == ".hex":
        raise ValueError(
            f"CTD hex files are not supported directly: {file_path.name}\n"
            "Convert the file to a 1-Hz CNV file using SBEDataProcessing first, "
            "then update the 'ctd_file' field in your YAML to point to the .cnv output."
        )

    if file_path.suffix.lower() == ".cnv":
        # For .cnv files, use seabirdscientific if available
        if not SEABIRD_AVAILABLE:
            raise ImportError("seabirdscientific package required for CNV data loading")

        # Use cnv_to_instrument_data to load CNV files; fall back to latin-1 if UTF-8 fails
        try:
            instrument_data = id.cnv_to_instrument_data(str(file_path))
        except UnicodeDecodeError:
            content = file_path.read_bytes().decode("latin-1")
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".cnv", delete=False
            ) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            try:
                instrument_data = id.cnv_to_instrument_data(str(tmp_path))
            finally:
                tmp_path.unlink(missing_ok=True)
        ds = to_xarray(instrument_data)

        # Fix time if it's showing year 2000 incorrectly
        # CTD files have timeJ which is elapsed days since start of cast
        if pd.Timestamp(ds.time.values[0]).year == 2000:
            # Check the raw file for the actual start time
            actual_start = None
            with open(file_path, encoding="latin-1") as f:
                for line in f:
                    if "* NMEA UTC" in line:
                        # Extract date from line like: * NMEA UTC (Time) = Mar 30 2026 21:06:33
                        try:
                            date_str = line.split("=")[-1].strip()
                            from datetime import datetime, timedelta

                            actual_start = datetime.strptime(
                                date_str, "%b %d %Y %H:%M:%S"
                            )
                            break
                        except ValueError:
                            continue

            if actual_start and "timeJ" in ds.data_vars:
                # timeJ is elapsed time in days since start of cast
                # The first timeJ value corresponds to actual_start
                elapsed_days = ds.timeJ.values - ds.timeJ.values[0]

                actual_timestamps = []
                for ed in elapsed_days:
                    timestamp = actual_start + timedelta(days=float(ed))
                    actual_timestamps.append(timestamp)

                ds = ds.assign_coords(time=pd.DatetimeIndex(actual_timestamps))
                ds.attrs["start_time"] = actual_start.isoformat()
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")

    # Add standardized variable names and units
    ds.attrs["instrument_type"] = "CTD"
    ds.attrs["filename"] = str(file_path)

    return ds


def load_microcat_data(file_path: str | Path) -> xr.Dataset:
    """Load microCAT (SBE37) data from SeaBird hex/asc/cnv file.

    Deprecated: load_instrument_data() now routes sbe-cnv/sbe-hex/sbe-asc through
    seasenselib directly. This function is retained for direct use and testing only.

    Parameters
    ----------
    file_path : str or Path
        Path to microCAT data file (.hex, .asc, or .cnv format)

    Returns
    -------
    xarray.Dataset
        MicroCAT data with standardized variable names and metadata
    """
    file_path = Path(file_path)

    if file_path.suffix.lower() == ".cnv":
        # For .cnv files, use cnv_to_instrument_data (confirmed working)
        if not SEABIRD_AVAILABLE:
            raise ImportError(
                "seabirdscientific package required for .cnv file loading"
            )

        instrument_data = id.cnv_to_instrument_data(str(file_path))
        ds = to_xarray(instrument_data)

        # Fix time coordinate if timeJV2 (actual timestamps) is available
        if "timeJV2" in ds.data_vars:
            # timeJV2 is Julian days: day 1 = Jan 1, so day 0 = Dec 31 of previous year.
            # Parse the year from the CNV header rather than hardcoding it.
            from datetime import datetime, timedelta

            import pandas as pd

            year = None
            with open(file_path) as _f:
                for _line in _f:
                    if "* System UpLoad Time =" in _line:
                        try:
                            _date_str = _line.split("=")[-1].strip()
                            year = datetime.strptime(
                                _date_str, "%b %d %Y %H:%M:%S"
                            ).year
                        except ValueError:
                            pass
                        break

            if year is None:
                import warnings

                warnings.warn(
                    f"Could not parse year from CNV header in {file_path.name}; "
                    "falling back to current year for timeJV2 conversion.",
                    UserWarning,
                    stacklevel=2,
                )
                year = datetime.now().year

            julian_days = ds.timeJV2.values
            reference_date = datetime(year - 1, 12, 31, 0, 0, 0)

            actual_timestamps = [
                reference_date + timedelta(days=float(jd)) for jd in julian_days
            ]
            ds = ds.assign_coords(time=pd.DatetimeIndex(actual_timestamps))
            ds.attrs["time_corrected"] = "Using actual timestamps from timeJV2"

        elif "timeK" in ds.data_vars:
            # timeK is the SBE instrument's internal clock in seconds since 2000-01-01.
            # More reliable than start_time + timeS when there are recording gaps.
            # Corrupted timeK values (zeros, wrap-arounds, random) break the uniform
            # increment; we keep only the longest block where consecutive timeK values
            # step by the expected sample interval.
            from collections import Counter

            import pandas as pd

            tq = ds["timeK"].values.astype("float64")
            n = len(tq)
            valid_mask = np.ones(n, dtype=bool)
            if n > 1:
                diffs = np.diff(tq)
                # Infer sample interval from the most common positive diff (1 s – 1 hr)
                pos = diffs[(diffs >= 1) & (diffs <= 3600)].astype(int)
                interval = Counter(pos).most_common(1)[0][0] if len(pos) else 10
                # A consecutive pair is good if its diff matches the interval
                good_pair = np.abs(diffs - interval) < 0.5
                # A sample is valid if it is part of at least one good pair
                sample_ok = np.zeros(n, dtype=bool)
                sample_ok[:-1] |= good_pair
                sample_ok[1:] |= good_pair
                # Keep only the largest contiguous valid block
                changes = np.diff(sample_ok.astype(np.int8), prepend=0, append=0)
                starts = np.where(changes == 1)[0]
                ends = np.where(changes == -1)[0]
                if len(starts):
                    best = int(np.argmax(ends - starts))
                    valid_mask = np.zeros(n, dtype=bool)
                    valid_mask[starts[best] : ends[best]] = True

            n_dropped = n - int(valid_mask.sum())
            if n_dropped:
                ds = ds.isel(time=valid_mask)
                tq = tq[valid_mask]
                print(f"  ⚠️  Dropped {n_dropped} rows with non-sequential timeK values")
            timestamps = pd.to_datetime(
                tq * 1e9, unit="ns", origin="2000-01-01", errors="coerce"
            )
            ds = ds.assign_coords(time=timestamps)
            ds.attrs["time_corrected"] = (
                "Using instrument clock from timeK (seconds since 2000-01-01)"
            )
            print(f"  🕐 Time from timeK: {timestamps[0]} → {timestamps[-1]}")

    elif file_path.suffix.lower() == ".hex":
        # Parse MicroCAT hex files using calibration data from hex header
        ds = sbe37_hex_reader(file_path)

    elif file_path.suffix.lower() == ".asc":
        # Parse ASCII files manually
        ds = _parse_microcat_ascii(file_path)

    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")

    # Extract serial number from filename if not in metadata
    if "serial_number" not in ds.attrs:
        serial_parts = file_path.stem.split("_")
        ds.attrs["serial_number"] = serial_parts[0] if serial_parts else "unknown"

    ds.attrs["instrument_type"] = "SBE37"
    ds.attrs["filename"] = str(file_path)

    return ds


def _parse_microcat_ascii(file_path: Path) -> xr.Dataset:
    """
    Parse ASCII microCAT files (legacy format).

    This handles the basic ASCII format structure from SeaBird instruments.
    Automatically detects column format based on data structure.
    """
    with open(file_path) as f:
        lines = f.readlines()

    # Find data start (after header lines starting with * or #)
    data_start = 0
    metadata = {}

    for i, line in enumerate(lines):
        line = line.strip()

        # Extract metadata from header
        if line.startswith("*"):
            if "Temperature SN" in line:
                metadata["temperature_sn"] = line.split("=")[-1].strip()
            elif "Conductivity SN" in line:
                metadata["conductivity_sn"] = line.split("=")[-1].strip()
            elif "sample interval" in line:
                try:
                    interval_match = line.split("=")[-1].strip().split()[0]
                    metadata["interval_s"] = int(interval_match)
                except (ValueError, IndexError):
                    pass
            elif "System UpLoad Time" in line:
                try:
                    time_str = line.split("=")[-1].strip()
                    metadata["upload_time"] = datetime.strptime(
                        time_str, "%b %d %Y %H:%M:%S"
                    )
                except ValueError:
                    pass
        elif not line.startswith("*") and not line.startswith("#") and line:
            # Skip lines like "start time = ", "sample interval = ", "start sample number = "
            if (
                "start time" in line
                or "sample interval" in line
                or "start sample number" in line
            ):
                continue
            # First actual data line marks data start
            data_start = i
            break

    # Parse data lines (skip comments and empty lines)
    data_lines = []
    time_stamps = []
    has_pressure = False

    for line in lines[data_start:]:
        line = line.strip()
        if line and not line.startswith("*") and not line.startswith("#"):
            # Skip metadata lines that might appear in data section
            if (
                "start time" in line
                or "sample interval" in line
                or "start sample number" in line
            ):
                continue

            try:
                parts = [p.strip() for p in line.split(",")]

                # Detect format based on number of comma-separated values
                if len(parts) == 5:
                    # Format: temperature, conductivity, pressure, date, time
                    temp = float(parts[0])
                    cond = float(parts[1]) * 10.0  # Convert from S/m to mS/cm
                    press = float(parts[2])
                    date_str = f"{parts[3]} {parts[4]}"
                    has_pressure = True

                elif len(parts) == 4:
                    # Format: temperature, conductivity, date, time (no pressure)
                    temp = float(parts[0])
                    cond = float(parts[1]) * 10.0  # Convert from S/m to mS/cm
                    press = 0.0
                    date_str = f"{parts[2]} {parts[3]}"

                else:
                    continue

                # Try multiple date formats
                date_formats = [
                    "%d %b %Y %H:%M:%S",  # "30 Mar 2026 03:00:01"
                    "%m-%d-%Y %H:%M:%S",  # "03-30-2026 03:00:01"
                    "%d-%m-%Y %H:%M:%S",  # "30-03-2026 03:00:01"
                    "%Y-%m-%d %H:%M:%S",  # "2026-03-30 03:00:01"
                ]

                timestamp = None
                for fmt in date_formats:
                    try:
                        timestamp = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue

                if timestamp:
                    time_stamps.append(timestamp)
                    data_lines.append([temp, cond, press])

            except (ValueError, IndexError):
                continue

    if not data_lines:
        raise ValueError(f"No valid data found in ASCII file {file_path}")

    # Convert to numpy array
    data_array = np.array(data_lines)
    n_samples = len(data_array)

    # Create time coordinate - use parsed timestamps if available
    if time_stamps and any(t is not None for t in time_stamps):
        # Use the actual timestamps from the data
        valid_timestamps = [t for t in time_stamps if t is not None]
        if len(valid_timestamps) == len(time_stamps):
            time_index = pd.to_datetime(time_stamps)
        else:
            # Some timestamps missing, interpolate
            time_index = pd.to_datetime(time_stamps)
            time_index = time_index.fillna(method="ffill").fillna(method="bfill")
    else:
        # Fallback: create regular time series
        interval_s = metadata.get("interval_s", 10)  # Default 10 seconds
        start_time = metadata.get("upload_time", datetime.now())
        time_index = pd.date_range(
            start=start_time, periods=n_samples, freq=f"{interval_s}s"
        )

    # Create Dataset with appropriate variables
    data_vars = {
        "temperature": (["time"], data_array[:, 0]),
        "conductivity": (["time"], data_array[:, 1]),
    }

    # Only add pressure if it exists (not all zeros)
    if has_pressure and np.any(data_array[:, 2] != 0):
        data_vars["prdM"] = (["time"], data_array[:, 2])

    return xr.Dataset(data_vars, coords={"time": time_index}, attrs=metadata)


def _parse_nortek_csv_columns(df: pd.DataFrame) -> dict:
    """
    Extract data variables from Nortek CSV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with Nortek CSV data

    Returns
    -------
    Dict
        Dictionary of data variables for xarray Dataset
    """
    data_vars = {}

    # Environmental data
    for csv_col, var_name in [
        ("temperature", "temperature"),
        ("pressure", "pressure"),
        ("heading", "heading"),
        ("pitch", "pitch"),
        ("roll", "roll"),
        ("speedOfSound", "speed_of_sound"),
        ("batteryVoltage", "battery_voltage"),
    ]:
        if csv_col in df.columns:
            data_vars[var_name] = (["time"], df[csv_col].values)

    # Velocity, amplitude, correlation data for 3 beams
    for i in [1, 2, 3]:
        for data_type, prefix in [
            ("vel", "velocity"),
            ("amp", "amplitude"),
            ("corr", "correlation"),
        ]:
            csv_col = f"{data_type}Beam{i}#1"
            var_name = f"{prefix}_beam{i}"
            if csv_col in df.columns:
                data_vars[var_name] = (["time"], df[csv_col].values)

    return data_vars


def _add_nortek_variable_attributes(ds: xr.Dataset) -> xr.Dataset:
    """
    Add units and metadata attributes to Nortek dataset variables.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset to add attributes to

    Returns
    -------
    xr.Dataset
        Dataset with variable attributes added
    """
    # Environmental variable attributes
    attr_map = {
        "temperature": {"units": "degrees_C", "long_name": "Water Temperature"},
        "pressure": {"units": "dbar", "long_name": "Pressure"},
        "heading": {"units": "degrees", "long_name": "Heading"},
        "pitch": {"units": "degrees", "long_name": "Pitch"},
        "roll": {"units": "degrees", "long_name": "Roll"},
        "speed_of_sound": {"units": "m/s", "long_name": "Speed of Sound"},
        "battery_voltage": {"units": "V", "long_name": "Battery Voltage"},
    }

    for var_name, attrs in attr_map.items():
        if var_name in ds.data_vars:
            ds[var_name].attrs.update(attrs)

    # Beam data attributes
    for i in [1, 2, 3]:
        vel_var = f"velocity_beam{i}"
        amp_var = f"amplitude_beam{i}"
        corr_var = f"correlation_beam{i}"

        if vel_var in ds.data_vars:
            ds[vel_var].attrs.update(
                {
                    "units": "m/s",
                    "long_name": f"Velocity Beam {i}",
                    "coordinate_system": "BEAM",
                }
            )
        if amp_var in ds.data_vars:
            ds[amp_var].attrs.update(
                {"units": "counts", "long_name": f"Amplitude Beam {i}"}
            )
        if corr_var in ds.data_vars:
            ds[corr_var].attrs.update(
                {"units": "%", "long_name": f"Correlation Beam {i}"}
            )

    return ds


def load_nortek_csv_data(
    file_path: str | Path,
    header_file: str | None = None,  # noqa: ARG001  # unused here; the live path forwards it to seasenselib
) -> xr.Dataset:
    """Load Nortek CSV data exported from AquaPro software.

    Deprecated: load_instrument_data() now routes nortek-csv through seasenselib
    directly. This function is retained for direct use and testing only.

    Parameters
    ----------
    file_path : str or Path
        Path to the CSV data file (e.g., "Average Velocity DF3.csv")
    header_file : str, optional
        Path to Units.csv file for metadata (optional)

    Returns
    -------
    xr.Dataset
        Dataset with Nortek CSV data
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    # Read CSV and parse time
    df = pd.read_csv(file_path, delimiter=";")
    df["datetime"] = pd.to_datetime(df["dateTime"])
    times = df["datetime"].values

    # Extract data variables
    data_vars = _parse_nortek_csv_columns(df)

    # Create dataset
    ds = xr.Dataset(data_vars, coords={"time": times})

    # Add global metadata
    ds.attrs.update(
        {
            "instrument_type": "Nortek_Aquadopp",
            "filename": str(file_path),
            "data_format": "Nortek_CSV_Export",
            "coordinate_system": "BEAM",
        }
    )

    # Extract serial number
    if "serialNumber" in df.columns:
        ds.attrs["serial_number"] = str(df["serialNumber"].iloc[0])

    # Add variable attributes
    ds = _add_nortek_variable_attributes(ds)

    print(f"  ✅ Nortek CSV: loaded {len(times)} samples from {file_path.name}")

    return ds


def sbe37_xmlcon_reader(xmlcon_file: str | Path) -> dict:
    """Parse an SBE37 xmlcon file for sensor configuration and calibration coefficients.

    Deprecated: retained for direct use and testing only.

    Parameters
    ----------
    xmlcon_file : Union[str, Path]
        Path to .xmlcon file

    Returns
    -------
    Dict
        Dictionary containing sensor configurations and coefficient objects
    """
    import xml.etree.ElementTree as ET

    xmlcon_path = Path(xmlcon_file)
    if not xmlcon_path.exists():
        raise FileNotFoundError(f"XMLCON file not found: {xmlcon_path}")

    # Parse XML
    tree = ET.parse(xmlcon_path)
    root = tree.getroot()

    sensors = {}
    enabled_sensors = []

    # Find all sensors by index
    for sensor_elem in root.findall(".//Sensor"):
        index = sensor_elem.get("index")
        if index is None:
            continue

        index = int(index)

        # Check what type of sensor this is
        temp_sensor = sensor_elem.find("TemperatureSensor")
        cond_sensor = sensor_elem.find("ConductivitySensor")
        press_sensor = sensor_elem.find("PressureSensor")

        if temp_sensor is not None:
            sensors[index] = _parse_coefficients(temp_sensor, "temperature", index)
            enabled_sensors.append("temperature")

        elif cond_sensor is not None:
            sensors[index] = _parse_coefficients(cond_sensor, "conductivity", index)
            enabled_sensors.append("conductivity")

        elif press_sensor is not None:
            sensors[index] = _parse_coefficients(press_sensor, "pressure", index)
            enabled_sensors.append("pressure")

    return {
        "sensors": sensors,
        "enabled_sensors": enabled_sensors,
        "xmlcon_path": xmlcon_path,
    }


def _parse_coefficients(
    sensor_elem: "ET.Element", sensor_type: str, sensor_index: int
) -> dict:
    """
    Parse sensor coefficients from an XML element.

    Parameters
    ----------
    sensor_elem : xml.etree.ElementTree.Element
        XML element containing sensor data
    sensor_type : str
        Type of sensor ('temperature', 'conductivity', 'pressure')
    sensor_index : int
        Sensor index from xmlcon

    Returns
    -------
    Dict
        Sensor information with coefficients
    """
    # Extract common fields
    serial_num = sensor_elem.find("SerialNumber").text
    cal_date = sensor_elem.find("CalibrationDate").text

    # Parse all coefficient elements to lowercase keys
    coef_dict = {}

    if sensor_type == "conductivity":
        # Special handling for conductivity - check UseG_J flag
        use_g_j_elem = sensor_elem.find("UseG_J")
        use_g_j = use_g_j_elem is not None and use_g_j_elem.text == "1"

        if use_g_j:
            # Look for equation="1" coefficients which contain G,H,I,J
            for coeffs_elem in sensor_elem.findall("Coefficients"):
                equation_attr = coeffs_elem.get("equation")
                if equation_attr == "1":
                    for child in coeffs_elem:
                        if child.text:
                            coef_dict[child.tag.lower()] = float(child.text)
                    break
        else:
            # Use equation="0" with A,B,C,D coefficients
            for coeffs_elem in sensor_elem.findall("Coefficients"):
                equation_attr = coeffs_elem.get("equation")
                if equation_attr == "0":
                    for child in coeffs_elem:
                        if child.text:
                            coef_dict[child.tag.lower()] = float(child.text)
                    break

        # Also parse direct children (slope, offset, etc.)
        for child in sensor_elem:
            if child.tag.lower() in ["slope", "offset"] and child.text:
                coef_dict[child.tag.lower()] = float(child.text)

    else:
        # For temperature and pressure, parse all numeric child elements
        for child in sensor_elem:
            if child.text and child.tag not in ["SerialNumber", "CalibrationDate"]:
                try:
                    coef_dict[child.tag.lower()] = float(child.text)
                except ValueError:
                    # Skip non-numeric elements
                    continue

    # Separate seabirdscientific calibration coefficients from slope/offset
    cal_coeffs = {}
    metadata = {}

    # Define expected coefficient names for each sensor type
    if sensor_type == "temperature":
        expected_coeffs = ["a0", "a1", "a2", "a3"]
    elif sensor_type == "conductivity":
        expected_coeffs = ["g", "h", "i", "j", "cpcor", "ctcor", "wbotc"]
    elif sensor_type == "pressure":
        expected_coeffs = [
            "pa0",
            "pa1",
            "pa2",
            "ptca0",
            "ptca1",
            "ptca2",
            "ptcb0",
            "ptcb1",
            "ptcb2",
            "ptempa0",
            "ptempa1",
            "ptempa2",
        ]
    else:
        expected_coeffs = []

    # Split coefficients
    for key, value in coef_dict.items():
        if key in expected_coeffs:
            cal_coeffs[key] = value
        else:
            metadata[key] = value

    return {
        "type": sensor_type,
        "serial_number": serial_num,
        "calibration_date": cal_date,
        "coefficients": cal_coeffs,
        "metadata": metadata,
        "index": sensor_index,
    }


# Removed duplicate sbe37_hex_reader function - using import from .sbe_hex_reader instead
