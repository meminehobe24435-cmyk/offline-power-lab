"""offline-power-lab :: smallest useful CLI (design + stress).

STAGE NOTE: this file is intentionally small in the current build stage.  The
:mod:`opl.pipeline` and :mod:`opl.report` modules are being filled in next; the
sub-commands ``loop`` / ``safety`` / ``emi`` / ``budget`` / ``all`` report that
they are unavailable until those modules land.  ``design`` and ``stress`` are
fully functional and print a plain-text verification sheet to stdout.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .errors import OplError
from .flyback import design_flyback
from .magnetics import design_magnetics
from .model import Components, DesignSpec
from .stress import evaluate_stress

__all__ = ["main", "build_parser", "DEFAULT_SPEC_KWARGS"]

DEFAULT_SPEC_KWARGS = dict(
    vac_min=90.0,
    vac_max=264.0,
    vout=5.0,
    iout=3.0,
    fsw=65.0e3,
    eta_target=0.80,
)

STAGES = ("design", "stress", "loop", "safety", "emi", "budget", "all")
_AVAILABLE = ("design", "stress")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (public so tests can assert on the options)."""
    p = argparse.ArgumentParser(
        prog="offline-power-lab",
        description=(
            "Offline (mains input) AC-DC flyback design and verification tool. "
            "Design calculations and checks - NOT a circuit simulator."
        ),
    )
    p.add_argument("command", choices=STAGES, help="which design/check stage to run")
    p.add_argument("--vac-min", type=float, default=90.0, help="minimum mains RMS voltage [Vrms]")
    p.add_argument("--vac-max", type=float, default=264.0, help="maximum mains RMS voltage [Vrms]")
    p.add_argument("--vout", type=float, default=5.0, help="output voltage [V]")
    p.add_argument("--iout", type=float, default=3.0, help="output current [A]")
    p.add_argument("--fsw", type=float, default=65.0e3, help="switching frequency [Hz]")
    p.add_argument("--eta", type=float, default=0.80, help="target efficiency [0..1]")
    p.add_argument("--line-freq", type=float, default=50.0, help="mains frequency [Hz]")
    p.add_argument("--mode", choices=("CCM", "DCM", "AUTO"), default="CCM", help="conduction mode")
    p.add_argument("--dmax", type=float, default=0.45, help="Dmax design target [0..1]")
    p.add_argument("--dmax-limit", type=float, default=0.50, help="hard Dmax limit [0..1]")
    p.add_argument("--ripple-k", type=float, default=0.40, help="CCM ripple ratio dI/Ipk")
    p.add_argument("--dcm-k", type=float, default=0.60, help="DCM Lp/Lbcm ratio")
    p.add_argument("--bmax", type=float, default=0.28, help="flux density target [T]")
    p.add_argument("--j", type=float, default=4.0, help="current density [A/mm^2]")
    p.add_argument("--core", default=None, help="force a core from the built-in table (e.g. EE25)")
    p.add_argument("--out", default=None, help="output directory for the report and CSVs")
    p.add_argument("--quiet", action="store_true", help="only print the verdict lines")
    return p


def spec_from_args(args) -> DesignSpec:
    """Build a :class:`DesignSpec` from parsed CLI arguments."""
    return DesignSpec(
        vac_min=args.vac_min,
        vac_max=args.vac_max,
        vout=args.vout,
        iout=args.iout,
        fsw=args.fsw,
        eta_target=args.eta,
        line_freq=args.line_freq,
        mode=args.mode,
        dmax_limit=args.dmax_limit,
        dmax_target=args.dmax,
        ripple_k=args.ripple_k,
        dcm_k=args.dcm_k,
    )


