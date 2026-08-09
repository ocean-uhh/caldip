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
