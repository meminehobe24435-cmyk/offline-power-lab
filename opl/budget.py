"""PLACEHOLDER - implemented in a later step (see opl/__init__.py for the API)."""

from __future__ import annotations

from .errors import OPL_E_NODATA, OplError

__all__ = [
    "steinmetz_pv",
    "core_loss_w",
    "copper_loss_w",
    "switch_losses",
    "rectifier_loss_w",
    "loss_budget",
]

_MSG = "opl.budget is not implemented in this build stage"


def _nyi(*args, **kwargs):
    raise OplError(OPL_E_NODATA, _MSG)


steinmetz_pv = _nyi
core_loss_w = _nyi
copper_loss_w = _nyi
switch_losses = _nyi
rectifier_loss_w = _nyi
loss_budget = _nyi
