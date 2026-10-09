"""PLACEHOLDER - implemented in a later step (see opl/__init__.py for the API)."""

from __future__ import annotations

from .errors import OPL_E_NODATA, OplError

__all__ = ["insertion_loss_lc", "insertion_loss_dm", "insertion_loss_cm", "emi_report"]

_MSG = "opl.emi is not implemented in this build stage"


def _nyi(*args, **kwargs):
    raise OplError(OPL_E_NODATA, _MSG)


insertion_loss_lc = _nyi
insertion_loss_dm = _nyi
insertion_loss_cm = _nyi
emi_report = _nyi
