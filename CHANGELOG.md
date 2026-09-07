# Changelog

All notable changes to caldip are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and caldip uses
[semantic versioning](https://semver.org/spec/v2.0.0.html) (read for a scientific
package: before 1.0, a minor bump may change output files or public calls, and
those changes are listed under **Breaking changes**).

## [0.2.0] - 2026-09-07

### Added

- `{cast}_caldip.nc`, a per-cast netCDF that is now caldip's machine-readable
  statistics output. It is a two-dimensional `(instrument, stop)` grid: instrument
  identity along `instrument`; the CTD reference, a `datetime64` `time` coordinate
  and the bottle-stop pressure along `stop`; and the per-instrument-per-stop
  differences, standard deviations, sample counts and usability flags on the grid.
  Every variable carries `units`, every difference states its sign convention, and
  absent values are `NaN` rather than `0` or empty.
- Per-variable usability as a CF/QARTOD flag variable (`temp_flag` / `cond_flag` /
  `press_flag`), each carrying the `flagging_threshold` used.
- A complete provenance attribute block on every netCDF (identity, versions,
  `data_mode`, lineage and the CTD-reference fields), with `UNK` where a value
  cannot yet be sourced.
- `caldip inspect <file.nc>`, which writes a browsable HTML inventory of a netCDF
  (dimensions, variables with shapes and units, and global attributes).
- `caldip report` now generates a per-cast netCDF inventory page and links it from
  each cast page, and reads the cruise name and usability counts from the netCDF.
- A controlled vocabulary for the instrument class, in
  `caldip.config.parameters.INSTRUMENT_CLASSES` (the nine oceanarray classes:
  `microcat`, `sbe56`, `sbe16`, `aquadopp`, `tr1050`, `rbrsolo`, `rbrduet`,
  `seapoint`, `adcp`). `load_config` validates the cruise-YAML `instrument:` field
  against it and normalises legacy values (`sbe37`/`sbe`/`MicroCAT` → `microcat`,
  `nortek` → `aquadopp`, `rbr` → `tr1050` or `rbrsolo` by `file_type`) with a
  deprecation warning; `caldip init` now scaffolds class names directly.

### Changed

- The detailed statistics CSV is now a derived export of the netCDF, with the same
  columns as before plus constant `cast_id`, `schema_version` and `tracking_id`
  columns; empty cells (not the string `NaN`) mark absent values.
- `caldip stats` writes the netCDF and derives the CSV from it in one run.
- `{cast}_summary_statistics.csv` values may differ from earlier output in the last
  decimal place for boundary cases: the summary is now rounded once from the
  full-precision differences rather than from already-rounded detailed values.

### Breaking changes

- `caldip.stats()` now returns full-precision difference columns (`temp_diff`,
  `cond_diff`, `press_diff`); it previously rounded them. Rounding moved to the CSV
  export, so the detailed CSV is unchanged. A caller relying on the pre-rounded API
  values must round its own.
- `caldip report` now requires each cast's `{cast}_caldip.nc` to count flags and
  read the cruise; a directory of CSVs alone reports zero flags and an `UNK` cruise
  with a warning. Re-run `caldip stats` to produce the netCDF.
- `instrument_type` in the netCDF and CSV is now an oceanarray class name, not the
  raw YAML string; a cruise YAML naming an old value (`rbr`, `sbe`, `sbe37`, …) still
  loads but warns, and the aliases are removed at v1.0.0. A YAML naming `instrument:`
  outside the vocabulary is now refused on load.
- The `dip_role` global attribute is removed from the netCDF. Pre- versus
  post-deployment is a property of the (instrument, deployment) pair, which
  oceanarray assigns from the cast time against each instrument's deployment window;
  caldip guarantees only that the cast is datable.
- Instrument serials are normalised on load (leading zeros and a trailing marker
  asterisk stripped, so `013874` and `9920*` become `13874` and `9920`), matching
  the join key oceanarray uses.

## [0.1.0] - 2026-07-05

### Added

- Initial release: `caldip init`, `caldip ctd`, `caldip plot`, `caldip stats` and
  `caldip report` for calibration-dip analysis of CTD, MicroCAT and RBR data.

[0.2.0]: https://github.com/ocean-uhh/caldip/releases/tag/v0.2.0
[0.1.0]: https://github.com/ocean-uhh/caldip/releases/tag/v0.1.0
