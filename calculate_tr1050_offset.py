#!/usr/bin/env python3
"""
Calculate correct clock offset for TR1050 instruments
"""

import pandas as pd

# Deployment period
deployment_start = pd.to_datetime("2026-04-03T03:05:36")
deployment_end = pd.to_datetime("2026-04-03T05:08:24")

# TR1050 data after current 7175s offset (example from 015581)
tr1050_start_with_7175 = pd.to_datetime("2026-02-04 18:37:21")
tr1050_end_with_7175 = pd.to_datetime("2026-03-04 05:47:21")

# SBE37 reference data (correct timing)
sbe_start = pd.to_datetime("2026-04-03 03:45:01")
sbe_end = pd.to_datetime("2026-04-03 05:32:11")

print("=== TR1050 Clock Offset Analysis ===")
print(f"Deployment period:     {deployment_start} to {deployment_end}")
print(f"TR1050 (with +7175s):  {tr1050_start_with_7175} to {tr1050_end_with_7175}")
print(f"SBE37 (correct):       {sbe_start} to {sbe_end}")
print()

# Calculate the additional offset needed
additional_offset_needed = (deployment_start - tr1050_start_with_7175).total_seconds()
total_offset_needed = 7175 + additional_offset_needed

print(f"Current offset:        +7175 seconds ({7175/86400:.1f} days)")
print(
    f"Additional needed:     +{additional_offset_needed:.0f} seconds ({additional_offset_needed/86400:.1f} days)"
)
print(
    f"Total offset needed:   +{total_offset_needed:.0f} seconds ({total_offset_needed/86400:.1f} days)"
)
print()

# Verify this aligns TR1050 with deployment period
tr1050_corrected_start = tr1050_start_with_7175 + pd.Timedelta(
    seconds=additional_offset_needed
)
tr1050_corrected_end = tr1050_end_with_7175 + pd.Timedelta(
    seconds=additional_offset_needed
)

print("=== Verification ===")
print(f"TR1050 with total offset: {tr1050_corrected_start} to {tr1050_corrected_end}")
print(f"Deployment period:        {deployment_start} to {deployment_end}")
print()

if (
    tr1050_corrected_start <= deployment_end
    and tr1050_corrected_end >= deployment_start
):
    print("✅ TR1050 data will overlap with deployment period!")

    # Check if corrected time aligns well with SBE data
    time_diff_start = abs((tr1050_corrected_start - sbe_start).total_seconds())
    time_diff_end = abs((tr1050_corrected_end - sbe_end).total_seconds())
    print("Time alignment with SBE37:")
    print(f"  Start difference: {time_diff_start:.0f} seconds")
    print(f"  End difference:   {time_diff_end:.0f} seconds")
else:
    print("❌ TR1050 data still won't overlap with deployment period")

print()
print("=== Recommended YAML Update ===")
print(
    f"Change clock_offset from 7175 to {total_offset_needed:.0f} for all TR1050 instruments"
)

# Check the specific pattern the user mentioned
days_30_plus_7175 = 30 * 86400 + 7175
print(
    f"\nUser's hypothesis (30 days + 7175): {days_30_plus_7175} seconds ({days_30_plus_7175/86400:.1f} days)"
)
print(
    f"Our calculated total:                 {total_offset_needed:.0f} seconds ({total_offset_needed/86400:.1f} days)"
)
print(
    f"Difference: {abs(total_offset_needed - days_30_plus_7175):.0f} seconds ({abs(total_offset_needed - days_30_plus_7175)/86400:.1f} days)"
)
