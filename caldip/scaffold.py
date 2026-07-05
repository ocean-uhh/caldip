"""
Scaffold utilities for initialising new caldip cast directories.

Public API:
- generate_stub_yaml() — scan a cast directory and write a starter .caldip.yaml
"""

import re
from pathlib import Path
from typing import Dict, List, Optional


def generate_stub_yaml(directory: str, print_only: bool = False) -> Dict:
    """
    Generate a stub YAML configuration for a caldip directory.

    Parameters
    ----------
    directory : str
        Path to caldip directory (e.g., 'data/proc_calib/cruise123/cal_dip/castM3')
    print_only : bool
        If True, print to stdout instead of writing file

    Returns
    -------
    Dict
        Configuration dictionary
    """

    dir_path = Path(directory)

    if not dir_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    # Extract information from directory structure
    cast_name = dir_path.name  # e.g., 'castM3'

    # Try to extract cruise name from path structure
    path_parts = dir_path.parts
    cruise_name = ""
    for part in reversed(path_parts):
        if "cal_dip" in part.lower():
            continue
        if any(x in part.lower() for x in ["cruise", "msm", "expedition"]):
            cruise_name = part
            break

    # Extract year from cast name or directory
    year_match = re.search(r"20\d{2}", str(dir_path))
    year = int(year_match.group()) if year_match else 2024

    # Find CTD file and extract metadata
    ctd_file = _find_ctd_file(dir_path)
    if not ctd_file:
        raise FileNotFoundError(f"No *_1sec.cnv file found in {directory}")

    ctd_metadata = _extract_ctd_metadata(ctd_file)

    # Detect instruments
    instruments = _detect_instruments(dir_path)

    # Build the configuration
    config = {
        "name": cast_name,
        "year": year,
        "waterdepth": ".nan",
        "cruise": cruise_name,
        "directory": f"{directory}/",
        "ctd_file": ctd_file.name,
        "ctd_sensors": 2,  # Default assumption
        "instruments": instruments,
    }

    # Add optional fields if available
    if ctd_metadata["start_time"]:
        config["deployment_time"] = ctd_metadata["start_time"]
    if ctd_metadata["end_time"]:
        config["recovery_time"] = ctd_metadata["end_time"]
    if ctd_metadata["latitude"]:
        config["deployment_latitude"] = ctd_metadata["latitude"]
        # Extract the number with proper sign
        lat_parts = ctd_metadata["latitude"].split()
        lat_value = float(lat_parts[0])
        if len(lat_parts) > 1 and lat_parts[1] == "S":
            lat_value = -lat_value
        config["latitude"] = lat_value
    if ctd_metadata["longitude"]:
        config["deployment_longitude"] = ctd_metadata["longitude"]
        # Extract the number with proper sign
        lon_parts = ctd_metadata["longitude"].split()
        lon_value = float(lon_parts[0])
        if len(lon_parts) > 1 and lon_parts[1] == "W":
            lon_value = -lon_value
        config["longitude"] = lon_value
    if ctd_metadata["ship"]:
        config["ship"] = ctd_metadata["ship"]

    # Handle output
    if print_only:
        import yaml

        print(yaml.dump(config, default_flow_style=False, sort_keys=False, indent=2))
        return config

    # Determine output filename
    output_file = dir_path / f"{cast_name}.caldip.yaml"

    # Check if file exists and find next available name
    if output_file.exists():
        counter = 1
        while True:
            new_name = dir_path / f"{cast_name}.caldip-{counter}.yaml"
            if not new_name.exists():
                output_file = new_name
                break
            counter += 1

    # Write YAML file
    import yaml

    with open(output_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, indent=2)

    print(f"Generated stub YAML: {output_file}")
    print(f"Found {len(config['instruments'])} instruments")

    return config


def _find_ctd_file(directory: Path) -> Optional[Path]:
    """Find the main CTD file (*_1sec.cnv) in the directory."""
    files = list(directory.glob("*_1sec.cnv"))
    if files:
        return files[0]
    return None


