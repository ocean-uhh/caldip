"""Classify caldip per-variable status strings into a closed set of kinds.

caldip writes a short prose status for each variable of each instrument into the
``temp_status`` / ``cond_status`` / ``press_status`` columns of the detailed
statistics CSV (for example ``"T OK"``, ``"C NO DATA"``,
``"T reads high by 0.008"``). The report needs to decide *usable / not usable*
from that prose without inheriting an open-ended negative rule: any future
wording change should surface as ``unknown`` and warn, not silently count as a
problem.

The vocabulary is a closed set of three templates (nine forms once embedded
numbers are normalised):

- ``{T,C,P} OK``                     -> ``ok``
- ``{T,C,P} NO DATA``               -> ``no_data``
- ``{T,C,P} reads {high,low} by N`` -> ``flagged`` (with direction and magnitude)

An empty cell is ``missing`` (absence, not a problem, no warning). Anything else
non-empty is ``unknown`` and should be warned about by the caller.

This prose parsing is a workaround for a gap: caldip does not yet emit a
machine-readable per-variable status. Once it emits ``temp_usable`` /
``cond_usable`` / ``press_usable`` (requested as §5 of the oceanarray CSV
requirements), this module shrinks to a column read and the template matching here
can be removed. Do not mistake the prose parsing for the intended design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_OK_RE = re.compile(r"^[TCP] OK$")
_NO_DATA_RE = re.compile(r"^[TCP] NO DATA$")
_FLAG_RE = re.compile(r"^[TCP] reads (high|low) by ([-+]?[0-9]*\.?[0-9]+)$")

#: Kinds that mean "the instrument reported a real value we can trust".
OK_KIND = "ok"
#: Kinds that are neither usable nor a defect (variable simply not measured).
NO_DATA_KIND = "no_data"
#: A real caldip flag: the instrument reads high/low by a stated magnitude.
FLAGGED_KIND = "flagged"
#: An empty status cell.
MISSING_KIND = "missing"
#: A non-empty status that matches none of the known templates.
UNKNOWN_KIND = "unknown"


@dataclass(frozen=True)
class StatusClassification:
    """The classification of a single caldip status string.

    Parameters
    ----------
    kind : str
        One of ``"ok"``, ``"no_data"``, ``"flagged"``, ``"missing"``,
        ``"unknown"``.
    direction : str or None
        ``"high"`` or ``"low"`` for a flagged status; ``None`` otherwise.
    magnitude : float or None
        The magnitude caldip reported (same unit as the variable) for a flagged
        status; ``None`` otherwise.
    raw : str
        The original stripped status string.
    """

    kind: str
    direction: str | None
    magnitude: float | None
    raw: str


def classify_status(text: str | None) -> StatusClassification:
    """Classify a single caldip per-variable status string.

    Parameters
    ----------
    text : str or None
        A status cell from the detailed statistics CSV, e.g. ``"T OK"`` or
        ``"C reads low by 0.021"``. ``None`` or empty is treated as missing.

    Returns
    -------
    StatusClassification
        The kind and, for flagged statuses, the direction and magnitude.
    """
    raw = (text or "").strip()
    if raw == "":
        return StatusClassification(MISSING_KIND, None, None, raw)
    if _OK_RE.match(raw):
        return StatusClassification(OK_KIND, None, None, raw)
    if _NO_DATA_RE.match(raw):
        return StatusClassification(NO_DATA_KIND, None, None, raw)
    match = _FLAG_RE.match(raw)
    if match:
        return StatusClassification(
            FLAGGED_KIND, match.group(1), float(match.group(2)), raw
        )
    return StatusClassification(UNKNOWN_KIND, None, None, raw)
