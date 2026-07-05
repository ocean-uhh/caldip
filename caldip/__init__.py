"""
Caldip: Calibration dip analysis for oceanographic instruments.

This package provides tools for processing, analyzing, and visualizing data from
calibration dips performed with CTD profiles and multiple instrument types including
MicroCATs and RBR thermistors.
"""

from caldip.core import stats, find_bottle_stops
from caldip._plot import plot
from caldip.readers import load_config

__all__ = [
    "plot",
    "stats",
    "find_bottle_stops",
    "load_config",
    "core",
    "readers",
    "tools",
]
