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
