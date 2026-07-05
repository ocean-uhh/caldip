#!/usr/bin/env python3
"""
Calculate and verify the clock offset for TR1050 instruments.

Loads actual data files rather than using hardcoded timestamps.
Previously, dates in this script were written in YYYY-DD-MM order (European
day-first notation) but pandas parsed them as YYYY-MM-DD (ISO), producing
February/March timestamps instead of April.  This version avoids that bug by
reading timestamps directly from the mat files and CNV via the readers module.
"""

import copy
from pathlib import Path

import pandas as pd

from caldip import readers

DATA_DIR = Path("data/proc_calib/msm142_2026/cal_dip/castM4")
CONFIG_FILE = DATA_DIR / "castM4.caldip.yaml"
TARGET_SERIAL = "015581"  # TR1050 instrument to analyse

# ── load config ───────────────────────────────────────────────────────────────
config = readers.load_caldip_config(CONFIG_FILE)
deployment_start = pd.Timestamp(config["deployment_time"])
deployment_end = pd.Timestamp(config["recovery_time"])

print("=== TR1050 Clock Offset Analysis ===")
print(f"Deployment period: {deployment_start} to {deployment_end}")
print()

# ── load TR1050 raw timestamps (clock_offset forced to 0) ─────────────────────
configured_offset = None
config_raw = copy.deepcopy(config)
for inst in config_raw.get("instruments", []):
    if str(inst.get("serial", "")) == TARGET_SERIAL:
        configured_offset = inst.get("clock_offset", 0)
        inst["clock_offset"] = 0
        break
if configured_offset is None:
    raise ValueError(f"Serial {TARGET_SERIAL!r} not found in {CONFIG_FILE}")

instruments_raw = readers.load_instruments_from_config(config_raw, DATA_DIR)
tr1050_key = next(k for k in instruments_raw if str(k) == TARGET_SERIAL)
tr1050 = instruments_raw[tr1050_key]["data"]
tr1050_start_raw = pd.Timestamp(tr1050.time.values[0])
tr1050_end_raw = pd.Timestamp(tr1050.time.values[-1])

print(f"TR1050 {TARGET_SERIAL} raw timestamps (clock_offset=0):")
print(f"  Start: {tr1050_start_raw}")
print(f"  End:   {tr1050_end_raw}")
print(
    f"  Duration: {(tr1050_end_raw - tr1050_start_raw).total_seconds()/3600:.1f} hours"
)
print()

# ── load CTD reference ────────────────────────────────────────────────────────
reference_data = readers.load_reference_data(config, DATA_DIR)
ctd = list(reference_data.values())[0]["data"]
ctd_start = pd.Timestamp(ctd.time.values[0])
ctd_end = pd.Timestamp(ctd.time.values[-1])

print("CTD reference timestamps:")
print(f"  Start: {ctd_start}")
print(f"  End:   {ctd_end}")
print()

# ── load SBE37 if present ─────────────────────────────────────────────────────
# Load with clock_offset=0 so we see its raw times too
config_sbe_raw = copy.deepcopy(config)
for inst in config_sbe_raw["instruments"]:
    if inst.get("instrument", "") == "sbe":
        inst["clock_offset"] = 0
sbe_instruments = {
    k: v
    for k, v in readers.load_instruments_from_config(config_sbe_raw, DATA_DIR).items()
    if v["type"] == "sbe37"
}
if sbe_instruments:
    sbe_key = next(iter(sbe_instruments))
    sbe_data = sbe_instruments[sbe_key]["data"]
    sbe_start = pd.Timestamp(sbe_data.time.values[0])
    sbe_end = pd.Timestamp(sbe_data.time.values[-1])
    print(f"SBE37 {sbe_key} timestamps (clock_offset=0):")
    print(f"  Start: {sbe_start}")
    print(f"  End:   {sbe_end}")
    print()

# ── check coverage with configured offset ─────────────────────────────────────
print(
    f"Configured clock_offset in YAML: {configured_offset} seconds"
    f"  ({configured_offset/3600:.2f} hours)"
)
print()

tr1050_corrected_start = tr1050_start_raw + pd.Timedelta(seconds=configured_offset)
tr1050_corrected_end = tr1050_end_raw + pd.Timedelta(seconds=configured_offset)

print(f"TR1050 with clock_offset={configured_offset}s:")
print(f"  Start: {tr1050_corrected_start}")
print(f"  End:   {tr1050_corrected_end}")
print()

deploy_duration = (deployment_end - deployment_start).total_seconds()
if (
    tr1050_corrected_start <= deployment_end
    and tr1050_corrected_end >= deployment_start
):
    overlap_start = max(tr1050_corrected_start, deployment_start)
    overlap_end = min(tr1050_corrected_end, deployment_end)
    overlap_seconds = (overlap_end - overlap_start).total_seconds()
    print(
        f"Deployment coverage: {overlap_seconds:.0f}s / {deploy_duration:.0f}s"
        f"  ({100 * overlap_seconds / deploy_duration:.0f}%)"
    )
    if overlap_seconds >= deploy_duration:
        print("✅ TR1050 fully covers the deployment period")
    else:
        gap_start = tr1050_corrected_start > deployment_start
        gap_end = tr1050_corrected_end < deployment_end
        if gap_start:
            print(
                f"⚠️  Misses {(tr1050_corrected_start - deployment_start).total_seconds():.0f}s at start"
            )
        if gap_end:
            print(
                f"⚠️  Misses {(deployment_end - tr1050_corrected_end).total_seconds():.0f}s at end"
            )
else:
    print("❌ TR1050 does not overlap with the deployment period")
    needed = (deployment_start - tr1050_end_raw).total_seconds()
    print(f"   Minimum offset needed to reach deployment: {needed:.0f}s")

print()

# ── what offset would align TR1050 end with deployment end ────────────────────
offset_to_align_ends = (deployment_end - tr1050_end_raw).total_seconds()
print(
    f"Offset to align TR1050 end with deployment end: {offset_to_align_ends:.0f}s"
    f"  ({offset_to_align_ends/3600:.2f} hours)"
)

if sbe_instruments:
    offset_tr_sbe_start = (sbe_start - tr1050_start_raw).total_seconds()
    print(
        f"Time from TR1050 raw start to SBE37 start:      {offset_tr_sbe_start:.0f}s"
        f"  ({offset_tr_sbe_start/3600:.2f} hours)"
    )

print()
print("=== Summary ===")
print(
    f"clock_offset = {configured_offset}  →  deployment coverage"
    f" {100 * min(overlap_seconds, deploy_duration) / deploy_duration:.0f}%"
    if tr1050_corrected_start <= deployment_end
    and tr1050_corrected_end >= deployment_start
    else f"clock_offset = {configured_offset}  →  NO deployment coverage"
)
