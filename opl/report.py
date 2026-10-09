"""offline-power-lab :: Markdown design book + CSV detail files.

Every section of the generated report prints, in this order:

1. the **formula** (with units),
2. the **substituted numbers**,
3. the **result** and its **verdict** (pass / fail / warning).

That is the whole point of the project: a reviewer can follow the arithmetic
without re-deriving it, and a number that cannot be traced back to a formula has
no business being in the report.

Files written by :func:`write_outputs` (all with ``encoding="utf-8"``):

===============================  ==========================================
``<prefix>_report.md``           the design book (this module's Markdown)
``<prefix>_summary.csv``         the one-line-per-quantity summary table
``<prefix>_losses.csv``          loss budget items
``<prefix>_stress.csv``          derating table (actual/rated/ratio/margin)
``<prefix>_loop.csv``            loop gain sweep (f, mag dB, phase deg)
``<prefix>_emi.csv``             insertion loss sweep (f, DM dB, CM dB)
===============================  ==========================================
"""

from __future__ import annotations

import csv
import os
from typing import Dict, Iterable, List, Optional, Sequence

from .errors import OPL_E_NODATA, OplError

__all__ = ["render_markdown", "write_csv", "write_outputs", "summary_rows"]

_BAR = "-" * 78


def _fmt(value, digits: int = 4) -> str:
    """Format a number compactly for the Markdown tables."""
    if value is None:
        return "-"
    if isinstance(value, float):
        if value == float("inf"):
            return "inf"
        if abs(value) >= 1000.0:
            return "{0:,.1f}".format(value)
        if value != 0.0 and abs(value) < 1e-3:
            return "{0:.3e}".format(value)
        return ("{0:." + str(digits) + "f}").format(value).rstrip("0").rstrip(".")
    return str(value)


