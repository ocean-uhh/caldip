#!/usr/bin/env python3
"""
SBE hex file readers for Sea-Bird instruments.

This module provides functions to read and parse SBE hex files, extracting
calibration coefficients directly from the hex file header instead of requiring
separate xmlcon files.
"""

import re
import warnings
from pathlib import Path
from typing import Dict, Union
import pandas as pd
import numpy as np
import xarray as xr

# Import seabirdscientific if available
try:
    import seabirdscientific.instrument_data as id
    import seabirdscientific.conversion as conv
    from seabirdscientific.cal_coefficients import (
        TemperatureCoefficients,
        ConductivityCoefficients,
        PressureCoefficients,
    )

    SEABIRD_AVAILABLE = True
except ImportError:
    SEABIRD_AVAILABLE = False
    warnings.warn("seabirdscientific not available. SBE hex reading will be limited.")


def _parse_hex_calibration(hex_file: Union[str, Path]) -> Dict:
    """
    Parse calibration data from SBE hex file header.

    Parameters
    ----------
    hex_file : Union[str, Path]
        Path to the hex file

    Returns
    -------
    Dict
        Dictionary containing hardware, configuration, and calibration data
    """
    hex_path = Path(hex_file)

    with open(hex_path, "r") as f:
        # Read until we hit *END* which marks end of header
        header_lines = []
        for line in f:
            if line.strip() == "*END*":
                break
            header_lines.append(line.rstrip())

    header_text = "\n".join(header_lines)

    # Extract different data sections
    hardware_data = _parse_hardware_data(header_text)
    config_data = _parse_config_data(header_text)
    calib_data = _parse_calib_coeff(header_text, hardware_data["internal_sensors"])

    return {
        "hardware": hardware_data,
        "configuration": config_data,
        "calibration": calib_data,
        "header_text": header_text,
    }


def _parse_hardware_data(header_text: str) -> Dict:
    """
    Parse hardware data from hex file header.

    Parameters
    ----------
    header_text : str
        Complete header text from hex file

    Returns
    -------
    Dict
        Hardware information including firmware version, manufacturer, and internal sensors
    """
    # Extract HardwareData section
    hardware_match = re.search(
        r"<HardwareData[^>]*>(.*?)</HardwareData>", header_text, re.DOTALL
    )

    if not hardware_match:
        raise ValueError("HardwareData section not found in hex file")

    hardware_section = hardware_match.group(1)

    # Parse basic hardware info
    firmware_version = re.search(
        r"<FirmwareVersion>(.*?)</FirmwareVersion>", hardware_section
    )
    manufacturer = re.search(r"<Manufacturer>(.*?)</Manufacturer>", hardware_section)

    # Parse internal sensors
    internal_sensors = {}
    sensors_match = re.search(
        r"<InternalSensors>(.*?)</InternalSensors>", hardware_section, re.DOTALL
    )

    if sensors_match:
        sensors_text = sensors_match.group(1)
        # Find all sensor entries
        sensor_matches = re.finditer(
            r"<Sensor id='([^']+)'>(.*?)</Sensor>", sensors_text, re.DOTALL
        )

        for sensor_match in sensor_matches:
            sensor_id = sensor_match.group(1)
            sensor_content = sensor_match.group(2)

            # Extract serial number
            serial_match = re.search(
                r"<SerialNumber>(.*?)</SerialNumber>", sensor_content
            )
            serial_number = serial_match.group(1) if serial_match else ""

            internal_sensors[sensor_id] = {
                "id": sensor_id,
                "serial_number": serial_number,
            }

    return {
        "firmware_version": firmware_version.group(1) if firmware_version else "",
        "manufacturer": manufacturer.group(1) if manufacturer else "",
        "internal_sensors": internal_sensors,
    }


def _parse_config_data(header_text: str) -> Dict:
    """
    Parse configuration data from hex file header.

    Parameters
    ----------
    header_text : str
        Complete header text from hex file

    Returns
    -------
    Dict
        Configuration information including pressure/pump installation and min conductivity frequency
    """
    # Extract ConfigurationData section
    config_match = re.search(
        r"<ConfigurationData[^>]*>(.*?)</ConfigurationData>", header_text, re.DOTALL
    )

    if not config_match:
        return {}

    config_section = config_match.group(1)

    # Parse configuration fields
    pressure_installed = re.search(
        r"<PressureInstalled>(.*?)</PressureInstalled>", config_section
    )
    pump_installed = re.search(r"<PumpInstalled>(.*?)</PumpInstalled>", config_section)
    min_cond_freq = re.search(r"<MinCondFreq>(.*?)</MinCondFreq>", config_section)

    config_data = {}

    if pressure_installed:
        config_data["pressure_installed"] = pressure_installed.group(1).lower() == "yes"

    if pump_installed:
        config_data["pump_installed"] = pump_installed.group(1).lower() == "yes"

    if min_cond_freq:
        try:
            config_data["min_cond_freq"] = float(min_cond_freq.group(1))
        except ValueError:
            pass

    return config_data


