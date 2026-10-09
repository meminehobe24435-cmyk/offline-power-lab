"""Reference run: the same 90-264 VAC / 5 V / 3 A design with a part set and an
input filter that satisfy every check.

The default screening part set in `opl.pipeline.default_components()` is aimed at
a 15 W adapter and deliberately trips several derating rules (that is what the
tool is for).  This script shows the *corrected* design so that the README can
quote a passing case as well as a failing one:

    python demo_corrected.py            # prints the summary table
    python demo_corrected.py --out out  # also writes the report and CSVs

Everything printed here is **computed**, not measured - see the README
"Boundaries" section.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from opl import Components, DesignSpec, EmiFilter, render_markdown, run_spec, write_outputs
from opl.report import summary_rows


def corrected_components() -> Components:
    """A 5 V / 3 A class part set that passes every derating rule in the table."""
    comp = Components()
    comp.mosfet_vds_rated = 800.0          # 800 V device: Vds + leakage spike < 80 %
    comp.mosfet_power_rated = 1.50         # W allowed in this thermal design
    comp.clamp_c_f = 4.7e-9                # bigger RCD clamp capacitor -> smaller spike
    comp.rectifier_kind = "sync"           # synchronous rectifier instead of a Schottky
    comp.sr_rds_on = 0.012                 # 12 mohm SR
    comp.sr_vds_rated = 60.0
    comp.diode_power_rated = 1.00
    comp.cin_v_rated = 500.0               # 450 V bulk caps do not meet an 80 % rule at 264 VAC
    comp.cout_cap_f = 940e-6               # 2 x 470 uF
    comp.cout_esr = 0.20                   # realistic total ESR -> Q ~ 1, loop is damped
    comp.cout_ripple_rated = 1.20
    comp.cout_n = 5                        # 5 capacitors in parallel for the ripple current
    return comp


def corrected_filter() -> EmiFilter:
    """Input filter that meets 40 dB from 150 kHz in both DM and CM."""
    filt = EmiFilter()
    filt.cx_f = 1.0e-6                     # 1 uF of X capacitance
    filt.cy_f = 1.0e-9                     # 1 nF per line keeps the earth leakage legal
    filt.lcm_h = 10.0e-3                   # 10 mH CM choke
    filt.ldm_h = 470.0e-6                  # 470 uH of DM inductance
    return filt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="write the report and CSVs here")
    parser.add_argument("--vout", type=float, default=5.0, help="output voltage [V]")
    parser.add_argument("--iout", type=float, default=3.0, help="output current [A]")
    args = parser.parse_args(argv)

    spec = DesignSpec(
        vac_min=90.0, vac_max=264.0, vout=args.vout, iout=args.iout, fsw=65.0e3,
        eta_target=0.80, mode="CCM", ripple_k=0.40,
    )
    result = run_spec(
        spec,
        comp=corrected_components(),
        emi_filter=corrected_filter(),
        design_clearance_mm=6.0,
        design_creepage_mm=6.5,
        insulation="reinforced",
        altitude_m=2000.0,
    )

    width = max(len(row[0]) for row in summary_rows(result))
    print("=" * 78)
    print("offline-power-lab :: corrected reference design (computed, not measured)")
    print("=" * 78)
    for name, value, unit, note in summary_rows(result):
        print("{0:<{w}}  {1:>14} {2:<6} {3}".format(name, value, unit, note, w=width))

    verdicts = []
    if result.stress is not None:
        verdicts.append("derating {0}/{1} pass".format(
            len(result.stress.items) - len(result.stress.failed), len(result.stress.items)))
    if result.loop is not None:
        verdicts.append("loop {0}".format("PASS" if result.loop.passed else "FAIL"))
    if result.safety is not None:
        verdicts.append("safety {0}".format("PASS" if result.safety.passed else "FAIL"))
    if result.emi is not None:
        verdicts.append("emi {0}".format("PASS" if result.emi.passed else "FAIL"))
    if result.budget is not None:
        verdicts.append("efficiency {0:.2f} %".format(result.budget.efficiency * 100.0))
    print("-" * 78)
    print(" | ".join(verdicts))
    for warning in result.warnings:
        print("warning: " + warning)

    if args.out:
        for name, path in sorted(write_outputs(result, args.out, prefix="corrected").items()):
            print("wrote {0}: {1}".format(name, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
