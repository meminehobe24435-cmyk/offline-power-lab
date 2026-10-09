"""PLACEHOLDER - implemented in a later step (see opl/__init__.py for the API)."""

from __future__ import annotations

from .errors import OPL_E_NODATA, OplError

__all__ = [
    "CLEARANCE_TABLE",
    "CREEPAGE_TABLE",
    "ALTITUDE_FACTORS",
    "STANDARD_LEAKAGE_LIMITS_MA",
    "lookup_clearance",
    "lookup_creepage",
    "leakage_current_ma",
    "check_safety",
]

CLEARANCE_TABLE = ()
CREEPAGE_TABLE = ()
ALTITUDE_FACTORS = ()
STANDARD_LEAKAGE_LIMITS_MA = {}

_MSG = "opl.safety is not implemented in this build stage"


def _nyi(*args, **kwargs):
    raise OplError(OPL_E_NODATA, _MSG)


lookup_clearance = _nyi
lookup_creepage = _nyi
leakage_current_ma = _nyi
check_safety = _nyi
