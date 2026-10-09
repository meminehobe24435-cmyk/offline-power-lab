"""PLACEHOLDER - implemented in a later step (see opl/__init__.py for the API)."""

from __future__ import annotations

from typing import Dict

from .errors import OPL_E_NODATA, OplError
from .model import Components, DesignSpec

__all__ = ["default_components", "EXAMPLE_SPECS", "run_spec"]

EXAMPLE_SPECS: Dict[str, DesignSpec] = {}


def default_components() -> Components:
    """Return the default component set (see :class:`opl.Components`)."""
    return Components()


def run_spec(*args, **kwargs):
    raise OplError(OPL_E_NODATA, "opl.pipeline is not implemented in this build stage")