def _print_design(design, mag, stream) -> None:
    w = stream.write
    w("=" * 78 + "\n")
    w("FLYBACK MAIN CIRCUIT - {0:.1f}-{1:.1f} VAC -> {2:g} V / {3:g} A, fsw={4:g} Hz\n".format(
        design.spec.vac_min, design.spec.vac_max, design.spec.vout, design.spec.iout,
        design.spec.fsw))
    w("=" * 78 + "\n")
    w("mode                 : {0}\n".format(design.mode))
    w("bulk Vin min/max     : {0:.2f} / {1:.2f} V\n".format(design.vin_dc_min, design.vin_dc_max))
    w("turns ratio n=Np/Ns  : {0:.4f}\n".format(design.n))
    w("reflected voltage Vor: {0:.3f} V\n".format(design.vor))
    w("Dmax / Dmin          : {0:.4f} / {1:.4f}  (limit {2:.2f})  {3}\n".format(
        design.dmax, design.dmin, design.dmax_limit, "OK" if design.dmax_ok else "OVER LIMIT"))
    w("primary inductance   : {0:.6f} H  (boundary {1:.6f} H)\n".format(design.lp, design.lp_bcm))
    w("primary peak / start : {0:.4f} / {1:.4f} A\n".format(design.ipk, design.ip1))
    w("RMS primary/secondary: {0:.4f} / {1:.4f} A\n".format(design.irms_pri, design.irms_sec))
    w("secondary peak / avg : {0:.4f} / {1:.4f} A\n".format(design.is_pk, design.is_avg))
    for line in design.warnings:
        w("WARNING: {0}\n".format(line))
    if mag is not None:
        w("-" * 78 + "\n")
        w("core                 : {0} (AP {1:.4f} cm^4 vs required {2:.4f}, margin {3:.2f}x)\n".format(
            mag.core.name, mag.core.ap_cm4, mag.ap_required, mag.ap_margin))
        w("turns Np/Ns          : {0} / {1}  (n_actual {2:.4f})\n".format(
            mag.np, mag.ns, mag.n_actual))
        w("air gap              : {0:.4f} mm\n".format(mag.gap_mm))
        w("Bmax / delta_B       : {0:.4f} / {1:.4f} T (target {2:.2f} T)\n".format(
            mag.bmax, mag.delta_b, mag.bmax_target))
        w("wire primary         : {0} x {1:.3f} mm, Rdc {2:.3f} ohm\n".format(
            mag.wire_pri.awg, mag.wire_pri.d_bare_mm, mag.wire_pri.r_dc_ohm))
        w("wire secondary       : {0} x {1} strands, Rdc {2:.4f} ohm\n".format(
            mag.wire_sec.awg, mag.wire_sec.strands, mag.wire_sec.r_dc_ohm))
        w("window utilisation   : {0:.3f}\n".format(mag.ku_actual))
        for line in mag.warnings:
            w("WARNING: {0}\n".format(line))


def _print_stress(rep, stream) -> None:
    w = stream.write
    w("-" * 78 + "\n")
    w("{0:<16}{1:>12}{2:>10}{3:>12}{4:>9}{5:>9}  {6}\n".format(
        "item", "actual", "unit", "rated", "ratio", "margin%", "verdict"))
    for it in rep.items:
        w("{0:<16}{1:>12.3f}{2:>10}{3:>12.3f}{4:>9.3f}{5:>9.1f}  {6}\n".format(
            it.name, it.actual, it.unit, it.rated, it.ratio, it.margin_pct,
            "PASS" if it.passed else "FAIL"))
    w("{0} item(s) failed derating\n".format(len(rep.failed)))
    for line in rep.warnings:
        w("WARNING: {0}\n".format(line))


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.  Returns a process exit code (0 = all checks pass)."""
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command not in _AVAILABLE and args.command != "all":
        sys.stderr.write(
            "{0}: not available in this build stage; available: {1}\n".format(
                args.command, ", ".join(_AVAILABLE)
            )
        )
        return 3

    try:
        spec = spec_from_args(args)
        design = design_flyback(spec)
        mag = design_magnetics(design, bmax_target=args.bmax, j_a_per_mm2=args.j,
                               core_name=args.core)
        comp = Components()
        rep = evaluate_stress(design, comp, mag)
    except OplError as exc:
        sys.stderr.write("error: {0}\n".format(exc))
        return 3

    out = sys.stdout
    _print_design(design, mag, out)
    _print_stress(rep, out)
    if args.out:
        sys.stderr.write(
            "note: --out is wired up once opl.report lands (this build prints to stdout)\n"
        )
    return 0 if rep.passed and design.dmax_ok else 1
