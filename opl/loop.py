"""PLACEHOLDER - implemented in a later step (see opl/__init__.py for the API)."""

from __future__ import annotations

from .errors import OPL_E_NODATA, OplError

__all__ = [
    "power_stage_model",
    "power_stage_response",
    "compensator_response",
    "loop_response",
    "design_compensator",
    "type2_components",
    "sweep_response",
    "analytic_crossover",
    "numeric_crossover",
    "analyze_loop",
]

_MSG = "opl.loop is not implemented in this build stage"


def _nyi(*args, **kwargs):
    raise OplError(OPL_E_NODATA, _MSG)


power_stage_model = _nyi
power_stage_response = _nyi
compensator_response = _nyi
loop_response = _nyi
design_compensator = _nyi
type2_components = _nyi
sweep_response = _nyi
analytic_crossover = _nyi
numeric_crossover = _nyi
analyze_loop = _nyi
