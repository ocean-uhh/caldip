
# Generate caldip plots and statistics for all available cast configurations
# Copy and paste these commands to generate all outputs

echo "Generating all available caldip plots and statistics..."

# castM3
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM3/ --output outputs/castM3_plot.html --title "castM3: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM3/ --output outputs/castM3_detailed_statistics.csv --output-dir outputs --ctd-sensor 2

# castM4
python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM4/ --output outputs/castM4_plot.html --title "castM4: Instruments vs CTD"
python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM4/ --output outputs/castM4_detailed_statistics.csv --output-dir outputs --ctd-sensor 2

# castM5
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM5/ --output outputs/castM6_plot.html --title "castM5: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM5/ --output outputs/castM5_detailed_statistics.csv --output-dir outputs --ctd-sensor 2

# castM6
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM6/ --output outputs/castM6_plot.html --title "castM6: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM6/ --output outputs/castM6_detailed_statistics.csv --output-dir outputs --ctd-sensor 2

# castM7
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM7/ --output outputs/castM7_plot.html --title "castM7: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM7/ --output outputs/castM7_detailed_statistics.csv --output-dir outputs --ctd-sensor 2


# castM8
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM8/ --output outputs/castM8_plot.html --title "castM8: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM8/ --output outputs/castM8_detailed_statistics.csv --output-dir outputs --ctd-sensor 2
echo "All plots and statistics generated in outputs/ directory"