"""Package-level configuration constants for caldip.

Holds caldip-specific defaults that are *not* shared with seasenselib. The
root-level :mod:`caldip.parameters` is a copy of ``seasenselib/parameters.py``
(canonical variable-name mappings) and is off-limits for local constants;
anything caldip owns — such as bottle-stop detection thresholds — lives here
instead, mirroring ``ctdcast/config/parameters.py`` and
``oceanarray/config/parameters.py``.
"""
