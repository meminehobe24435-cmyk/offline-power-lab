"""offline-power-lab :: command line interface.

    python main.py {design,stress,loop,safety,emi,budget,all} [options] [--out DIR]

Exit codes
----------
====  =====================================================================
0     every requested check passed
1     at least one requested check failed (see the FAIL lines)
2     command line usage error (argparse)
3     an :class:`opl.OplError` was raised (bad input or an unsatisfiable design)
====  =====================================================================

The printed sheet is the same information as the Markdown design book; with
``--out DIR`` the full report plus the CSV detail files are written there
(created by Python, with ``encoding="utf-8"``).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .errors import OplError
from .model import Components, DesignSpec, EmiFilter
from .pipeline import ALL_STAGES, EXAMPLE_SPECS, default_components, run_spec
from .report import _fmt, write_outputs

__all__ = ["main", "build_parser", "spec_from_args", "verdict_of"]

STAGE_CHOICES = ("design", "stress", "loop", "safety", "emi", "budget", "all")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (public so tests can assert on the options)."""
    p = argparse.ArgumentParser(
        prog="offline-power-lab",
        description=(
            "Offline (mains input) AC-DC flyback design and verification tool: main "
            "circuit, transformer, stress/derating, loop compensation, safety "
            "distances, EMC filter, loss budget.  Design calculations and checks - "
            "NOT a circuit simulator, and no hardware was built or measured."
        ),
        epilog="Example: python main.py all --vout 5 --iout 3 --out results",
    )
    p.add_argument("command", choices=STAGE_CHOICES, help="which stage(s) to run")
    p.add_argument("--example", choices=sorted(EXAMPLE_SPECS), default=None,
                   help="load a built-in example specification instead of the defaults")
    p.add_argument("--vac-min", type=float, default=None, help="minimum mains RMS voltage [Vrms]")
    p.add_argument("--vac-max", type=float, default=None, help="maximum mains RMS voltage [Vrms]")
    p.add_argument("--vout", type=float, default=None, help="output voltage [V]")
    p.add_argument("--iout", type=float, default=None, help="output current [A]")
    p.add_argument("--fsw", type=float, default=None, help="switching frequency [Hz]")
    p.add_argument("--eta", type=float, default=None, help="target efficiency [0..1]")
    p.add_argument("--line-freq", type=float, default=None, help="mains frequency [Hz] (50/60)")
    p.add_argument("--vf-sec", type=float, default=None, help="secondary rectifier drop [V]")
    p.add_argument("--bridge-drop", type=float, default=None, help="input rectifier drop [V]")
    p.add_argument("--mode", choices=("CCM", "DCM", "AUTO"), default=None, help="conduction mode")
    p.add_argument("--dmax", type=float, default=None, help="Dmax design target [0..1]")
    p.add_argument("--dmax-limit", type=float, default=None, help="hard Dmax limit [0..1]")
    p.add_argument("--ripple-k", type=float, default=None, help="CCM ripple ratio dI/Ipk (0..1]")
    p.add_argument("--dcm-k", type=float, default=None, help="DCM Lp/Lbcm ratio (0..1]")
    p.add_argument("--bmax", type=float, default=0.28, help="flux density target [T]")
    p.add_argument("--j", type=float, default=4.0, help="winding current density [A/mm^2]")
    p.add_argument("--core", default=None, help="force a core from the built-in table (e.g. EE25)")
    p.add_argument("--temp-c", type=float, default=100.0, help="winding/junction temperature [degC]")
    p.add_argument("--fc", type=float, default=None, help="loop crossover target [Hz]")
    p.add_argument("--pm", type=float, default=45.0, help="phase margin target [deg]")
    p.add_argument("--gm", type=float, default=10.0, help="gain margin target [dB]")
    p.add_argument("--cout", type=float, default=None, help="total output capacitance [F]")
    p.add_argument("--cout-esr", type=float, default=None, help="total output capacitor ESR [ohm]")
    p.add_argument("--clearance", type=float, default=6.0, help="design clearance [mm]")
    p.add_argument("--creepage", type=float, default=6.5, help="design creepage [mm]")
    p.add_argument("--insulation", choices=("basic", "reinforced", "functional"), default="reinforced",
                   help="insulation type for the distance look-up")
    p.add_argument("--material-group", choices=("I", "II", "IIIa", "IIIb"), default="IIIa",
                   help="CTI material group")
    p.add_argument("--altitude", type=float, default=2000.0, help="operating altitude [m]")
    p.add_argument("--cx", type=float, default=None, help="X capacitance [F]")
    p.add_argument("--cy", type=float, default=None, help="Y capacitance per line [F]")
    p.add_argument("--lcm", type=float, default=None, help="common-mode inductance per winding [H]")
    p.add_argument("--ldm", type=float, default=None, help="differential-mode inductance [H]")
    p.add_argument("--emi-target", type=float, default=40.0, help="required insertion loss [dB]")
    p.add_argument("--out", default=None, help="output directory for the report and CSVs")
    p.add_argument("--quiet", action="store_true", help="print only the verdict lines")
    return p