def _parse_calib_coeff(header_text: str, internal_sensors: Dict) -> Dict:
    """
    Parse calibration coefficients from hex file header.

    Parameters
    ----------
    header_text : str
        Complete header text from hex file
    internal_sensors : Dict
        Internal sensors information from hardware data

    Returns
    -------
    Dict
        Calibration coefficients for each sensor type
    """
    # Extract CalibrationCoefficients section
    calib_match = re.search(
        r"<CalibrationCoefficients[^>]*>(.*?)</CalibrationCoefficients>",
        header_text,
        re.DOTALL,
    )

    if not calib_match:
        return {}

    calib_section = calib_match.group(1)

    # Find all calibration entries
    calibrations = {}
    calib_matches = re.finditer(
        r"<Calibration[^>]*id='([^']+)'[^>]*>(.*?)</Calibration>",
        calib_section,
        re.DOTALL,
    )

    for calib_match in calib_matches:
        sensor_id = calib_match.group(1)
        calib_content = calib_match.group(2)

        # Extract calibration date
        cal_date_match = re.search(r"<CalDate>(.*?)</CalDate>", calib_content)
        cal_date = cal_date_match.group(1) if cal_date_match else ""

        # Extract serial number for this calibration
        serial_match = re.search(r"<SerialNum>(.*?)</SerialNum>", calib_content)
        serial_number = serial_match.group(1) if serial_match else ""

        # Extract coefficients - find all coefficient tags
        coefficients = {}
        coeff_pattern = r"<([A-Z][A-Z0-9]*)>([^<]+)</\1>"
        coeff_matches = re.finditer(coeff_pattern, calib_content)

        for coeff_match in coeff_matches:
            coeff_name = coeff_match.group(1)
            coeff_value = coeff_match.group(2)

            # Skip non-coefficient fields
            if coeff_name in ["SerialNum", "CalDate"]:
                continue

            try:
                # Map coefficient names to expected format
                coeff_lower = coeff_name.lower()

                # Map SBE hex file coefficient names to seabirdscientific expected names
                if coeff_lower == "pcor":
                    coeff_lower = "cpcor"
                elif coeff_lower == "tcor":
                    coeff_lower = "ctcor"
                elif coeff_lower == "wbotc":
                    coeff_lower = "wbotc"  # This one is already correct

                coefficients[coeff_lower] = float(coeff_value)
            except ValueError:
                continue

        # Map sensor type
        sensor_type = sensor_id.lower()

        calibrations[sensor_type] = {
            "type": sensor_type,
            "serial_number": serial_number,
            "calibration_date": cal_date,
            "coefficients": coefficients,
        }

    return calibrations


