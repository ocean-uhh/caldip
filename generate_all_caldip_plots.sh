
# Generate caldip plots and statistics for all available cast configurations
# Copy and paste these commands to generate all outputs

echo "Generating all available caldip plots and statistics..."

# castM3
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM3/ --output castM3 -o outputs/ --title "castM3: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM3/ --output castM3 -o outputs/ --ctd-sensor 2

# castM4
python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM4/ --output castM4 -o outputs/ --title "castM4: Instruments vs CTD"
python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM4/ --output castM4 -o outputs/ --ctd-sensor 2

# castM5
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM5/ --output castM5 -o outputs/ --title "castM5: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM5/ --output castM5 -o outputs/ --ctd-sensor 2

# castM6
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM6/ --output castM6 -o outputs/ --title "castM6: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM6/ --output castM6 -o outputs/ --ctd-sensor 2

# castM7
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM7/ --output castM7 -o outputs/ --title "castM7: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM7/ --output castM7 -o outputs/ --ctd-sensor 2

# castM8
#python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM8/ --output castM8 -o outputs/ --title "castM8: Instruments vs CTD"
#python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM8/ --output castM8 -o outputs/ --ctd-sensor 2

echo "All plots and statistics generated in outputs/ directory"
