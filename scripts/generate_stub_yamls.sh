#!/usr/bin/env bash
# Generate stub YAML configuration files for all caldip directories.
# Requires: pip install -e . (so the `caldip` command is available)

echo "Generating stub YAML files for all available caldip directories..."

# castM4 (example — add more cast directories as needed)
caldip init data/proc_calib/msm142_2026/cal_dip/castM4/

echo "Done."
