
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
    for sensor_elem in root.findall('.//Sensor'):
        index = sensor_elem.get('index')
        if index is None:
            continue
            
        index = int(index)
        
        # Check what type of sensor this is
        temp_sensor = sensor_elem.find('TemperatureSensor')
        cond_sensor = sensor_elem.find('ConductivitySensor') 
        press_sensor = sensor_elem.find('PressureSensor')
        
        if temp_sensor is not None:
            sensors[index] = _parse_coefficients(temp_sensor, 'temperature', index)
            enabled_sensors.append('temperature')
            
        elif cond_sensor is not None:
            sensors[index] = _parse_coefficients(cond_sensor, 'conductivity', index)
            enabled_sensors.append('conductivity')
            
        elif press_sensor is not None:
            sensors[index] = _parse_coefficients(press_sensor, 'pressure', index)
            enabled_sensors.append('pressure')
    
    return {
        'sensors': sensors,
        'enabled_sensors': enabled_sensors,
        'xmlcon_path': xmlcon_path
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
    serial_num = sensor_elem.find('SerialNumber').text
    cal_date = sensor_elem.find('CalibrationDate').text
    
    # Parse all coefficient elements to lowercase keys
    coef_dict = {}
    
    if sensor_type == 'conductivity':
        # Special handling for conductivity - check UseG_J flag
        use_g_j_elem = sensor_elem.find('UseG_J')
        use_g_j = use_g_j_elem is not None and use_g_j_elem.text == '1'
        
        if use_g_j:
            # Look for equation="1" coefficients which contain G,H,I,J
            for coeffs_elem in sensor_elem.findall('Coefficients'):
                equation_attr = coeffs_elem.get('equation')
                if equation_attr == '1':
                    for child in coeffs_elem:
                        if child.text:
                            coef_dict[child.tag.lower()] = float(child.text)
                    break
        else:
            # Use equation="0" with A,B,C,D coefficients  
            for coeffs_elem in sensor_elem.findall('Coefficients'):
                equation_attr = coeffs_elem.get('equation')
                if equation_attr == '0':
                    for child in coeffs_elem:
                        if child.text:
                            coef_dict[child.tag.lower()] = float(child.text)
                    break
        
        # Also parse direct children (slope, offset, etc.)
        for child in sensor_elem:
            if child.tag.lower() in ['slope', 'offset']:
                if child.text:
                    coef_dict[child.tag.lower()] = float(child.text)
    
    else:
        # For temperature and pressure, parse all numeric child elements
        for child in sensor_elem:
            if child.text and child.tag not in ['SerialNumber', 'CalibrationDate']:
                try:
                    coef_dict[child.tag.lower()] = float(child.text)
                except ValueError:
                    # Skip non-numeric elements
                    continue
    
    # Separate seabirdscientific calibration coefficients from slope/offset
    cal_coeffs = {}
    metadata = {}
    
    # Define expected coefficient names for each sensor type
    if sensor_type == 'temperature':
        expected_coeffs = ['a0', 'a1', 'a2', 'a3']
    elif sensor_type == 'conductivity':
        expected_coeffs = ['g', 'h', 'i', 'j', 'cpcor', 'ctcor', 'wbotc']
    elif sensor_type == 'pressure':
        expected_coeffs = ['pa0', 'pa1', 'pa2', 'ptca0', 'ptca1', 'ptca2', 
                          'ptcb0', 'ptcb1', 'ptcb2', 'ptempa0', 'ptempa1', 'ptempa2']
    else:
        expected_coeffs = []
    
    # Split coefficients
    for key, value in coef_dict.items():
        if key in expected_coeffs:
            cal_coeffs[key] = value
        else:
            metadata[key] = value
    
    return {
        'type': sensor_type,
        'serial_number': serial_num,
        'calibration_date': cal_date,
        'coefficients': cal_coeffs,
        'metadata': metadata,
        'index': sensor_index
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
        Dataset containing temperature, conductivity, and/or pressure data
    """
    hex_path = Path(hex_file)
    if not hex_path.exists():
        raise FileNotFoundError(f"Hex file not found: {hex_path}")
    
    # Look for corresponding xmlcon file
    xmlcon_path = hex_path.with_suffix('.xmlcon')
    if not xmlcon_path.exists():
        # Try without hex extension
        xmlcon_path = hex_path.parent / f"{hex_path.stem}.xmlcon"
        
    if not xmlcon_path.exists():
        raise FileNotFoundError(f"No corresponding xmlcon file found for {hex_path}")
    
    # Parse xmlcon to determine sensor configuration
    xmlcon_info = sbe37_xmlcon_reader(xmlcon_path)
    
    try:
        import seabirdscientific.instrument_data as id
    except ImportError:
        raise ImportError("seabirdscientific package required for SBE37 hex file reading")
    
    # Map our sensor types to seabirdscientific sensor types
    sensor_mapping = {
        'temperature': id.Sensors.Temperature,
        'conductivity': id.Sensors.Conductivity, 
        'pressure': id.Sensors.Pressure
    }
    
    enabled_sensors = [sensor_mapping[s] for s in xmlcon_info['enabled_sensors'] 
                      if s in sensor_mapping]
    
    # Read the hex file
    raw_data = id.read_hex_file(
        filepath=str(hex_path),
        instrument_type=id.InstrumentType.SBE37SM,  # Assuming SBE37SM
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
        raise ImportError("seabirdscientific conversion module required for calibration")
    
    # Convert to xarray Dataset
    data_vars = {}
    
    # Extract time coordinate from raw data
    times = pd.to_datetime(raw_data["date time"])
    n_samples = len(times)
    
    # Process each sensor type and apply calibrations
    for sensor_info in xmlcon_info['sensors'].values():
        sensor_type = sensor_info['type']
        coeffs = sensor_info['coefficients']
        
        if sensor_type == 'temperature' and 'temperature' in raw_data.columns:
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
            data_vars['temp'] = ('time', temperature)
            
        elif sensor_type == 'conductivity' and 'conductivity' in raw_data.columns:
            # Create conductivity coefficients object
            cond_coefs = ConductivityCoefficients(**coeffs)
            
            # Convert raw counts to calibrated conductivity
            # Note: This requires temperature for full conversion
            temp_values = data_vars.get('temp', (None, np.zeros(n_samples)))[1]
            pressure_values = np.zeros(n_samples)  # Will be updated if pressure is available
            
            conductivity = conv.convert_conductivity(
                conductivity_count=raw_data["conductivity"].values,
                temperature=temp_values,
                pressure=pressure_values,
                coefs=cond_coefs,
            )
            # Convert from S/m to mS/cm (multiply by 10)
            conductivity_mScm = conductivity * 10.0
            data_vars['cond'] = ('time', conductivity_mScm)
            
        elif sensor_type == 'pressure' and 'pressure' in raw_data.columns:
            # Create pressure coefficients object
            press_coefs = PressureCoefficients(**coeffs)
            
            # Convert raw counts to calibrated pressure
            # For SBE37, use temperature compensation if available
            temp_comp_values = raw_data.get("temperature compensation", np.zeros(n_samples))
            if hasattr(temp_comp_values, 'values'):
                temp_comp_values = temp_comp_values.values
            
            pressure = conv.convert_pressure(
                pressure_count=raw_data["pressure"].values,
                compensation_voltage=temp_comp_values,
                coefs=press_coefs,
                units="dbar"
            )
            data_vars['press'] = ('time', pressure)
    
    # Create dataset
    ds = xr.Dataset(data_vars, coords={'time': times})
    
    # Add units as variable attributes
    if 'temp' in data_vars:
        ds['temp'].attrs['units'] = 'degrees_C'
        ds['temp'].attrs['long_name'] = 'Temperature'
    if 'cond' in data_vars:
        ds['cond'].attrs['units'] = 'mS/cm'
        ds['cond'].attrs['long_name'] = 'Conductivity'
    if 'press' in data_vars:
        ds['press'].attrs['units'] = 'dbar'
        ds['press'].attrs['long_name'] = 'Pressure'
    
    # Add metadata
    ds.attrs['source_file'] = str(hex_path)
    ds.attrs['xmlcon_file'] = str(xmlcon_path)
    ds.attrs['instrument_type'] = 'SBE37'
    ds.attrs['data_type'] = 'calibrated'
    
    # Add sensor information as attributes
    for sensor_info in xmlcon_info['sensors'].values():
        sensor_type = sensor_info['type']
        serial = sensor_info['serial_number']
        cal_date = sensor_info['calibration_date']
        
        ds.attrs[f'{sensor_type}_serial'] = serial
        ds.attrs[f'{sensor_type}_calibration_date'] = cal_date
    
    return ds
