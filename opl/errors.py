"""offline-power-lab :: error codes, exceptions and input validation helpers.

Every public function in this package raises :class:`OplError` (or a subclass)
with a stable machine-readable ``code``.  The codes are part of the public API,
so tests and downstream tooling may assert on them.

Error code table
----------------
======================  ==========================================================
code                    meaning
======================  ==========================================================
``OPL-E-INPUT``         a scalar argument is out of its legal domain
                        (negative resistance, zero frequency, eta > 1, ...)
``OPL-E-RANGE``         the *requested operating point* is legal per-argument but
                        outside the validity range of the model in use
                        (e.g. a windings ratio that forces Dmax > 1)
``OPL-E-TABLE``         a look-up table has no entry for the requested key
                        (mains voltage above the tabulated band, unknown
                        material group, unknown pollution degree, ...)
``OPL-E-NOCORE``        no core in the built-in core table satisfies the required
                        area product / Bmax / window utilisation
``OPL-E-UNSAT``         the design constraints cannot be satisfied simultaneously
                        (e.g. the requested phase-margin target cannot be met by
                        a Type-II network over the allowed crossover window)
``OPL-E-NODATA``        a required upstream result is missing from the pipeline
                        bundle, or the caller hits a deliberately unimplemented
                        code path
======================  ==========================================================

All messages are ASCII-only English so that they survive a Windows console with
a non-UTF-8 code page.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

__all__ = [
    "OPL_E_INPUT",
    "OPL_E_RANGE",
    "OPL_E_TABLE",
    "OPL_E_NOCORE",
    "OPL_E_UNSAT",
    "OPL_E_NODATA",
    "ERROR_CODES",
    "OplError",
    "require",
    "check_number",
    "check_choice",
]

OPL_E_INPUT = "OPL-E-INPUT"
OPL_E_RANGE = "OPL-E-RANGE"
OPL_E_TABLE = "OPL-E-TABLE"
OPL_E_NOCORE = "OPL-E-NOCORE"
OPL_E_UNSAT = "OPL-E-UNSAT"
OPL_E_NODATA = "OPL-E-NODATA"

ERROR_CODES = (
    OPL_E_INPUT,
    OPL_E_RANGE,
    OPL_E_TABLE,
    OPL_E_NOCORE,
    OPL_E_UNSAT,
    OPL_E_NODATA,
)


class OplError(Exception):
    """Base exception for every recoverable failure in offline-power-lab.

    Parameters
    ----------
    code:
        one of the ``OPL_E_*`` constants.
    message:
        short human readable description (ASCII).
    hint:
        optional actionable hint printed after the message, e.g.
        "increase dmax_target or lower vor_target".
    """

    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.hint:
            return "[{0}] {1} (hint: {2})".format(self.code, self.message, self.hint)
        return "[{0}] {1}".format(self.code, self.message)


def require(condition: bool, code: str, message: str, hint: str = "") -> None:
    """Raise :class:`OplError` unless ``condition`` is truthy.

    Used everywhere instead of bare ``assert`` so that the checks survive
    ``python -O`` and so that every failure carries a stable code.
    """
    if not condition:
        raise OplError(code, message, hint)


def check_number(
    name: str,
    value: Any,
    lo: Optional[float] = None,
    hi: Optional[float] = None,
    unit: str = "",
    lo_inclusive: bool = True,
    hi_inclusive: bool = True,
) -> float:
    """Validate a scalar input and return it as ``float``.

    ``lo``/``hi`` are inclusive by default.  Non-finite input is always
    rejected.  ``unit`` is only used to build the error message.
    """
    try:
        val = float(value)
    except (TypeError, ValueError):
        raise OplError(
            OPL_E_INPUT,
            "{0} must be a real number, got {1!r}".format(name, value),
        )
    if val != val or val in (float("inf"), float("-inf")):
        raise OplError(OPL_E_INPUT, "{0} must be finite, got {1!r}".format(name, value))
    suffix = " [{0}]".format(unit) if unit else ""
    if lo is not None:
        bad = val < lo if lo_inclusive else val <= lo
        if bad:
            raise OplError(
                OPL_E_INPUT,
                "{0}={1:g}{2} below minimum {3:g}".format(name, val, suffix, lo),
            )
    if hi is not None:
        bad = val > hi if hi_inclusive else val >= hi
        if bad:
            raise OplError(
                OPL_E_INPUT,
                "{0}={1:g}{2} above maximum {3:g}".format(name, val, suffix, hi),
            )
    return val


def check_choice(name: str, value: Any, choices: Iterable[str]) -> str:
    """Validate that ``value`` is one of ``choices`` (case-insensitive)."""
    opts = tuple(choices)
    if not isinstance(value, str):
        raise OplError(OPL_E_INPUT, "{0} must be a string, got {1!r}".format(name, value))
    up = value.strip().upper()
    for opt in opts:
        if opt.upper() == up:
            return opt
    raise OplError(
        OPL_E_INPUT,
        "{0}={1!r} not in {2}".format(name, value, list(opts)),
    )
