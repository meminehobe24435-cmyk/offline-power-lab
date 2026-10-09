"""offline-power-lab :: test runner.

Usage::

    python test/test_all.py

Runs every check module, prints one line per module, then the total::

    <N> checks passed

Exit code 0 when everything passed, 1 otherwise.  No third-party test
dependency: this is plain Python 3.8+.
"""

from __future__ import annotations

import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for path in (_ROOT, _HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

from oplcheck import Checker  # noqa: E402

# Modules are imported lazily by name so that a partially built checkout still
# runs the modules that do exist (the Makefile/CI always runs the full list).
MODULES = (
    "test_core",
    "test_loop",
    "test_safety_emi",
    "test_budget_report",
    "test_edge",
)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    only = [a for a in argv if not a.startswith("-")]
    names = [m for m in MODULES if (not only or any(m.endswith(o) for o in only))]

    total = Checker("offline-power-lab")
    ran = 0
    for name in names:
        try:
            module = __import__(name)
        except ImportError as exc:
            print("SKIP {0} (not importable: {1})".format(name, exc))
            continue
        chk = Checker(name)
        ran += 1
        try:
            module.run(chk)
        except Exception:  # noqa: BLE001 - a crashing module is a failure, not a skip
            chk.failed += 1
            print("FAIL {0} raised:".format(name))
            traceback.print_exc()
        chk.summary()
        total.merge(chk)

    print("")
    if ran == 0:
        print("no test modules were found")
        return 1
    print("{0} checks passed".format(total.passed))
    if total.failed:
        print("{0} checks FAILED".format(total.failed))
        for line in total.failures:
            print("  " + line)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
