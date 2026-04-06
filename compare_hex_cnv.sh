#!/bin/bash

# Compare SBE37 hex and CNV file data using the comparison script
# This script runs the Python comparison tool for the test data

echo "Comparing SBE37 hex and CNV data..."

python compare_hex_cnv.py data/proc_calib/msm142_2026/cal_dip/castM4/14626_cal_dip_data.hex data/proc_calib/msm142_2026/cal_dip/castM4/14626_cal_dip_data_time.cnv

echo "Comparison complete. Check comparison_plot.html for interactive plot."