def sbe37_hex_reader(hex_file: Union[str, Path]) -> xr.Dataset:
    """
    Read SBE37 hex file using calibration data from the hex file header.

    Parameters
    ----------
    hex_file : Union[str, Path]
        Path to .hex file

    Returns
    -------
    xr.Dataset
        Dataset containing temperature, conductivity, and/or pressure data
    """
    hex_path = Path(hex_file)
    if not hex_path.exists():
        raise FileNotFoundError(f"Hex file not found: {hex_path}")

    if not SEABIRD_AVAILABLE:
        raise ImportError(
            "seabirdscientific package required for SBE37 hex file reading"
        )

    # Parse calibration data from hex file header
    calib_info = _parse_hex_calibration(hex_path)

    # Determine which sensors are available
    available_sensors = []
    sensor_mapping = {
        "temperature": id.Sensors.Temperature,
        "conductivity": id.Sensors.Conductivity,
        "pressure": id.Sensors.Pressure,
    }

    # Check what sensors have calibration data
    for sensor_type in calib_info["calibration"].keys():
        if sensor_type in sensor_mapping:
            available_sensors.append(sensor_mapping[sensor_type])

    if not available_sensors:
        raise ValueError("No supported sensors found in hex file")

    # Read the hex file using seabirdscientific
    raw_data = id.read_hex_file(
        filepath=str(hex_path),
        instrument_type=id.InstrumentType.SBE37SM,
        enabled_sensors=available_sensors,
    )

    # Convert to xarray Dataset with calibrated data
    data_vars = {}

    # Extract time coordinate from raw data
    times = pd.to_datetime(raw_data["date time"])
    n_samples = len(times)

    # Process each sensor type and apply calibrations
    for sensor_type, calib_data in calib_info["calibration"].items():
        coeffs = calib_data["coefficients"]

        if sensor_type == "temperature" and "temperature" in raw_data.columns:
            # Create temperature coefficients object
            temp_coefs = TemperatureCoefficients(**coeffs)

            # Convert raw counts to calibrated temperature
            temperature = conv.convert_temperature(
                temperature_counts_in=raw_data["temperature"].values,
                coefs=temp_coefs,
                standard="ITS90",
                units="C",
                use_mv_r=False,
            )
            data_vars["temp"] = ("time", temperature)

        elif sensor_type == "conductivity" and "conductivity" in raw_data.columns:
            # Create conductivity coefficients object
            cond_coefs = ConductivityCoefficients(**coeffs)

            # Convert raw counts to calibrated conductivity
            temp_values = data_vars.get("temp", (None, np.zeros(n_samples)))[1]
            pressure_values = np.zeros(
                n_samples
            )  # Will be updated if pressure is available

            conductivity = conv.convert_conductivity(
                conductivity_count=raw_data["conductivity"].values,
                temperature=temp_values,
                pressure=pressure_values,
                coefs=cond_coefs,
            )
            # Convert from S/m to mS/cm (multiply by 10)
            conductivity_mScm = conductivity * 10.0
            data_vars["cond"] = ("time", conductivity_mScm)

        elif sensor_type == "pressure" and "pressure" in raw_data.columns:
            # Filter pressure coefficients to only include expected ones
            expected_press_coeffs = [
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
            filtered_coeffs = {
                k: v for k, v in coeffs.items() if k in expected_press_coeffs
            }

            # Create pressure coefficients object
            press_coefs = PressureCoefficients(**filtered_coeffs)

            # Convert raw counts to calibrated pressure
            # For SBE37, use temperature compensation if available
            temp_comp_values = raw_data.get(
                "temperature compensation", np.zeros(n_samples)
            )
            if hasattr(temp_comp_values, "values"):
                temp_comp_values = temp_comp_values.values

            pressure = conv.convert_pressure(
                pressure_count=raw_data["pressure"].values,
                compensation_voltage=temp_comp_values,
                coefs=press_coefs,
                units="dbar",
            )
            data_vars["press"] = ("time", pressure)

    # Create dataset
    ds = xr.Dataset(data_vars, coords={"time": times})

    # Add units and metadata as variable attributes
    for sensor_type, calib_data in calib_info["calibration"].items():
        var_name = None
        if sensor_type == "temperature" and "temp" in data_vars:
            var_name = "temp"
            ds[var_name].attrs["units"] = "degrees_C"
            ds[var_name].attrs["long_name"] = "Temperature"
        elif sensor_type == "conductivity" and "cond" in data_vars:
            var_name = "cond"
            ds[var_name].attrs["units"] = "mS/cm"
            ds[var_name].attrs["long_name"] = "Conductivity"
        elif sensor_type == "pressure" and "press" in data_vars:
            var_name = "press"
            ds[var_name].attrs["units"] = "dbar"
            ds[var_name].attrs["long_name"] = "Pressure"

        # Add calibration metadata as attributes
        if var_name:
            # Format calibration date as ISO format
            cal_date_str = calib_data["calibration_date"]
            try:
                # Parse date in format "13-Apr-23" and convert to ISO format
                from datetime import datetime

                parsed_date = datetime.strptime(cal_date_str, "%d-%b-%y")
                formatted_date = parsed_date.strftime("%Y-%m-%dT")
                ds[var_name].attrs["calibration_date"] = formatted_date
            except ValueError:
                # If parsing fails, use original string
                ds[var_name].attrs["calibration_date"] = cal_date_str

            # Format calibration coefficients as string
            coeff_pairs = []
            for coeff_name, coeff_value in calib_data["coefficients"].items():
                coeff_pairs.append(f"{coeff_name}={coeff_value:.6e}")
            ds[var_name].attrs["calib_coeffs"] = ", ".join(coeff_pairs)

            ds[var_name].attrs["sensor_serial_number"] = calib_data["serial_number"]

    # Add dataset metadata
    ds.attrs["source_file"] = str(hex_path)
    ds.attrs["instrument_type"] = "SBE37"
    ds.attrs["data_type"] = "calibrated"
    ds.attrs["firmware_version"] = calib_info["hardware"]["firmware_version"]
    ds.attrs["manufacturer"] = calib_info["hardware"]["manufacturer"]

    # Add configuration metadata
    for key, value in calib_info["configuration"].items():
        ds.attrs[key] = value

    return ds
