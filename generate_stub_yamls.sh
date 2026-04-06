#!/bin/bash

# Generate stub YAML configuration files for all caldip directories
# Copy and paste these commands to generate stub YAML files

echo "Generating stub YAML files for all available caldip directories..."

# castM4 (example - add more cast directories as needed)
python generate_stub_yaml.py data/proc_calib/msm142_2026/cal_dip/castM4/

echo "All stub YAML files generated"