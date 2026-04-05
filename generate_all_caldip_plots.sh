
# Generate caldip plots and statistics for all available cast configurations
# Copy and paste these commands to generate all outputs

echo "Generating all available caldip plots and statistics..."

# castM4
python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM4/ --output outputs/castM4_plot.html --title "castM4: Instruments vs CTD"
python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM4/ --output outputs/castM4_detailed_statistics.csv --output-dir outputs --ctd-sensor 2

echo "All plots and statistics generated in outputs/ directory"