# YAML Configuration Reference

Each calibration dip cast requires a `*.caldip.yaml` configuration file that tells caldip where to find the CTD reference data and all deployed instruments.

## Directory structure

On the UHH ExO data server, calibration dip data live under the mooring data tree:

```
moor/
└── proc_calib/
    └── {cruise_id}/
        └── cal_dip/
            └── cast{ID}/
                ├── {mooring_id}.caldip.yaml   ← configuration file
                ├── {ctd_file}.cnv             ← CTD reference cast
                └── {serial}_{date}.{ext}      ← one file per instrument
```

For example:
```
moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml
```

All filenames in the YAML are relative to the `directory` field (i.e., the cast folder).

---

## Generating a stub

`generate_stub_yaml.py` scans a cast directory for recognised instrument files and writes a skeleton YAML:

```bash
# Write YAML to the directory
python generate_stub_yaml.py moor/proc_calib/msm142_2026/cal_dip/castM4/

# Print to stdout instead
python generate_stub_yaml.py --print-only moor/proc_calib/msm142_2026/cal_dip/castM4/
```

`generate_stub_yamls.sh` wraps this for batch processing multiple cast directories.

After generation, open the stub and fill in the fields marked `null` or `.nan`.

---

## Field reference

### Cast metadata

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Short cast identifier, e.g. `castM4` |
| `cruise` | string | yes | Cruise identifier, e.g. `msm142` |
| `ship` | string | recommended | Vessel name, e.g. `FS MSMerian` |
| `year` | integer | recommended | Year of cruise |

### Position and depth

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `deployment_latitude` | string | recommended | Latitude with hemisphere, e.g. `59 27.84 N` |
| `deployment_longitude` | string | recommended | Longitude with hemisphere, e.g. `048 27.21 W` |
| `latitude` | float | recommended | Decimal latitude (positive N) |
| `longitude` | float | recommended | Decimal longitude (positive E) |
| `waterdepth` | float | optional | Bottom depth in metres (`.nan` if unknown) |

### Timing

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `deployment_time` | ISO 8601 string | yes | Time CTD entered water, e.g. `'2026-04-03T03:05:36'` |
| `recovery_time` | ISO 8601 string | yes | Time CTD left water |

### CTD reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `directory` | string | yes | Path to cast folder (relative to repo root or absolute) |
| `ctd_file` | string | yes | CTD `.cnv` filename |
| `ctd_sensors` | integer | recommended | Which sensor pair to use: `1` (primary) or `2` (secondary) |

### Instruments list

`instruments` is a list; each entry describes one deployed instrument.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `position` | string | recommended | Position number on mooring frame, e.g. `'1'` |
| `serial` | string or integer | yes | Instrument serial number |
| `label` | string | recommended | Human-readable model, e.g. `SBE37`, `TR1050` |
| `instrument` | string | yes | Instrument family: `sbe37`, `sbe`, or `rbr` |
| `file_type` | string | yes | File format (see table below) |
| `filename` | string | yes | Data filename relative to `directory` |
| `depth` | float | recommended | Nominal mooring depth in metres |
| `clock_offset` | integer | optional | Clock correction in seconds (positive = instrument clock runs fast) |

#### Supported `file_type` values

| `file_type` | Instrument | Format |
|-------------|------------|--------|
| `sbe-cnv` | SBE37 MicroCAT | SeaBird processed `.cnv` |
| `sbe-hex` | SBE37 MicroCAT | SeaBird raw `.hex` with embedded calibration |
| `sbe-asc` | SBE37 MicroCAT | SeaBird ASCII `.asc` dump |
| `rbr-matlab-legacy` | RBR TR-1050 thermistor | Legacy MATLAB `.mat` export |

---

## Minimal example (SBE37 hex files)

```yaml
name: castM3
cruise: msm142
ship: FS MSMerian
year: 2026
deployment_time: '2026-04-04T15:19:06'
recovery_time: '2026-04-04T18:11:16'
deployment_latitude: 58 01.63 N
deployment_longitude: 048 49.71 W
latitude: 58.0272
longitude: -48.8285
waterdepth: .nan
directory: 'moor/proc_calib/msm142_2026/cal_dip/castM3/'
ctd_file: 'msm_142_1_035_1sec.cnv'
ctd_sensors: 2
instruments:
  - position: '1'
    serial: '26271'
    label: 'SBE37'
    instrument: sbe37
    file_type: sbe-hex
    filename: SBE37SMP-RS232_03726271_2026_04_04.hex
    depth: 0
  - position: '2'
    serial: '26270'
    label: 'SBE37'
    instrument: sbe37
    file_type: sbe-hex
    filename: SBE37SMP-RS232_03726270_2026_04_04.hex
    depth: 0
```

## Example with RBR thermistors and clock offset

```yaml
name: castM4
cruise: msm142
ship: FS MSMerian
year: 2026
deployment_time: '2026-04-03T03:05:36'
recovery_time: '2026-04-03T05:08:24'
deployment_latitude: 59 27.84 N
deployment_longitude: 048 27.21 W
latitude: 59.4640
longitude: -48.4535
waterdepth: .nan
directory: 'moor/proc_calib/msm142_2026/cal_dip/castM4/'
ctd_file: 'msm_142_1_032_1sec.cnv'
ctd_sensors: 2
instruments:
  - position: '1'
    serial: 013874
    label: 'TR1050'
    instrument: rbr
    file_type: rbr-matlab-legacy
    filename: '013874_20260403_1302.mat'
    depth: 0
    clock_offset: 7175
  - position: '17'
    serial: 13840
    label: 'SBE37'
    instrument: sbe
    file_type: sbe-cnv
    filename: '13840_cal_dip_data_time.cnv'
    depth: 0
```