def _extract_ctd_metadata(ctd_file: Path) -> Dict:
    """Extract metadata from CTD .cnv file header."""
    metadata = {
        "start_time": None,
        "end_time": None,
        "latitude": None,
        "longitude": None,
        "ship": None,
        "nvalues": None,
        "interval": None,
    }

    try:
        with open(ctd_file, "r", encoding="latin1") as f:
            # Read header lines (typically first 100 lines contain metadata)
            for i, line in enumerate(f):
                if i > 200:  # Stop reading after header
                    break

                line = line.strip()

                # Extract start time
                if "start_time" in line.lower() or "start time" in line.lower():
                    # Look for format like "Apr 04 2026 15:19:06"
                    time_match = re.search(
                        r"(\w{3})\s+(\d{1,2})\s+(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})",
                        line,
                    )
                    if time_match:
                        month_abbr = time_match.group(1)
                        day = int(time_match.group(2))
                        year = int(time_match.group(3))
                        hour = int(time_match.group(4))
                        minute = int(time_match.group(5))
                        second = int(time_match.group(6))

                        # Convert month abbreviation to number
                        months = {
                            "Jan": 1,
                            "Feb": 2,
                            "Mar": 3,
                            "Apr": 4,
                            "May": 5,
                            "Jun": 6,
                            "Jul": 7,
                            "Aug": 8,
                            "Sep": 9,
                            "Oct": 10,
                            "Nov": 11,
                            "Dec": 12,
                        }
                        month = months.get(month_abbr, 1)

                        # Format as ISO datetime
                        metadata["start_time"] = (
                            f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
                        )
                    else:
                        # Fallback to existing ISO format
                        match = re.search(
                            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line
                        )
                        if match:
                            metadata["start_time"] = match.group(1)

                # Extract ship name
                if line.startswith("# ship:") or line.startswith("# Ship:"):
                    ship = line.split(":", 1)[1].strip()
                    if ship and ship != "unknown":
                        metadata["ship"] = ship

                # Extract NMEA latitude: "* NMEA Latitude = 58 01.63 N"
                if "nmea latitude" in line.lower():
                    lat_match = re.search(r"(\d+)\s+(\d+\.?\d*)\s+([NS])", line)
                    if lat_match:
                        deg = float(lat_match.group(1))
                        mins = float(lat_match.group(2))
                        hemisphere = lat_match.group(3)
                        decimal_deg = deg + mins / 60.0
                        metadata["latitude"] = f"{decimal_deg:.4f} {hemisphere}"

                # Extract NMEA longitude: "* NMEA Longitude = 048 49.71 W"
                if "nmea longitude" in line.lower():
                    lon_match = re.search(r"(\d+)\s+(\d+\.?\d*)\s+([EW])", line)
                    if lon_match:
                        deg = float(lon_match.group(1))
                        mins = float(lon_match.group(2))
                        hemisphere = lon_match.group(3)
                        decimal_deg = deg + mins / 60.0
                        metadata["longitude"] = f"{decimal_deg:.4f} {hemisphere}"

                # Fallback: Extract latitude from generic latitude lines
                if "latitude" in line.lower() and not metadata["latitude"]:
                    # Look for patterns like "59 27.84" (degrees minutes) or "59.4640" (decimal degrees)
                    lat_match = re.search(r"(-?\d+)\s+(\d+\.?\d*)", line)
                    if lat_match:
                        # Degrees minutes format
                        deg = float(lat_match.group(1))
                        mins = float(lat_match.group(2))
                        decimal_deg = abs(deg) + mins / 60.0
                        metadata["latitude"] = (
                            f"{decimal_deg:.4f} {'N' if deg >= 0 else 'S'}"
                        )
                    else:
                        # Try decimal degrees format
                        lat_match = re.search(r"(-?\d+\.?\d*)", line)
                        if lat_match:
                            deg = float(lat_match.group(1))
                            metadata["latitude"] = (
                                f"{abs(deg):.4f} {'N' if deg >= 0 else 'S'}"
                            )

                # Fallback: Extract longitude from generic longitude lines
                if "longitude" in line.lower() and not metadata["longitude"]:
                    # Look for patterns like "-048 27.21" (degrees minutes) or "-48.4535" (decimal degrees)
                    lon_match = re.search(r"(-?\d+)\s+(\d+\.?\d*)", line)
                    if lon_match:
                        # Degrees minutes format
                        deg = float(lon_match.group(1))
                        mins = float(lon_match.group(2))
                        decimal_deg = abs(deg) + mins / 60.0
                        metadata["longitude"] = (
                            f"{decimal_deg:.4f} {'E' if deg >= 0 else 'W'}"
                        )
                    else:
                        # Try decimal degrees format
                        lon_match = re.search(r"(-?\d+\.?\d*)", line)
                        if lon_match:
                            deg = float(lon_match.group(1))
                            metadata["longitude"] = (
                                f"{abs(deg):.4f} {'E' if deg >= 0 else 'W'}"
                            )

                # Extract nvalues
                if "nvalues" in line.lower():
                    nval_match = re.search(r"nvalues\s*=\s*(\d+)", line)
                    if nval_match:
                        metadata["nvalues"] = int(nval_match.group(1))

                # Extract interval
                if "interval" in line.lower():
                    interval_match = re.search(
                        r"interval\s*=\s*seconds:\s*(\d+(?:\.\d+)?)", line
                    )
                    if interval_match:
                        metadata["interval"] = float(interval_match.group(1))

    except Exception as e:
        print(f"Warning: Could not extract metadata from {ctd_file}: {e}")

    # Calculate recovery time if we have all the data
    if metadata["start_time"] and metadata["nvalues"] and metadata["interval"]:
        try:
            from datetime import datetime, timedelta

            start_dt = datetime.fromisoformat(metadata["start_time"])
            duration_seconds = metadata["nvalues"] * metadata["interval"]
            end_dt = start_dt + timedelta(seconds=duration_seconds)
            metadata["end_time"] = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception as e:
            print(f"Warning: Could not calculate end time: {e}")

    return metadata


