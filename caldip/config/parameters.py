"""caldip-specific processing constants.

Single source of truth for bottle-stop detection defaults. Both
:func:`caldip.core.find_bottle_stops` (used by ``caldip stats``) and
:func:`caldip.plot` import these, so the stats table and the figure detect the
*same* stops. Previously ``core.py`` used ``10.0 / 180.0`` while ``_plot.py``
hardcoded ``30.0 / 120.0``, so the two disagreed.

Changing these values changes which stops appear in every output.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Bottle-stop detection  [Science — changing gives a different set of stops]
# ---------------------------------------------------------------------------
# A cal-dip cast pauses the CTD at each bottle stop so instruments equilibrate.
# During a stop, pressure is nearly constant; during winch movement it changes
# fast. Detection slides a 60 s window and flags periods below the rate gate.

# Maximum pressure change rate (dbar/min) still counted as "holding station".
# Below this the CTD is treated as stopped; at or above it the winch is moving.
BOTTLE_STOP_THRESHOLD_DBAR_PER_MIN: float = 15.0

# Minimum duration (seconds) a detected stop must last to be kept as a real
# bottle stop. Shorter stable periods are discarded as noise.
#
# NOTE (planned extension): temperature and pressure equilibrate faster than
# conductivity, so a future revision may allow per-variable minimum durations
# (e.g. a shorter minimum for temperature/pressure than for conductivity).
# The plotting API already threads a ``bottle_stop_params`` dict, which is the
# natural place to grow per-variable keys once the science values are fixed.
BOTTLE_STOP_MIN_DURATION_SECONDS: float = 180.0

# Sliding-window length (seconds) over which the pressure change rate is measured.
BOTTLE_STOP_WINDOW_SECONDS: float = 60.0

# Detection only starts once the cast is within this many dbar of its maximum
# pressure, so stops near the bottom are found without scanning the whole downcast.
BOTTLE_STOP_SEARCH_MARGIN_DBAR: float = 10.0

# Initial pre-gate: a stable period shorter than this (seconds) is dropped before
# boundary refinement. Looser than ``MIN_DURATION_SECONDS``, which is applied last.
BOTTLE_STOP_INITIAL_MIN_SECONDS: float = 30.0

# Boundary refinement: the start/end are moved to the first/last sample within
# this many dbar of the stop's median pressure.
BOTTLE_STOP_BOUNDARY_TOL_DBAR: float = 2.0

# Two detected stops separated by fewer than this many samples are merged into one.
BOTTLE_STOP_MERGE_GAP_SAMPLES: int = 10


# ---------------------------------------------------------------------------
# Per-variable usability flags  [Output schema — CF flag variable in the netCDF]
# ---------------------------------------------------------------------------
# Closed usability set emitted by caldip.core.stats as the temp_flag / cond_flag /
# press_flag columns and written to {cast}_caldip.nc as a CF flag variable, which
# the report reads directly. Single source so the producer (core) and the writer
# (_writers) cannot drift.
USABILITY_FLAG_OK: int = 1
USABILITY_FLAG_NO_DATA: int = 2
USABILITY_FLAG_FLAGGED: int = 3
USABILITY_FLAG_MISSING: int = 4
USABILITY_FLAG_UNKNOWN: int = 9

# CF ``flag_values`` / ``flag_meanings`` pair, in matching order.
USABILITY_FLAG_VALUES: tuple[int, ...] = (1, 2, 3, 4, 9)
USABILITY_FLAG_MEANINGS: str = "ok no_data flagged missing unknown"


# ---------------------------------------------------------------------------
# Quality-flag thresholds  [Science — |instrument - CTD| above these is flagged]
# ---------------------------------------------------------------------------
# A per-stop difference at or below the threshold is "OK"; above it is flagged
# "reads high/low". Overridable per cast in the YAML under
# ``quality_flags: {temp_threshold: ..., cond_threshold: ..., press_threshold: ...}``.
QUALITY_TEMP_THRESHOLD: float = 0.005  # degree_C
QUALITY_COND_THRESHOLD: float = 0.02  # mS cm-1
QUALITY_PRESS_THRESHOLD: float = 5.0  # dbar


# ---------------------------------------------------------------------------
# Instrument classes  [Output schema — ``instrument_type`` in the netCDF]
# ---------------------------------------------------------------------------
# The controlled vocabulary for the cruise-YAML ``instrument:`` field and the
# ``instrument_type`` variable. Extracted 2026-09-07 from the *keys* of
# ``oceanarray.config.parameters.INSTRUMENT_FILE_TYPES``, which is the source
# of truth; the dict's values are oceanarray's file_type policy and are not
# shared. Class names, lowercase: every SBE37 variant is "microcat" (the
# variant stays in ``label``). Adding a class means adding it there first.
# NOTE: ``adcp`` is lowercase here, following the per-serial inventory; the
# oceanarray code still spells it ``ADCP`` (its own to reconcile). caldip dips
# no ADCPs, so the two never meet in a join today.
INSTRUMENT_CLASSES: tuple[str, ...] = (
    "microcat",
    "sbe56",
    "sbe16",
    "aquadopp",
    "tr1050",
    "rbrsolo",
    "rbrduet",
    "seapoint",
    "adcp",
)

# Which of caldip's three compared variables each class measures. A class
# without a variable gets USABILITY_FLAG_NO_DATA for it by construction, and a
# YAML naming an empty-tuple class is refused on load (a real class caldip does
# not compare, not an unknown one). "microcat" pressure depends on the model
# (inventory ``pressure`` column). ``seapoint`` measures turbidity only.
# ``adcp`` has real T/P channels, but an ADCP never rides the rosette, so the
# empty tuple records caldip's scope rather than the instrument's physics.
# Defined for provenance; the flag path still derives no_data from whether the
# reader produced the variable, so the two agree without this being enforced.
INSTRUMENT_CLASS_VARIABLES: dict[str, tuple[str, ...]] = {
    "microcat": ("temp", "cond", "press"),
    "sbe16": ("temp", "cond", "press"),
    "sbe56": ("temp",),
    "tr1050": ("temp",),
    "rbrsolo": ("temp",),
    "rbrduet": ("temp", "cond", "press"),  # T + one of C/P per the .rsk channels
    "aquadopp": ("temp", "press"),
    "seapoint": (),
    "adcp": (),
}

# Legacy ``instrument:`` values from pre-vocabulary cruise YAMLs, mapped to a
# class above. Accepted on load with a deprecation warning and removed at
# v1.0.0. ``rbr`` needs the file_type to choose (matlab-legacy -> tr1050,
# rsk -> rbrsolo); the rest map on the lowercased value alone (file_type None).
# A mere case variant of a real class (``MicroCAT`` -> ``microcat``) is not a
# legacy alias -- resolve_instrument_class matches the class tuple
# case-insensitively, so it is accepted without a warning. Every real
# cruise-YAML value as of 2026-09-07 is covered here.
LEGACY_INSTRUMENT_ALIASES: dict[tuple[str, str | None], str] = {
    ("sbe", None): "microcat",
    ("sbe37", None): "microcat",
    ("nortek", None): "aquadopp",
    ("rbr", "rbr-matlab-legacy"): "tr1050",
    ("rbr", "rbr-rsk"): "rbrsolo",
}