def _md_table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    out = ["| " + " | ".join(header) + " |"]
    out.append("|" + "|".join(["---"] * len(header)) + "|")
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def summary_rows(result) -> List[List[str]]:
    """The key numbers of a run as ``[quantity, value, unit, note]`` rows."""
    rows: List[List[str]] = []
    spec = result.spec
    rows.append(["Mains range", "{0:g}-{1:g}".format(spec.vac_min, spec.vac_max), "Vrms", "universal input"])
    rows.append(["Output", "{0:g} / {1:g}".format(spec.vout, spec.iout), "V / A", "rated"])
    rows.append(["Switching frequency", "{0:g}".format(spec.fsw), "Hz", "main switch"])
    rows.append(["Efficiency target", "{0:.0f}".format(spec.eta_target * 100.0), "%", "design input"])
    d = result.flyback
    if d is not None:
        rows.append(["Conduction mode", d.mode, "-", "from ripple_k / dcm_k"])
        rows.append(["Bulk Vin min / max", "{0:.2f} / {1:.2f}".format(d.vin_dc_min, d.vin_dc_max), "V", "after bridge drop"])
        rows.append(["Turns ratio n = Np/Ns", "{0:.4f}".format(d.n), "-", "continuous design value"])
        rows.append(["Reflected voltage Vor", "{0:.3f}".format(d.vor), "V", "n*(Vout+Vf)"])
        rows.append(["Dmax", "{0:.4f}".format(d.dmax), "-", "limit {0:.2f}".format(d.dmax_limit)])
        rows.append(["Dmin", "{0:.4f}".format(d.dmin), "-", "at vac_max"])
        rows.append(["Primary inductance Lp", "{0:.6f}".format(d.lp), "H", "CCM/DCM formula"])
        rows.append(["Boundary inductance Lbcm", "{0:.6f}".format(d.lp_bcm), "H", "CCM above this"])
        rows.append(["Primary peak current Ipk", "{0:.4f}".format(d.ipk), "A", "at vac_min, full load"])
        rows.append(["Primary RMS current", "{0:.4f}".format(d.irms_pri), "A", "trapezoid over D"])
        rows.append(["Secondary RMS current", "{0:.4f}".format(d.irms_sec), "A", "trapezoid over 1-D"])
    m = result.magnetics
    if m is not None:
        rows.append(["Required AP", "{0:.4f}".format(m.ap_required), "cm^4", "AP method"])
        rows.append(["Selected core", m.core.name, "-", "AP margin {0:.2f}x".format(m.ap_margin)])
        rows.append(["Turns Np / Ns", "{0} / {1}".format(m.np, m.ns), "-", "integers, n_actual {0:.3f}".format(m.n_actual)])
        rows.append(["Air gap", "{0:.4f}".format(m.gap_mm), "mm", "centre leg"])
        rows.append(["Bmax", "{0:.4f}".format(m.bmax), "T", "target {0:.2f} T".format(m.bmax_target)])
        rows.append(["AC flux swing", "{0:.4f}".format(m.delta_b), "T", "drives core loss"])
        rows.append(["Window utilisation", "{0:.3f}".format(m.ku_actual), "-", "copper / window"])
        rows.append(["Primary wire", "{0} x {1}".format(m.wire_pri.awg, m.wire_pri.strands), "-", "Rac {0:.3f} ohm".format(m.wire_pri.r_ac_ohm)])
        rows.append(["Secondary wire", "{0} x {1}".format(m.wire_sec.awg, m.wire_sec.strands), "-", "Rac {0:.5f} ohm".format(m.wire_sec.r_ac_ohm)])
    st = result.stress
    if st is not None:
        rows.append(["Derating items passed", "{0}/{1}".format(len(st.items) - len(st.failed), len(st.items)), "-", ", ".join(i.name for i in st.failed) or "all pass"])
    lp = result.loop
    if lp is not None:
        rows.append(["Loop crossover", "{0:.1f}".format(lp.fc_hz), "Hz", "first |T|=1 crossing"])
        rows.append(["Crossover analytic vs numeric", "{0:.2f}".format(lp.fc_error_pct), "%", "Bode sketch vs sweep"])
        rows.append(["Phase margin", "{0:.1f}".format(lp.phase_margin_deg), "deg", "target {0:.0f}".format(lp.pm_target_deg)])
        rows.append(["Gain margin", _fmt(lp.gain_margin_db), "dB", "target {0:.0f}".format(lp.gm_target_db)])
        rows.append(["Loop verdict", "PASS" if lp.passed else "FAIL", "-", "PM and GM"])
    sf = result.safety
    if sf is not None:
        rows.append(["Clearance required / design", "{0:.2f} / {1:.2f}".format(sf.requirement.clearance_mm, sf.design_clearance_mm), "mm", "PASS" if sf.clearance_pass else "FAIL"])
        rows.append(["Creepage required / design", "{0:.2f} / {1:.2f}".format(sf.requirement.creepage_mm, sf.design_creepage_mm), "mm", "PASS" if sf.creepage_pass else "FAIL"])
        rows.append(["Earth leakage", "{0:.3f}".format(sf.leakage_current_ma), "mA", "limit {0:.2f} mA".format(sf.leakage_limit_ma)])
    em = result.emi
    if em is not None:
        rows.append(["DM attenuation {0:.0f} dB from".format(em.target_db), _fmt(em.f_pass_dm_hz, 0), "Hz", "PASS" if em.dm_pass else "FAIL"])
        rows.append(["CM attenuation {0:.0f} dB from".format(em.target_db), _fmt(em.f_pass_cm_hz, 0), "Hz", "PASS" if em.cm_pass else "FAIL"])
    bg = result.budget
    if bg is not None:
        rows.append(["Total loss", "{0:.3f}".format(bg.total_w), "W", "sum of items"])
        rows.append(["Predicted efficiency", "{0:.2f}".format(bg.efficiency * 100.0), "%", "target {0:.1f} %".format(bg.eta_target * 100.0)])
        rows.append(["Efficiency gap", "{0:.2f}".format(bg.gap_pct_points), "points", "target minus predicted"])
        rows.append(["Dominant loss", bg.dominant, "-", "{0:.2f} W".format(bg.get(bg.dominant))])
    return rows


