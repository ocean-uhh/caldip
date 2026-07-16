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

import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from typing import Dict, Union, Optional
import yaml
from datetime import datetime
import warnings
import json
import tempfile

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
    warnings.warn("seabirdscientific not available. Some features will be limited.")

# Import tools for shared utilities
from caldip.tools import to_xarray
from caldip._writers import save_instrument_nc

# Import SBE hex readers
from .sbe_hex_reader import sbe37_hex_reader

# Conductivity source names that are in S/m and require ×10 to reach mS/cm
_CONDUCTIVITY_S_PER_M = frozenset({"c0S/m", "c1S/m", "cond0S/m", "cond1S/m"})

# Caldip-specific source names not in seasenselib's parameters.py default_mappings.
# These supplement (never override) the seasenselib mapping.
_CALDIP_SUPPLEMENT = {
    "conductivity": ["cond0S/m", "cond1S/m"],  # seasenselib only has c0S/m, c1S/m
}


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


def find_config_file(path):
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


def load_config(yaml_file: Union[str, Path]) -> Dict:
    """Load caldip configuration from YAML file."""
    with open(yaml_file, "r") as f:
        config = yaml.safe_load(f)
    return config


def resolve_data_dir(
    config_file: Path,
    config: Dict,
    override: Optional[str] = None,
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
    file_path: Union[str, Path], file_type: str, **kwargs
) -> xr.Dataset:
    """
    Load instrument data using the appropriate loader based on file_type.

    Parameters
    ----------
    file_path : str or Path
        Path to the data file
    file_type : str
        Type of file format (e.g., 'sbe-cnv', 'sbe-asc', 'rbr-rsk')
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
    if file_type in ["sbe-cnv", "sbe-asc", "sbe-hex"]:
        return load_microcat_data(file_path, **kwargs)

    elif file_type == "rbr-rsk":
        if not SEASENSELIB_AVAILABLE:
            raise ImportError("seasenselib is required for RBR data loading")
        return sl.read(file_path, **kwargs)

    elif file_type == "ctd-cnv":
        return load_ctd_data(file_path, **kwargs)

    elif file_type == "nortek-csv":
        return load_nortek_csv_data(file_path, **kwargs)

    else:
        # For all other file types, pass to seasenselib with any additional kwargs
        return sl.read(file_path, file_format=file_type, **kwargs)
    #    raise ValueError(f"Unsupported file_type: {file_type}")


def load_instruments_from_config(
    config: Dict, data_dir: Optional[Union[str, Path]] = None
) -> Dict[str, Dict]:
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
        Dictionary with instrument serial numbers as keys and data info as values:
        {
            'serial_number': {
                'data': xr.Dataset,
                'config': dict,  # instrument config from YAML
                'type': str,     # file_type
                'file': str      # full file path
            }
        }
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

            def _trim_and_save_use(ds):
                deploy = config.get("deployment_time")
                recover = config.get("recovery_time")
                if not (deploy and recover):
                    return
                dep_np = pd.to_datetime(deploy).to_datetime64()
                rec_np = pd.to_datetime(recover).to_datetime64()
                mask = (ds.time.values >= dep_np) & (ds.time.values <= rec_np)
                if mask.any():
                    save_instrument_nc(ds.sel(time=mask), nc_use, "_use.nc")

            # Priority: _use.nc → _raw.nc (if newer than source) → source
            if nc_use.exists():
                dataset = xr.open_dataset(nc_use)
                print(f"  📦 Loaded from _use.nc ({len(dataset.time)} samples)")
            elif (
                nc_raw.exists()
                and file_path.exists()
                and nc_raw.stat().st_mtime > file_path.stat().st_mtime
            ):
                dataset = xr.open_dataset(nc_raw)
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
                if dataset_serial and dataset_serial != serial:
                    print(
                        f"     ⚠️  YAML serial {serial} != Dataset serial {dataset_serial}"
                    )
            else:
                print(f"  ✅ Loaded: {len(dataset.time)} samples (no data)")

        except Exception as e:
            print(f"  ❌ Failed to load {serial}: {e}")

    return instruments


def load_reference_data(
    config: Dict, data_dir: Optional[Union[str, Path]] = None
) -> Dict[str, Dict]:
    """
    Load CTD reference data from config.

    Parameters
    ----------
    config : dict
        Caldip configuration dictionary
    data_dir : str or Path, optional
        Base directory for data files. If None, uses config['directory']

    Returns
    -------
    dict
        Dictionary with CTD data:
        {
            'ctd_name': {
                'data': xr.Dataset,
                'file': str
            }
        }
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

        try:
            nc_path = ctd_path.with_suffix(".nc")
            if nc_path.exists():
                dataset = xr.open_dataset(nc_path)
                print(
                    f"  ✅ Loaded pre-processed CTD from {nc_path.name} ({len(dataset.time)} samples)"
                )
            else:
                # NOTE: reads 'ctd_sensor' (singular). Old YAMLs using 'ctd_sensors' will
                # silently default to 1 — fix by renaming the key in the YAML.
                ctd_sensor = int(config.get("ctd_sensor", 1))
                dataset = load_instrument_data(ctd_path, "ctd-cnv")
                dataset = _normalize_ctd_vars(dataset, ctd_sensor=ctd_sensor)
                dataset = _wild_edit_ctd(dataset, config)
                dataset = _resample_1hz(dataset)
                print(f"  ✅ Loaded: {len(dataset.time)} samples")

            reference_data[ctd_name] = {"data": dataset, "file": str(ctd_path)}

        except Exception as e:
            print(f"  ❌ Failed to load CTD: {e}")

    return reference_data


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
_CTD_CANONICAL = _CTD_CANONICAL_S1  # noqa: F841


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


def _wild_edit_ctd(ds: "xr.Dataset", config: Dict) -> "xr.Dataset":
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


def load_ctd_data(file_path: Union[str, Path]) -> xr.Dataset:
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

    elif file_path.suffix.lower() == ".cnv":
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
            with open(file_path, "r", encoding="latin-1") as f:
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
                        except Exception:
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


def load_microcat_data(file_path: Union[str, Path]) -> xr.Dataset:
    """
    Load microCAT (SBE37) data from SeaBird hex/asc/cnv file.

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
            import pandas as pd
            from datetime import datetime, timedelta

            year = None
            with open(file_path, "r") as _f:
                for _line in _f:
                    if "* System UpLoad Time =" in _line:
                        try:
                            _date_str = _line.split("=")[-1].strip()
                            year = datetime.strptime(
                                _date_str, "%b %d %Y %H:%M:%S"
                            ).year
                        except Exception:
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
            import pandas as pd
            from collections import Counter

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
    with open(file_path, "r") as f:
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

    ds = xr.Dataset(data_vars, coords={"time": time_index}, attrs=metadata)

    return ds


def _parse_nortek_csv_columns(df: pd.DataFrame) -> Dict:
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
    file_path: Union[str, Path], header_file: Optional[str] = None
) -> xr.Dataset:
    """
    Load Nortek CSV data exported from AquaPro software.

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


def sbe37_xmlcon_reader(xmlcon_file: Union[str, Path]) -> Dict:
    """
    DEPRECATED
    Parse SBE37 xmlcon file to extract sensor configuration and calibration coefficients.

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


def _parse_coefficients(sensor_elem, sensor_type: str, sensor_index: int) -> Dict:
    """
    Generic function to parse sensor coefficients from XML element.

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
            if child.tag.lower() in ["slope", "offset"]:
                if child.text:
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
