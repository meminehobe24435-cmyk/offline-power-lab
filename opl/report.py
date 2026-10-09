"""PLACEHOLDER - implemented in a later step (see opl/__init__.py for the API)."""

from __future__ import annotations

from .errors import OPL_E_NODATA, OplError

__all__ = ["render_markdown", "write_outputs", "write_csv"]

_MSG = "opl.report is not implemented in this build stage"


def _nyi(*args, **kwargs):
    raise OplError(OPL_E_NODATA, _MSG)


render_markdown = _nyi
write_outputs = _nyi
write_csv = _nyi
