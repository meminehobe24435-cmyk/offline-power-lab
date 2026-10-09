"""offline-power-lab :: tiny dependency-free check helper.

No pytest, no unittest - just a counter and readable failure output, so the
suite runs with a bare ``python test/test_all.py`` on Python 3.8+ and returns a
non-zero exit code when anything fails.
"""

from __future__ import annotations

import math
import os
import sys
import traceback


def _caller() -> str:
    """``file:line`` of the code that called into the checker."""
    for frame in reversed(traceback.extract_stack()[:-2]):
        if os.path.basename(frame.filename) not in ("oplcheck.py",):
            return "{0}:{1}".format(os.path.basename(frame.filename), frame.lineno)
    return "?"


class Checker:
    """Counts assertions and prints every failure with its source line."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.passed = 0
        self.failed = 0
        self.failures = []

    # -- assertions --------------------------------------------------------

    def ok(self, cond, msg: str) -> bool:
        """Assert that ``cond`` is truthy."""
        if cond:
            self.passed += 1
            return True
        self.failed += 1
        text = "[{0}] {1}".format(self.name, msg)
        self.failures.append(text)
        print("FAIL {0}  <-- {1}".format(text, _caller()))
        return False

    def true(self, cond, msg: str) -> bool:
        return self.ok(bool(cond), msg)

    def false(self, cond, msg: str) -> bool:
        return self.ok(not cond, msg)

    def eq(self, got, want, msg: str) -> bool:
        return self.ok(
            got == want, "{0}: got {1!r}, want {2!r}".format(msg, got, want)
        )

    def close(self, got, want, rel: float = 1e-9, msg: str = "", abs_tol: float = 0.0) -> bool:
        """Assert ``|got - want| <= max(abs_tol, rel*|want|)``."""
        try:
            diff = abs(float(got) - float(want))
        except (TypeError, ValueError):
            return self.ok(False, "{0}: non-numeric got={1!r} want={2!r}".format(msg, got, want))
        tol = max(abs_tol, rel * abs(float(want)))
        return self.ok(
            diff <= tol,
            "{0}: got {1!r}, want {2!r} (diff {3:.3e} > tol {4:.3e})".format(
                msg, got, want, diff, tol
            ),
        )

    def between(self, got, lo, hi, msg: str) -> bool:
        try:
            val = float(got)
        except (TypeError, ValueError):
            return self.ok(False, "{0}: non-numeric {1!r}".format(msg, got))
        return self.ok(lo <= val <= hi, "{0}: {1!r} not in [{2!r}, {3!r}]".format(msg, got, lo, hi))

    def raises(self, code, func, *args, **kwargs) -> bool:
        """Assert that ``func(*args)`` raises :class:`OplError` with ``code``."""
        from opl import OplError

        label = kwargs.pop("_msg", None) or getattr(func, "__name__", "call")
        try:
            func(*args, **kwargs)
        except OplError as exc:
            return self.ok(
                exc.code == code,
                "{0}: raised {1} instead of {2} ({3})".format(label, exc.code, code, exc),
            )
        except Exception as exc:  # noqa: BLE001 - we want the failure detail
            return self.ok(
                False, "{0}: raised {1}: {2}".format(label, type(exc).__name__, exc)
            )
        return self.ok(False, "{0}: no exception, expected {1}".format(label, code))

    # -- reporting ---------------------------------------------------------

    def merge(self, other: "Checker") -> None:
        """Fold another checker's counts in (used by the aggregating runner)."""
        self.passed += other.passed
        self.failed += other.failed
        self.failures.extend(other.failures)

    def summary(self) -> int:
        total = self.passed + self.failed
        print(
            "{0}: {1}/{2} checks passed{3}".format(
                self.name or "checks",
                self.passed,
                total,
                "" if self.failed == 0 else "  ({0} FAILED)".format(self.failed),
            )
        )
        return 0 if self.failed == 0 else 1