def spec_from_args(args) -> DesignSpec:
    """Build a :class:`DesignSpec` from parsed arguments (``--example`` first)."""
    if args.example:
        base = EXAMPLE_SPECS[args.example]
        values = dict(
            vac_min=base.vac_min, vac_max=base.vac_max, vout=base.vout, iout=base.iout,
            fsw=base.fsw, eta_target=base.eta_target, line_freq=base.line_freq,
            bridge_drop=base.bridge_drop, vf_sec=base.vf_sec, dmax_limit=base.dmax_limit,
            dmax_target=base.dmax_target, mode=base.mode, ripple_k=base.ripple_k,
            dcm_k=base.dcm_k,
        )
    else:
        values = dict(
            vac_min=90.0, vac_max=264.0, vout=5.0, iout=3.0, fsw=65.0e3, eta_target=0.80,
            line_freq=50.0, bridge_drop=1.4, vf_sec=0.50, dmax_limit=0.50, dmax_target=0.45,
            mode="CCM", ripple_k=0.40, dcm_k=0.60,
        )
    overrides = {
        "vac_min": args.vac_min, "vac_max": args.vac_max, "vout": args.vout, "iout": args.iout,
        "fsw": args.fsw, "eta_target": args.eta, "line_freq": args.line_freq,
        "vf_sec": args.vf_sec, "bridge_drop": args.bridge_drop, "mode": args.mode,
        "dmax_target": args.dmax, "dmax_limit": args.dmax_limit, "ripple_k": args.ripple_k,
        "dcm_k": args.dcm_k,
    }
    for key, value in overrides.items():
        if value is not None:
            values[key] = value
    return DesignSpec(**values)


def _components_from_args(args) -> Components:
    comp = default_components()
    if args.cout is not None:
        comp.cout_cap_f = args.cout
    if args.cout_esr is not None:
        comp.cout_esr = args.cout_esr
    return comp


def _filter_from_args(args) -> EmiFilter:
    filt = EmiFilter()
    if args.cx is not None:
        filt.cx_f = args.cx
    if args.cy is not None:
        filt.cy_f = args.cy
    if args.lcm is not None:
        filt.lcm_h = args.lcm
    if args.ldm is not None:
        filt.ldm_h = args.ldm
    return filt


def verdict_of(result, stages: List[str]) -> List[str]:
    """Names of the requested checks that failed (empty list = all pass)."""
    failed: List[str] = []
    if result.flyback is not None and not result.flyback.dmax_ok:
        failed.append("design.Dmax")
    if "stress" in stages and result.stress is not None and not result.stress.passed:
        failed.extend("stress." + it.name for it in result.stress.failed)
    if "loop" in stages and result.loop is not None and not result.loop.passed:
        failed.append("loop.margins")
    if "safety" in stages and result.safety is not None and not result.safety.passed:
        failed.append("safety.distances")
    if "emi" in stages and result.emi is not None and not result.emi.passed:
        failed.append("emi.attenuation")
    if "budget" in stages and result.budget is not None:
        if result.budget.efficiency < result.budget.eta_target:
            failed.append("budget.efficiency")
    return failed


