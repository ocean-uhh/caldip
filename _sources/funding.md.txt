# Acknowledgments

The calibration dip approach in caldip — attaching mooring instruments to a CTD rosette and comparing their measurements against the CTD during brief stationary periods — is based on methods used by the [RAPID 26°N array](http://rapid.ac.uk) mooring calibration programme, where calibration dips are performed at the start and end of each mooring deployment.
The RAPID code was written in MATLAB and relied on known bottle stop times from the CTD bottle file.
caldip reimplements this comparison approach in Python and adds automatic bottle stop detection from the pressure record, support for variable stop durations, and a wider range of instrument types (SBE37 MicroCATs and RBR thermistors).

# Funding

caldip was initiated during cruise MSM142 as part of the AEI-DFG project **MIXSED**.

MIXSED is jointly funded by the Agencia Estatal de Investigación (AEI) through the PCI 2024 call (projects PCI2024-155022-2 and PCI2024-155084-2) and the Deutsche Forschungsgemeinschaft (DFG, German Research Foundation) – Projektnummer 541914507.
