"""offline-power-lab :: command line entry point.

Usage::

    python main.py design   [options] [--out DIR]
    python main.py stress   [options] [--out DIR]
    python main.py loop     [options] [--out DIR]
    python main.py safety   [options] [--out DIR]
    python main.py emi      [options] [--out DIR]
    python main.py budget   [options] [--out DIR]
    python main.py all      [options] [--out DIR]

Run ``python main.py --help`` for the option list.  The module keeps the
repository root on ``sys.path`` so the tool works from a fresh clone without
installation.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from opl.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
