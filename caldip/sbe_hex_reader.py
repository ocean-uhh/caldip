from typing import Union, Dict
from pathlib import Path
import pandas as pd
import numpy as np
import xarray as xr


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


def parse_hex_header_sensors(hex_file: Union[str, Path]) -> Dict:
    """
    Parse SBE37 hex file header to extract enabled sensors and calibration coefficients.

    Parameters
    ----------
    hex_file : Union[str, Path]
        Path to .hex file

    Returns
    -------
    Dict
        Dictionary with enabled_sensors list and calibration_coefficients
    """
    import xml.etree.ElementTree as ET

    hex_path = Path(hex_file)
    enabled_sensors = []
    calibration_coeffs = {}

    # Read the header and extract XML content
    header_lines = []
    with open(hex_path, "r") as f:
        for line in f:
            if line.startswith("*"):
                header_lines.append(line[1:].strip())  # Remove * prefix
            else:
                # End of header, start of data
                break

    # Join header lines and try to parse as XML
    header_xml = "\n".join(header_lines)

    # Extract enabled sensors
    for line in header_lines:
        if "<Sensor id=" in line:
            if "id='Temperature'" in line:
                enabled_sensors.append("temperature")
            elif "id='Conductivity'" in line:
                enabled_sensors.append("conductivity")
            elif "id='Pressure'" in line:
                enabled_sensors.append("pressure")
            elif "id='Oxygen'" in line:
                enabled_sensors.append("oxygen")

    # Extract calibration coefficients
    try:
        # Find CalibrationCoefficients section
        cal_start = header_xml.find("<CalibrationCoefficients")
        cal_end = header_xml.find("</CalibrationCoefficients>") + len(
            "</CalibrationCoefficients>"
        )

        if cal_start != -1 and cal_end != -1:
            cal_xml = header_xml[cal_start:cal_end]

            # Parse calibration XML
            root = ET.fromstring(cal_xml)

            for calibration in root.findall("Calibration"):
                sensor_id = calibration.get("id", "").lower()
                cal_format = calibration.get("format", "")

                if sensor_id in ["temperature", "conductivity", "pressure", "oxygen"]:
                    sensor_coeffs = {}

                    for child in calibration:
                        if child.tag in ["A0", "A1", "A2", "A3"]:  # Temperature coeffs
                            sensor_coeffs[child.tag.lower()] = float(child.text)
                        elif child.tag in [
                            "G",
                            "H",
                            "I",
                            "J",
                            "PCOR",
                            "TCOR",
                            "WBOTC",
                        ]:  # Conductivity coeffs
                            # Map to seabirdscientific expected names
                            key_map = {
                                "PCOR": "cpcor",
                                "TCOR": "ctcor",
                                "WBOTC": "wbotc",
                            }
                            key = key_map.get(child.tag, child.tag.lower())
                            sensor_coeffs[key] = float(child.text)
                        elif child.tag.startswith("PA"):  # Pressure coeffs
                            sensor_coeffs[child.tag.lower()] = float(child.text)
                        elif child.tag.startswith("PTC"):  # Pressure temp compensation
                            sensor_coeffs[child.tag.lower()] = float(child.text)
                        elif child.tag.startswith("PTEMP"):  # Pressure temp coeffs
                            sensor_coeffs[child.tag.lower()] = float(child.text)
                        elif child.tag.startswith("OX") or child.tag in [
                            "TAU20",
                            "NTAU",
                        ]:  # Oxygen coeffs
                            sensor_coeffs[child.tag.lower()] = float(child.text)
                        elif child.tag in ["SerialNum", "CalDate"]:
                            sensor_coeffs[child.tag.lower()] = child.text

                    calibration_coeffs[sensor_id] = {
                        "coefficients": sensor_coeffs,
                        "format": cal_format,
                        "type": sensor_id,
                    }

    except Exception as e:
        print(f"Warning: Could not parse calibration coefficients: {e}")

    return {
        "enabled_sensors": enabled_sensors,
        "calibration_coefficients": calibration_coeffs,
    }