def _prioritize_files(files: List[Path]) -> List[Path]:
    """Select the best file based on extension priority."""
    # Group files by base name (without extension)
    by_basename: Dict[str, List[Path]] = {}
    for f in files:
        basename = f.stem
        # Handle cases like file.12345.cnv -> use just file.12345
        if "." in basename:
            basename = (
                ".".join(basename.split(".")[:-1])
                if basename.count(".") > 1
                else basename
            )

        if basename not in by_basename:
            by_basename[basename] = []
        by_basename[basename].append(f)

    # For each basename, pick the best file
    selected = []
    for basename, file_list in by_basename.items():
        # Priority: .cnv > .mat > .rsk > .hex
        cnv_files = [f for f in file_list if f.suffix.lower() == ".cnv"]
        mat_files = [f for f in file_list if f.suffix.lower() == ".mat"]
        rsk_files = [f for f in file_list if f.suffix.lower() == ".rsk"]
        hex_files = [f for f in file_list if f.suffix.lower() == ".hex"]

        if cnv_files:
            selected.append(cnv_files[0])
        elif mat_files:
            selected.append(mat_files[0])
        elif rsk_files:
            selected.append(rsk_files[0])
        elif hex_files:
            selected.append(hex_files[0])
        elif file_list:  # fallback
            selected.append(file_list[0])

    return selected


def _detect_instruments(directory: Path) -> List[Dict]:
    """Detect instruments based on files in directory."""
    instruments = []

    # Find all potential instrument files
    all_files = list(directory.glob("*"))

    # Filter out unwanted files
    instrument_files = []
    ignored_extensions = {".xml", ".xmlcon", ".cap", ".txt", ".log", ".yaml", ".yml"}

    for f in all_files:
        if f.is_file() and f.suffix.lower() not in ignored_extensions:
            # Skip the main CTD file
            if "_1sec.cnv" in f.name:
                continue
            instrument_files.append(f)

    # Prioritize files
    selected_files = _prioritize_files(instrument_files)

    # Create instrument entries
    for i, file in enumerate(selected_files, 1):
        # Try to extract serial number from filename
        serial = ""

        # Handle SBE37SMP-RS232 pattern: SBE37SMP-RS232_037#####_20*.*
        sbe_match = re.match(r"SBE37SMP-RS232_037(\d{5})_20", file.name)
        if sbe_match:
            serial = sbe_match.group(1)

        instrument = {
            "position": str(i),
            "serial": serial,
            "label": "",
            "filename": file.name,
            "depth": 0,
        }

        # Determine instrument type and file_type based on extension
        ext = file.suffix.lower()
        if ext == ".cnv":
            instrument["instrument"] = "sbe"
            instrument["file_type"] = "sbe-cnv"
        elif ext == ".mat":
            instrument["instrument"] = "rbr"  # Common for RBR files
            instrument["file_type"] = "rbr-matlab-legacy"
        elif ext == ".rsk":
            instrument["instrument"] = "rbr"
            instrument["file_type"] = "rbr-rsk"
        elif ext == ".hex":
            instrument["instrument"] = "sbe"  # SBE hex files
            instrument["file_type"] = "sbe-hex"
        else:
            # Unknown file type - leave instrument and file_type blank
            instrument["instrument"] = ""
            instrument["file_type"] = ""

        instruments.append(instrument)

    return instruments