def _print_text(result, stages: List[str], stream) -> None:
    w = stream.write
    spec = result.spec
    w("=" * 78 + "\n")
    w("offline-power-lab - offline flyback design sheet\n")
    w("input: {0:g}-{1:g} VAC -> {2:g} V / {3:g} A, fsw {4:g} Hz, eta target {5:.0f} %\n".format(
        spec.vac_min, spec.vac_max, spec.vout, spec.iout, spec.fsw, spec.eta_target * 100.0))
    w("NOTE: design calculation only - not a simulator, and nothing was measured.\n")
    w("=" * 78 + "\n")

    d = result.flyback
    if d is not None:
        w("[design] {0}: n={1:.4f} Vor={2:.2f} V Dmax={3:.4f} (limit {4:.2f}, {5}) "
          "Dmin={6:.4f}\n".format(d.mode, d.n, d.vor, d.dmax, d.dmax_limit,
                                  "OK" if d.dmax_ok else "OVER", d.dmin))
        w("         Lp={0:.6f} H (Lbcm {1:.6f}) Ipk={2:.4f} A Irms_pri={3:.4f} A "
          "Irms_sec={4:.4f} A\n".format(d.lp, d.lp_bcm, d.ipk, d.irms_pri, d.irms_sec))
    m = result.magnetics
    if m is not None:
        w("[magnet] core={0} AP={1:.4f}/{2:.4f} cm^4 ({3:.2f}x) Np/Ns={4}/{5} gap={6:.4f} mm "
          "Bmax={7:.4f} T Ku={8:.3f}\n".format(
              m.core.name, m.core.ap_cm4, m.ap_required, m.ap_margin, m.np, m.ns, m.gap_mm,
              m.bmax, m.ku_actual))
    st = result.stress
    if st is not None:
        w("-" * 78 + "\n")
        w("{0:<16}{1:>12}{2:>8}{3:>12}{4:>9}{5:>10}  {6}\n".format(
            "derating item", "actual", "unit", "rated", "ratio", "margin%", "verdict"))
        for it in st.items:
            w("{0:<16}{1:>12.3f}{2:>8}{3:>12.3f}{4:>9.3f}{5:>10.1f}  {6}\n".format(
                it.name, it.actual, it.unit, it.rated, it.ratio, it.margin_pct,
                "PASS" if it.passed else "FAIL"))
        w("         {0}/{1} derating items pass\n".format(len(st.items) - len(st.failed), len(st.items)))
    lp = result.loop
    if lp is not None:
        w("-" * 78 + "\n")
        w("[loop]   fc={0:.1f} Hz (analytic {1:.1f} Hz, error {2:.2f} %) PM={3:.1f} deg "
          "GM={4} dB -> {5}\n".format(lp.fc_hz, lp.fc_analytic_hz, lp.fc_error_pct,
                                      lp.phase_margin_deg, _fmt(lp.gain_margin_db),
                                      "PASS" if lp.passed else "FAIL"))
    sf = result.safety
    if sf is not None:
        w("[safety] clearance {0:.2f}/{1:.2f} mm creepage {2:.2f}/{3:.2f} mm leak {4:.3f} mA "
          "-> {5}\n".format(sf.requirement.clearance_mm, sf.design_clearance_mm,
                            sf.requirement.creepage_mm, sf.design_creepage_mm,
                            sf.leakage_current_ma, "PASS" if sf.passed else "FAIL"))
    em = result.emi
    if em is not None:
        w("[emi]    DM {0:.0f} dB from {1} Hz, CM {2:.0f} dB from {3} Hz -> {4}\n".format(
            em.target_db, _fmt(em.f_pass_dm_hz, 0), em.target_db, _fmt(em.f_pass_cm_hz, 0),
            "PASS" if em.passed else "FAIL"))
    bg = result.budget
    if bg is not None:
        w("[budget] total loss {0:.3f} W, efficiency {1:.2f} % (target {2:.1f} %, gap {3:+.2f} pts), "
          "dominant {4} ({5:.3f} W)\n".format(bg.total_w, bg.efficiency * 100.0,
                                              bg.eta_target * 100.0, bg.gap_pct_points,
                                              bg.dominant, bg.get(bg.dominant)))
    failed = verdict_of(result, stages)
    w("=" * 78 + "\n")
    w("VERDICT: {0}\n".format("ALL REQUESTED CHECKS PASS" if not failed else "FAIL -> " + ", ".join(failed)))
    if not failed:
        w("reminder: no hardware exists, no measurement was made, and the safety tables are a\n"
          "          simplified subset - verify on the bench and against the standards.\n")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.  Returns the process exit code (see the module docstring)."""
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    stages = list(ALL_STAGES) if args.command == "all" else [args.command]
    try:
        spec = spec_from_args(args)
        result = run_spec(
            spec,
            comp=_components_from_args(args),
            stages=stages,
            bmax_target=args.bmax,
            j_a_per_mm2=args.j,
            core_name=args.core,
            temp_c=args.temp_c,
            fc_target_hz=args.fc,
            pm_target_deg=args.pm,
            gm_target_db=args.gm,
            design_clearance_mm=args.clearance,
            design_creepage_mm=args.creepage,
            insulation=args.insulation,
            material_group=args.material_group,
            altitude_m=args.altitude,
            emi_filter=_filter_from_args(args),
            emi_target_db=args.emi_target,
        )
        if args.out:
            written = write_outputs(result, args.out, prefix="opl")
            for name, path in sorted(written.items()):
                sys.stderr.write("wrote {0}: {1}\n".format(name, path))
    except OplError as exc:
        sys.stderr.write("error: {0}\n".format(exc))
        return 3

    _print_text(result, stages, sys.stdout)
    if args.quiet:
        for line in result.warnings:
            sys.stderr.write("warning: {0}\n".format(line))
    return 1 if verdict_of(result, stages) else 0