def sbe37_hex_reader(hex_file: Union[str, Path]) -> xr.Dataset:
    """
    Read SBE37 hex file using seabirdscientific library.

    Parameters
    ----------
    hex_file : Union[str, Path]
        Path to .hex file

    Returns
    -------
    xr.Dataset
        Dataset containing temperature, conductivity, pressure, and/or oxygen data
    """
    hex_path = Path(hex_file)
    if not hex_path.exists():
        raise FileNotFoundError(f"Hex file not found: {hex_path}")

    # Parse sensors and calibration coefficients from hex header
    header_info = parse_hex_header_sensors(hex_path)
    enabled_sensors_list = header_info["enabled_sensors"]
    calibration_coeffs = header_info.get("calibration_coefficients", {})

    # Fallback: Look for corresponding xmlcon file if header parsing fails
    xmlcon_info = None
    if not enabled_sensors_list:
        xmlcon_path = hex_path.with_suffix(".xmlcon")
        if not xmlcon_path.exists():
            # Try without hex extension
            xmlcon_path = hex_path.parent / f"{hex_path.stem}.xmlcon"

        if xmlcon_path.exists():
            xmlcon_info = sbe37_xmlcon_reader(xmlcon_path)
            enabled_sensors_list = xmlcon_info["enabled_sensors"]
        else:
            raise ValueError(
                f"Could not determine sensor configuration for {hex_path}. No xmlcon file found and header parsing failed."
            )

    print(f"Detected enabled sensors: {enabled_sensors_list}")
    if calibration_coeffs:
        print(f"Found calibration coefficients for: {list(calibration_coeffs.keys())}")

    try:
        import seabirdscientific.instrument_data as id
    except ImportError:
        raise ImportError(
            "seabirdscientific package required for SBE37 hex file reading"
        )

    # Build enabled sensors list following the example format
    enabled_sensors = []

    # Always include basic sensors first
    if "temperature" in enabled_sensors_list:
        enabled_sensors.append(id.Sensors.Temperature)
    if "conductivity" in enabled_sensors_list:
        enabled_sensors.append(id.Sensors.Conductivity)
    if "pressure" in enabled_sensors_list:
        enabled_sensors.append(id.Sensors.Pressure)

    # Add oxygen sensor if detected - use SBE63 format for ODO instruments
    if "oxygen" in enabled_sensors_list:
        enabled_sensors.append(id.Sensors.SBE63)
        # Keep using SBE37SM type since SBE63 is handled in the same parsing function
        instrument_type = id.InstrumentType.SBE37SM
    else:
        instrument_type = id.InstrumentType.SBE37SM

    print(f"Using instrument type: {instrument_type.value}")
    print(f"Enabled sensors: {[s.value for s in enabled_sensors]}")

    # Read the hex file
    raw_data = id.read_hex_file(
        filepath=str(hex_path),
        instrument_type=instrument_type,
        enabled_sensors=enabled_sensors,
    )

    # Import conversion functions and coefficient classes
    try:
        import seabirdscientific.conversion as conv
        from seabirdscientific.cal_coefficients import (
            TemperatureCoefficients,
            ConductivityCoefficients,
            PressureCoefficients,
        )
    except ImportError:
        raise ImportError(
            "seabirdscientific conversion module required for calibration"
        )

    # Convert to xarray Dataset
    data_vars = {}

    # Extract time coordinate from raw data
    times = pd.to_datetime(raw_data["date time"])
    n_samples = len(times)

    # Apply calibration coefficients if available (from header or xmlcon)
    if calibration_coeffs or xmlcon_info:
        print("Applying calibration coefficients to convert raw data")

        # Use header calibration coefficients if available, otherwise fall back to xmlcon
        if calibration_coeffs:
            sensor_configs = calibration_coeffs
        else:
            sensor_configs = xmlcon_info["sensors"]

        # Process each sensor type and apply calibrations
        for sensor_id, sensor_info in sensor_configs.items():
            sensor_type = sensor_info["type"]
            coeffs = sensor_info["coefficients"]

            if sensor_type == "temperature" and "temperature" in raw_data.columns:
                # Create temperature coefficients object - filter to only numeric coefficients
                temp_coeffs_filtered = {
                    k: v
                    for k, v in coeffs.items()
                    if k in ["a0", "a1", "a2", "a3"] and isinstance(v, (int, float))
                }
                temp_coefs = TemperatureCoefficients(**temp_coeffs_filtered)

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
                # Create conductivity coefficients object - filter to expected coefficients
                cond_coeffs_filtered = {
                    k: v
                    for k, v in coeffs.items()
                    if k in ["g", "h", "i", "j", "cpcor", "ctcor", "wbotc"]
                    and isinstance(v, (int, float))
                }
                cond_coefs = ConductivityCoefficients(**cond_coeffs_filtered)

                # Convert raw counts to calibrated conductivity
                # Note: This requires temperature for full conversion
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
                # Create pressure coefficients object - filter to expected coefficients
                press_coeffs_filtered = {
                    k: v
                    for k, v in coeffs.items()
                    if k.startswith(("pa", "ptc", "ptemp"))
                    and isinstance(v, (int, float))
                }
                press_coefs = PressureCoefficients(**press_coeffs_filtered)

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

            # Handle oxygen data - apply SBE63 calibration to convert phase to ml/L
            elif sensor_type == "oxygen" and "SBE63 oxygen phase" in raw_data.columns:
                try:
                    # Import SBE63 oxygen conversion
                    from seabirdscientific.cal_coefficients import (
                        Oxygen63Coefficients,
                        Thermistor63Coefficients,
                    )

                    # Create oxygen coefficients object
                    oxygen_coeffs_filtered = {
                        "a0": coeffs.get("oxa0", 0),
                        "a1": coeffs.get("oxa1", 0),
                        "a2": coeffs.get("oxa2", 0),
                        "b0": coeffs.get("oxb0", 0),
                        "b1": coeffs.get("oxb1", 0),
                        "c0": coeffs.get("oxc0", 0),
                        "c1": coeffs.get("oxc1", 0),
                        "c2": coeffs.get("oxc2", 0),
                        "e": coeffs.get("oxe", 0),
                    }
                    oxy_coefs = Oxygen63Coefficients(**oxygen_coeffs_filtered)

                    # Create thermistor coefficients object
                    therm_coeffs_filtered = {
                        "ta0": coeffs.get("oxta0", 0),
                        "ta1": coeffs.get("oxta1", 0),
                        "ta2": coeffs.get("oxta2", 0),
                        "ta3": coeffs.get("oxta3", 0),
                    }
                    therm_coefs = Thermistor63Coefficients(**therm_coeffs_filtered)

                    # Get required data for conversion
                    oxygen_phase = raw_data[
                        "SBE63 oxygen phase"
                    ].values  # in microseconds
                    oxygen_temp = raw_data[
                        "SBE63 oxygen temperature"
                    ].values  # in degrees C

                    # We need pressure and salinity for full conversion
                    if (
                        "temp" in data_vars
                        and "cond" in data_vars
                        and "press" in data_vars
                    ):
                        # Calculate salinity from temp, cond, press (basic approximation)
                        # For now, use a typical seawater salinity of 35 PSU
                        pressure_vals = data_vars["press"][1]  # Get pressure values
                        salinity_vals = np.full_like(
                            pressure_vals, 35.0
                        )  # Assume 35 PSU

                        # Convert oxygen phase to ml/L
                        oxygen_ml_per_l = conv.convert_sbe63_oxygen(
                            raw_oxygen_phase=oxygen_phase,
                            thermistor=oxygen_temp,
                            pressure=pressure_vals,
                            salinity=salinity_vals,
                            coefs=oxy_coefs,
                            thermistor_coefs=therm_coefs,
                            thermistor_units="C",  # oxygen_temp is already in Celsius
                        )

                        # Convert ml/L to μmol/L for comparison with CTD SBE43 sensors
                        # 1 ml/L O2 = 44.66 μmol/L at STP
                        oxygen_umol_per_l = oxygen_ml_per_l * 44.66

                        data_vars["oxygen"] = ("time", oxygen_umol_per_l)
                        data_vars["oxygen_ml_l"] = ("time", oxygen_ml_per_l)
                    else:
                        # Fallback: use raw data if we don't have all required variables
                        data_vars["oxygen_phase"] = ("time", oxygen_phase)
                        data_vars["oxygen_temp"] = ("time", oxygen_temp)

                except Exception as e:
                    print(f"Warning: Could not apply oxygen calibration: {e}")
                    # Fallback to raw data
                    data_vars["oxygen_phase"] = (
                        "time",
                        raw_data["SBE63 oxygen phase"].values,
                    )
                    data_vars["oxygen_temp"] = (
                        "time",
                        raw_data["SBE63 oxygen temperature"].values,
                    )
    else:
        # No xmlcon file - use raw data directly from seabirdscientific
        print("No calibration coefficients available - using raw converted data")

        # Add available sensors from raw_data
        if "temperature" in raw_data.columns:
            data_vars["temp"] = ("time", raw_data["temperature"].values)
        if "conductivity" in raw_data.columns:
            data_vars["cond"] = ("time", raw_data["conductivity"].values)
        if "pressure" in raw_data.columns:
            data_vars["press"] = ("time", raw_data["pressure"].values)
        # Handle SBE63 oxygen data (phase and temperature)
        if "SBE63 oxygen phase" in raw_data.columns:
            data_vars["oxygen_phase"] = ("time", raw_data["SBE63 oxygen phase"].values)
        if "SBE63 oxygen temperature" in raw_data.columns:
            data_vars["oxygen_temp"] = (
                "time",
                raw_data["SBE63 oxygen temperature"].values,
            )

    # Create dataset
    ds = xr.Dataset(data_vars, coords={"time": times})

    # Add units as variable attributes
    if "temp" in data_vars:
        ds["temp"].attrs["units"] = "degrees_C"
        ds["temp"].attrs["long_name"] = "Temperature"
    if "cond" in data_vars:
        ds["cond"].attrs["units"] = "mS/cm"
        ds["cond"].attrs["long_name"] = "Conductivity"
    if "press" in data_vars:
        ds["press"].attrs["units"] = "dbar"
        ds["press"].attrs["long_name"] = "Pressure"
    if "oxygen" in data_vars:
        ds["oxygen"].attrs["units"] = "umol/L"
        ds["oxygen"].attrs["long_name"] = "Dissolved Oxygen"
    if "oxygen_ml_l" in data_vars:
        ds["oxygen_ml_l"].attrs["units"] = "ml/L"
        ds["oxygen_ml_l"].attrs["long_name"] = "Dissolved Oxygen (ml/L)"
    if "oxygen_phase" in data_vars:
        ds["oxygen_phase"].attrs["units"] = "degrees"
        ds["oxygen_phase"].attrs["long_name"] = "Oxygen Phase"
    if "oxygen_temp" in data_vars:
        ds["oxygen_temp"].attrs["units"] = "degrees_C"
        ds["oxygen_temp"].attrs["long_name"] = "Oxygen Sensor Temperature"

    # Add metadata
    ds.attrs["source_file"] = str(hex_path)
    if xmlcon_info:
        ds.attrs["xmlcon_file"] = str(xmlcon_path)
    else:
        ds.attrs["sensor_detection"] = "hex_header"
    ds.attrs["instrument_type"] = "SBE37"
    ds.attrs["data_type"] = "calibrated"

    # Add sensor information as attributes
    if xmlcon_info:
        for sensor_info in xmlcon_info["sensors"].values():
            sensor_type = sensor_info["type"]
            serial = sensor_info["serial_number"]
            cal_date = sensor_info["calibration_date"]

            ds.attrs[f"{sensor_type}_serial"] = serial
            ds.attrs[f"{sensor_type}_calibration_date"] = cal_date

    return ds