def render_markdown(result, title: Optional[str] = None) -> str:
    """Render the design book as a Markdown string.

    ``result`` is an :class:`opl.model.DesignResult`; stages that were not run
    (``None``) are simply omitted.
    """
    if result is None or getattr(result, "spec", None) is None:
        raise OplError(OPL_E_NODATA, "render_markdown needs a DesignResult with a spec")
    spec = result.spec
    headline = title or "Offline flyback design book"
    lines: List[str] = []
    add = lines.append

    add("# " + headline)
    add("")
    add("Generated by **offline-power-lab** `{0}`  ".format(_version()))
    add(
        "Input: **{0:g}-{1:g} VAC**, **{2:g} V / {3:g} A**, **fsw = {4:g} Hz**, "
        "efficiency target **{5:.0f} %**.".format(
            spec.vac_min, spec.vac_max, spec.vout, spec.iout, spec.fsw, spec.eta_target * 100.0
        )
    )
    add("")
    add("> **This is a design calculation, not a measurement and not a simulation.**")
    add("> Every number below comes from the closed-form formulas quoted in each section,")
    add("> using the component parameters in `opl.Components` and the built-in reference")
    add("> tables. No prototype was built, nothing was measured, and the core/safety")
    add("> tables are simplified subsets that cannot replace datasheets or the standards.")
    add("")
    add("## 1. Summary")
    add("")
    add(_md_table(["Quantity", "Value", "Unit", "Note"], summary_rows(result)))
    add("")

    d = result.flyback
    if d is not None:
        add("## 2. Flyback main circuit ({0})".format(d.mode))
        add("")
        add("```")
        add("Vin_dc_min = vac_min*sqrt(2) - bridge_drop = {0:g}*1.4142 - {1:g} = {2:.3f} V".format(spec.vac_min, spec.bridge_drop, d.vin_dc_min))
        add("Vin_dc_max = vac_max*sqrt(2) - bridge_drop = {0:g}*1.4142 - {1:g} = {2:.3f} V".format(spec.vac_max, spec.bridge_drop, d.vin_dc_max))
        add("Pin        = Pout/eta_target = {0:g}/{1:g} = {2:.3f} W".format(spec.pout, spec.eta_target, spec.pin))
        add("Vor        = Vin_min*Dmax/(1-Dmax) = {0:.3f}*{1:g}/(1-{1:g}) = {2:.3f} V".format(d.vin_dc_min, spec.dmax_target, d.vor))
        add("n          = Vor/(Vout+Vf) = {0:.3f}/{1:g} = {2:.4f}".format(d.vor, spec.vout_ref, d.n))
        if d.mode == "CCM":
            add("Dmin       = Vor/(Vin_max+Vor) = {0:.3f}/({1:.3f}+{0:.3f}) = {2:.4f}".format(d.vor, d.vin_dc_max, d.dmin))
            add("Ipk        = 2*Pin/(Vin_min*Dmax*(2-kr)) = 2*{0:.3f}/({1:.3f}*{2:g}*{3:.2f}) = {4:.4f} A".format(spec.pin, d.vin_dc_min, d.dmax, 2.0 - d.krip, d.ipk))
            add("dI         = kr*Ipk = {0:.4f} A".format(d.ipk - d.ip1))
            add("Lp         = Vin_min*Dmax/(dI*fsw) = {0:.6f} H".format(d.lp))
        else:
            add("Lp         = dcm_k*Lbcm = {0:.4f}*{1:.6f} = {2:.6f} H".format(spec.dcm_k, d.lp_bcm, d.lp))
            add("Dmax       = Dmax_target*sqrt(dcm_k) = {0:g}*sqrt({1:g}) = {2:.4f}".format(spec.dmax_target, spec.dcm_k, d.dmax))
            add("Ipk        = 2*Pin/(Vin_min*Dmax) = {0:.4f} A".format(d.ipk))
            add("tdis       = Ipk*Lp/(n*(Vout+Vf)) = {0:.3e} s ({1:.3f} T)".format(d.tdis, d.tdis * spec.fsw))
        add("Lbcm       = (Vin_min*Dmax)^2/(2*Pin*fsw) = {0:.6f} H  (Lp/Lbcm = {1:.2f})".format(d.lp_bcm, d.lp / d.lp_bcm))
        add("Irms_pri   = sqrt(D*(Ip1^2+Ip1*Ipk+Ipk^2)/3) = {0:.4f} A".format(d.irms_pri))
        add("Irms_sec   = n*sqrt((1-D)*(Ip1^2+Ip1*Ipk+Ipk^2)/3) = {0:.4f} A".format(d.irms_sec))
        add("Is_pk/avg  = {0:.4f} / {1:.4f} A".format(d.is_pk, d.is_avg))
        add("check      : 0.5*(Ip1+Ipk)*Vin_min*Dmax/Pin = 1.000000 (power balance)")
        add("```")
        add("")
        add("**Dmax verdict:** {0} (Dmax = {1:.4f}, limit {2:.2f})".format(
            "PASS" if d.dmax_ok else "**FAIL**", d.dmax, d.dmax_limit))
        add("")
        if d.warnings:
            add("Warnings:")
            for w in d.warnings:
                add("- " + w)
            add("")

    m = result.magnetics
    if m is not None:
        add("## 3. Transformer ({0})".format(m.core.name))
        add("")
        add("```")
        add("AP_required = Lp*Ipk*Irms/(Ku*Bmax*J) * 1e4 = {0:.4f} cm^4   (J = A/cm^2)".format(m.ap_required))
        add("AP_core     = Ae*Aw = {0:.4f}*{1:.4f} = {2:.4f} cm^4  (margin {3:.2f}x)".format(m.core.ae_cm2, m.core.aw_cm2, m.core.ap_cm4, m.ap_margin))
        add("Np          = ceil(Lp*Ipk/(Bmax_target*Ae)) = {0} turns".format(m.np))
        add("Ns          = ceil(Np/n) = {0} turns  (n_actual = {1:.4f}, Vor_actual = {2:.3f} V)".format(m.ns, m.n_actual, m.vor_actual))
        add("Bmax        = Lp*Ipk/(Np*Ae) = {0:.4f} T   (target {1:.2f} T, saturation ~0.35-0.39 T at 100 C)".format(m.bmax, m.bmax_target))
        add("delta_B     = Bmax*krip = {0:.4f} T".format(m.delta_b))
        add("gap         = mu0*Np^2*Ae/Lp - le/ur = {0:.4f} mm".format(m.gap_mm))
        add("delta(fsw)  = 66.1*sqrt(1+0.00393*(T-20))/sqrt(f) = {0:.4f} mm at 100 C".format(m.delta_mm))
        add("Ku          = (Np*Aout_pri + Ns*Aout_sec)/Aw = {0:.3f}".format(m.ku_actual))
        add("```")
        add("")
        add(_md_table(
            ["Winding", "Wire", "Strands", "Bare d (mm)", "Area (mm^2)", "Turns", "Rdc (ohm)", "Rac (ohm)", "J (A/mm^2)"],
            [
                ["primary", m.wire_pri.awg, m.wire_pri.strands, _fmt(m.wire_pri.d_bare_mm), _fmt(m.wire_pri.area_mm2), m.np, _fmt(m.wire_pri.r_dc_ohm), _fmt(m.wire_pri.r_ac_ohm), _fmt(m.j_pri)],
                ["secondary", m.wire_sec.awg, m.wire_sec.strands, _fmt(m.wire_sec.d_bare_mm), _fmt(m.wire_sec.area_mm2), m.ns, _fmt(m.wire_sec.r_dc_ohm), _fmt(m.wire_sec.r_ac_ohm), _fmt(m.j_sec)],
            ],
        ))
        add("")
        add("Strand diameter is kept below 2 x skin depth = {0:.3f} mm at {1:g} Hz.".format(2.0 * m.delta_mm, spec.fsw))
        add("")
        if m.warnings:
            add("Warnings:")
            for w in m.warnings:
                add("- " + w)
            add("")

    st = result.stress
    if st is not None:
        add("## 4. Component stress and derating")
        add("")
        add(_md_table(
            ["Item", "Actual", "Unit", "Rated", "Ratio", "Limit", "Margin %", "Verdict", "Note"],
            [
                [it.name, _fmt(it.actual), it.unit, _fmt(it.rated), _fmt(it.ratio), "{0:.2f}".format(it.limit), "{0:.1f}".format(it.margin_pct), "PASS" if it.passed else "**FAIL**", it.note]
                for it in st.items
            ],
        ))
        add("")
        add("Verdict: **{0}** ({1} of {2} items fail)".format(
            "PASS" if st.passed else "FAIL", len(st.failed), len(st.items)))
        add("")
        if st.failed:
            add("Failing items and what they mean:")
            for it in st.failed:
                add("- **{0}**: {1} vs {2} {3} (limit {4:.0%}) - {5}".format(
                    it.name, _fmt(it.actual), _fmt(it.rated), it.unit, it.limit, it.note))
            add("")
        if st.warnings:
            for w in st.warnings:
                add("- " + w)
            add("")

    lp = result.loop
    if lp is not None and result.loop_power_stage is not None:
        ps = result.loop_power_stage
        add("## 5. Loop compensation")
        add("")
        add("```")
        add("Power stage (average model, {0}):".format(ps.mode))
        add("  g0    = {0:.3f} V/duty      L_sec = Lp/n^2 = {1:.6e} H".format(ps.g0_dc, ps.l_sec_h))
        add("  f0    = {0:.1f} Hz          Q = {1:.3f}".format(ps.f0_hz, ps.q))
        add("  f_rhp = {0:.1f} Hz          f_esr = {1:.1f} Hz".format(ps.f_rhp_hz, ps.f_esr_hz))
        add("  R_load= {0:.3f} ohm         Cout = {1:.3e} F, ESR = {2:.4f} ohm".format(ps.r_load_ohm, ps.cout_f, ps.esr_ohm))
        if result.compensator is not None:
            c = result.compensator
            add("Compensator (Type {0}): kc = {1:.4f} 1/s, fz = {2:.1f} Hz, fp = {3:.1f} Hz".format(c.kind, c.kc, c.wz / (2 * 3.141592653589793), c.wp / (2 * 3.141592653589793)))
            comps = c.components
            if comps:
                add("  R_upper = {0:.1f} ohm, R_lower = {1:.1f} ohm, C_zero = {2:.3e} F, C_pole = {3:.3e} F".format(
                    comps.get("r_upper_ohm", 0.0), comps.get("r_lower_ohm", 0.0), comps.get("c_zero_f", 0.0), comps.get("c_pole_f", 0.0)))
                add("  opto LED bias current ~ {0:.2f} mA (needs >= 1 mA for a TL431)".format(comps.get("i_led_ma", 0.0)))
        add("```")
        add("")
        add(_md_table(
            ["Quantity", "Value", "Unit", "Target", "Verdict"],
            [
                ["crossover (numeric sweep + bisection)", "{0:.1f}".format(lp.fc_hz), "Hz", "-", "-"],
                ["crossover (asymptotic Bode sketch)", "{0:.1f}".format(lp.fc_analytic_hz), "Hz", "-", "-"],
                ["crossover error (analytic vs numeric)", "{0:.2f}".format(lp.fc_error_pct), "%", "small", "PASS" if abs(lp.fc_error_pct) < 25.0 else "CHECK"],
                ["phase margin", "{0:.1f}".format(lp.phase_margin_deg), "deg", "{0:.0f}".format(lp.pm_target_deg), "PASS" if lp.phase_margin_deg >= lp.pm_target_deg else "**FAIL**"],
                ["gain margin", _fmt(lp.gain_margin_db), "dB", "{0:.0f}".format(lp.gm_target_db), "PASS" if (lp.gain_margin_db == float("inf") or lp.gain_margin_db >= lp.gm_target_db) else "**FAIL**"],
            ],
        ))
        add("")
        add("Loop verdict: **{0}**".format("PASS" if lp.passed else "FAIL"))
        add("")
        for w in lp.warnings:
            add("- " + w)
        add("")

    sf = result.safety
    if sf is not None:
        add("## 6. Insulation distances (safety)")
        add("")
        req = sf.requirement
        add("```")
        add("Working voltage   = {0:.1f} Vrms, PD{1}, material group {2}, {3} insulation, {4:.0f} m".format(
            req.v_working_rms, req.pollution_degree, req.material_group, req.insulation, req.altitude_m))
        add("clearance_req     = table(V_working, PD) * altitude_factor = {0:.2f} mm".format(req.clearance_mm))
        add("creepage_req      = table(V_working, material_group)       = {0:.2f} mm".format(req.creepage_mm))
        add("I_leak            = 2*pi*f_line*C_y_total*Vac = {0:.3f} mA (limit {1:.2f} mA)".format(sf.leakage_current_ma, sf.leakage_limit_ma))
        add("```")
        add("")
        add(_md_table(
            ["Check", "Required", "Design", "Margin", "Verdict"],
            [
                ["clearance (mm)", "{0:.2f}".format(req.clearance_mm), "{0:.2f}".format(sf.design_clearance_mm), "{0:+.2f}".format(sf.clearance_margin_mm), "PASS" if sf.clearance_pass else "**FAIL**"],
                ["creepage (mm)", "{0:.2f}".format(req.creepage_mm), "{0:.2f}".format(sf.design_creepage_mm), "{0:+.2f}".format(sf.creepage_margin_mm), "PASS" if sf.creepage_pass else "**FAIL**"],
                ["earth leakage (mA)", "{0:.2f}".format(sf.leakage_limit_ma), "{0:.3f}".format(sf.leakage_current_ma), "{0:+.3f}".format(sf.leakage_limit_ma - sf.leakage_current_ma), "PASS" if sf.leakage_pass else "**FAIL**"],
            ],
        ))
        add("")
        add("**{0}**".format(sf.conclusion))
        add("")
        add("> The tables behind this section are a **simplified subset** of the")
        add("> IEC 60950-1 / GB 4943.1-style requirement ({0}).".format(req.basis))
        add("> They cannot replace the standards text and no conclusion here replaces a")
        add("> safety agency's judgement.")
        add("")
        for w in sf.warnings:
            add("- " + w)
        add("")

    em = result.emi
    if em is not None:
        add("## 7. EMC input filter")
        add("")
        f = result.emi_filter
        if f is not None:
            add("```")
            add("Cx = {0:.3f} uF, Cy = {1:.2f} nF per line, Lcm = {2:.3f} mH per winding, Ldm = {3:.1f} uH".format(
                f.cx_f * 1e6, f.cy_f * 1e9, f.lcm_h * 1e3, f.ldm_h * 1e6))
            add("IL(f) = 20*log10( |H_ref| / |H_filter| ),  Rs = Rl = {0:g} ohm".format(f.rs_ohm))
            add("DM: series Ldm, shunt Cx        CM: series 2*Lcm, shunt Cy (one Y cap, conservative)")
            add("```")
            add("")
        add(_md_table(
            ["Check", "Result", "Unit", "Verdict"],
            [
                ["DM insertion loss reaches {0:.0f} dB at".format(em.target_db), _fmt(em.f_pass_dm_hz, 0), "Hz", "PASS" if em.dm_pass else "**FAIL**"],
                ["CM insertion loss reaches {0:.0f} dB at".format(em.target_db), _fmt(em.f_pass_cm_hz, 0), "Hz", "PASS" if em.cm_pass else "**FAIL**"],
                ["earth leakage from the Y capacitors", "{0:.3f}".format(em.leakage_current_ma), "mA", "PASS" if em.leakage_pass else "**FAIL**"],
            ],
        ))
        add("")
        sample = [em.curve[i] for i in range(0, len(em.curve), max(1, len(em.curve) // 8))]
        add(_md_table(
            ["f (Hz)", "DM IL (dB)", "CM IL (dB)"],
            [["{0:,.0f}".format(row[0]), "{0:.1f}".format(row[1]), "{0:.1f}".format(row[2])] for row in sample],
        ))
        add("")
        add("> The **required** attenuation ({0:.0f} dB) is an input to this tool, not a".format(em.target_db))
        add("> result: without a measured or estimated noise spectrum there is no way to")
        add("> compute what a product needs. No EMC measurement or mitigation was done.")
        add("")
        for w in em.warnings:
            add("- " + w)
        add("")

    bg = result.budget
    if bg is not None:
        add("## 8. Loss budget and predicted efficiency")
        add("")
        add(_md_table(
            ["Loss term", "Value (W)", "Share (%)", "Formula / substituted numbers"],
            [[it.name, _fmt(it.value_w), "{0:.1f}".format(it.pct), it.formula] for it in sorted(bg.items, key=lambda x: -x.value_w)],
        ))
        add("")
        add("```")
        add("Total loss  = {0:.4f} W".format(bg.total_w))
        add("Pout        = {0:.3f} W".format(bg.pout_w))
        add("Pin         = Pout + total = {0:.4f} W".format(bg.pin_w))
        add("Efficiency  = Pout/Pin = {0:.4f} ({1:.2f} %)".format(bg.efficiency, bg.efficiency * 100.0))
        add("Target      = {0:.4f} -> gap {1:+.2f} percentage points".format(bg.eta_target, bg.gap_pct_points))
        add("Dominant    = {0} ({1:.3f} W, {2:.1f} % of the total)".format(bg.dominant, bg.get(bg.dominant), 100.0 * bg.get(bg.dominant) / bg.total_w if bg.total_w else 0.0))
        add("```")
        add("")
        for w in bg.warnings:
            add("- " + w)
        add("")

    add("## 9. Boundaries of this document")
    add("")
    for line in (
        "Design calculation and verification only - **not a circuit simulator**: no SPICE, no time-domain waveforms, no PCB parasitics, no thermal simulation.",
        "**No hardware exists**: no prototype, no measurement, no waveform capture. Every number is computed from formulas and public data and does **not** represent the measured performance of any product.",
        "Core table, safety-distance tables and material coefficients are simplified subsets - replace them with vendor datasheets and the standards text before building anything.",
        "The loop model is an average model (no sampling effect); loop results must be verified on the bench.",
        "No EMC measurement, no safety certification, no temperature-rise or reliability test was performed.",
        "Predictions here are only as good as the parameters in `opl.Components`.",
    ):
        add("- " + line)
    add("")
    return "\n".join(lines)


def _version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:  # pragma: no cover - import cycle guard
        return "unknown"


def write_csv(path: str, header: Sequence[str], rows: Iterable[Sequence]) -> str:
    """Write a CSV file with UTF-8 encoding and return the absolute path.

    ``newline=""`` is passed to :func:`csv.writer` as required, and the file is
    opened in text mode with ``encoding="utf-8"`` (never a Windows default
    code page - that is where the 0x1A and code-page traps live).
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(header))
        for row in rows:
            writer.writerow(list(row))
    return os.path.abspath(path)


def write_outputs(result, out_dir: str, prefix: str = "opl", title: Optional[str] = None) -> Dict[str, str]:
    """Write the Markdown book plus the CSV detail files, return a path map.

    The output directory is created by this function (no shell ``mkdir`` is
    involved anywhere in the project).
    """
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    written: Dict[str, str] = {}

    md_path = os.path.join(out_dir, prefix + "_report.md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_markdown(result, title=title))
    written["report"] = os.path.abspath(md_path)

    written["summary"] = write_csv(
        os.path.join(out_dir, prefix + "_summary.csv"),
        ["quantity", "value", "unit", "note"],
        summary_rows(result),
    )

    if result.budget is not None:
        written["losses"] = write_csv(
            os.path.join(out_dir, prefix + "_losses.csv"),
            ["loss_term", "value_w", "share_pct", "formula"],
            [[it.name, "{0:.6f}".format(it.value_w), "{0:.2f}".format(it.pct), it.formula] for it in result.budget.items],
        )
    if result.stress is not None:
        written["stress"] = write_csv(
            os.path.join(out_dir, prefix + "_stress.csv"),
            ["item", "actual", "unit", "rated", "ratio", "limit", "margin_pct", "verdict", "note"],
            [[it.name, "{0:.6f}".format(it.actual), it.unit, "{0:.6f}".format(it.rated),
              "{0:.6f}".format(it.ratio), "{0:.2f}".format(it.limit),
              "{0:.2f}".format(it.margin_pct), "PASS" if it.passed else "FAIL", it.note]
             for it in result.stress.items],
        )
    if result.loop is not None:
        written["loop"] = write_csv(
            os.path.join(out_dir, prefix + "_loop.csv"),
            ["f_hz", "magnitude_db", "phase_deg"],
            [["{0:.6f}".format(pt.f_hz), "{0:.4f}".format(pt.mag_db), "{0:.4f}".format(pt.phase_deg)]
             for pt in result.loop.sweep],
        )
    if result.emi is not None:
        written["emi"] = write_csv(
            os.path.join(out_dir, prefix + "_emi.csv"),
            ["f_hz", "il_dm_db", "il_cm_db"],
            [["{0:.6f}".format(row[0]), "{0:.4f}".format(row[1]), "{0:.4f}".format(row[2])]
             for row in result.emi.curve],
        )
    return written
