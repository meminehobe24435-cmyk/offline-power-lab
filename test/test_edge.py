"""Boundary, degenerate and illegal-input checks across the whole package.

Extreme-but-legal operating points must still produce self-consistent numbers
(power balance closes, Bmax stays under the target, Dmax stays under its limit),
and everything outside the documented domain must raise the documented error
code rather than returning a plausible-looking wrong answer.
"""

from __future__ import annotations

import math

from opl import (
    OPL_E_INPUT,
    OPL_E_NOCORE,
    OPL_E_RANGE,
    OPL_E_TABLE,
    Components,
    DesignSpec,
    EmiFilter,
    analyze_loop,
    bmax_of,
    boundary_inductance,
    check_safety,
    design_compensator,
    design_flyback,
    design_magnetics,
    duty_dcm,
    emi_report,
    evaluate_stress,
    find_core,
    gap_mm_for_lp,
    list_cores,
    loss_budget,
    nearest_awg,
    peak_current_ccm,
    pick_wire,
    power_stage_model,
    primary_rms,
    required_ap,
    secondary_rms,
    select_core,
    skin_depth_mm,
    trapezoid_rms,
    verify_power_balance,
)
from opl.magnetics import AWG_TABLE, CORE_TABLE, ENAMEL_BUILD_FACTOR


def spec(**kw):
    base = dict(vac_min=90.0, vac_max=264.0, vout=5.0, iout=3.0, fsw=65.0e3,
                eta_target=0.80, mode="CCM", ripple_k=0.40)
    base.update(kw)
    return DesignSpec(**base)


def run(chk) -> None:
    # ---- extreme but legal specifications --------------------------------
    cases = [
        ("single input voltage", spec(vac_min=230.0, vac_max=230.0)),
        ("narrow range", spec(vac_min=100.0, vac_max=120.0)),
        ("low line only", spec(vac_min=85.0, vac_max=85.0)),
        ("tiny output", spec(vout=1.2, iout=0.05)),
        ("big output", spec(vout=48.0, iout=2.0, vf_sec=0.6)),
        ("20 kHz switching", spec(fsw=20.0e3)),
        ("500 kHz switching", spec(fsw=500.0e3)),
        ("high efficiency target", spec(eta_target=0.95)),
        ("low efficiency target", spec(eta_target=0.40)),
        ("near-boundary ripple", spec(ripple_k=0.99)),
        ("low ripple", spec(ripple_k=0.05)),
        ("deep DCM", spec(mode="DCM", dcm_k=0.05)),
        ("mild DCM", spec(mode="DCM", dcm_k=0.95)),
        ("AUTO mode", spec(mode="AUTO")),
        ("low Dmax", spec(dmax_target=0.25)),
        ("high Dmax", spec(dmax_target=0.70, dmax_limit=0.75)),
        ("60 Hz line", spec(line_freq=60.0)),
        ("large bridge drop", spec(bridge_drop=3.0)),
    ]
    for label, s in cases:
        d = design_flyback(s)
        chk.close(verify_power_balance(d), 1.0, 1e-9, "power balance closes: " + label)
        chk.true(0.0 < d.dmax < 1.0, "Dmax in range: " + label)
        chk.true(d.lp > 0.0, "positive inductance: " + label)
        chk.true(d.ipk > 0.0, "positive peak current: " + label)
        chk.true(d.irms_pri > 0.0 and d.irms_sec > 0.0, "positive RMS currents: " + label)
        chk.close(d.is_avg * d.vout_ref, s.pin, 1e-9, "ampere-turn identity: " + label)
        if d.mode == "CCM":
            chk.true(d.lp > d.lp_bcm, "CCM above the boundary inductance: " + label)
            chk.close(d.lp / d.lp_bcm, (2.0 - d.krip) / d.krip, 1e-9,
                      "Lp/Lbcm = (2-kr)/kr: " + label)
            chk.close(d.tdis * s.fsw, 1.0 - d.dmax, 1e-9, "CCM off-time: " + label)
        else:
            chk.close(d.ip1, 0.0, 1e-15, "DCM starts at zero: " + label)
            chk.true(d.dmax + d.tdis * s.fsw <= 1.0 + 1e-9, "DCM discharge fits: " + label)
            chk.close(d.lp / d.lp_bcm, s.dcm_k, 1e-9, "DCM Lp = dcm_k*Lbcm: " + label)
        chk.true(d.dmax <= s.dmax_limit + 1e-12, "Dmax within its limit: " + label)

    # magnetics must still be buildable and safe across the same extremes
    for label, s in cases[:10]:
        d = design_flyback(s)
        m = design_magnetics(d, bmax_target=0.28, j_a_per_mm2=4.0)
        chk.true(m.bmax <= 0.28 * (1 + 1e-9), "Bmax under target: " + label)
        chk.true(m.gap_mm >= 0.0, "gap not negative: " + label)
        chk.true(m.ku_actual <= 0.65 + 1e-12, "winding fits: " + label)
        chk.true(m.ns >= 1 and m.np >= m.ns, "turns sane: " + label)
        chk.true(m.core.ap_cm4 >= m.ap_required, "AP requirement met: " + label)
        chk.true(0.0 < m.delta_b <= m.bmax, "flux swing bounded: " + label)

    # ---- boundary formulas ----------------------------------------------
    chk.close(trapezoid_rms(0.0, 0.0, 0.5), 0.0, 1e-15, "zero current gives zero RMS")
    chk.close(primary_rms(1.0, 0.0, 1.0), 1.0, 1e-12, "flat current over the whole period")
    chk.close(primary_rms(1.0, 1.0, 1.0), (1.0 / 3.0) ** 0.5, 1e-12, "triangle over the whole period")
    chk.raises(OPL_E_INPUT, secondary_rms, 1.0, 0.0, 0.0, 10.0, _msg="zero off-time is rejected")
    chk.close(secondary_rms(1.0, 0.0, 1e-9, 10.0), 10.0 * math.sqrt(1e-9), 1e-9,
              "tiny off-time gives a tiny RMS")
    chk.close(required_ap(1e-3, 1.0, 0.5, 0.25, 1.0, 4.0), 0.05, 1e-9, "Ku=1 halves the AP again")
    chk.close(gap_mm_for_lp(1e-3, 1, 1.0, 10.0, 2000.0), 0.0, 1e-12, "one turn needs no gap")
    chk.close(bmax_of(1e-3, 1.0, 100000, 1.0), 1e-4, 1e-9, "many turns give a tiny Bmax")
    chk.eq(select_core(0.0).name, "EE13", "zero AP selects the smallest core")
    chk.close(find_core("  ee16  ").ae_cm2, 0.201, 1e-12, "lookup tolerates whitespace")
    chk.eq(len(list_cores()), len(CORE_TABLE), "core list matches the table")
    chk.eq(AWG_TABLE[0][0], "AWG16", "AWG table starts at AWG16")
    chk.eq(AWG_TABLE[-1][0], "AWG40", "AWG table ends at AWG40")
    chk.true(all(AWG_TABLE[i][1] > AWG_TABLE[i + 1][1] for i in range(len(AWG_TABLE) - 1)),
             "AWG diameters strictly decreasing")
    chk.close(nearest_awg(1.29)[1], 1.291, 1e-12, "nearest AWG clamps to the table ends")
    chk.close(nearest_awg(0.001)[1], 0.0799, 1e-12, "very thin wire clamps to AWG40")
    chk.close(pick_wire(0.001, 4.0, 65e3).area_mm2,
              math.pi / 4 * pick_wire(0.001, 4.0, 65e3).d_bare_mm ** 2, 1e-12, "one strand for tiny current")
    w_many = pick_wire(50.0, 4.0, 500e3, 100.0, max_strands=3)
    chk.true(w_many.strands <= 3, "max_strands is respected")
    chk.true(w_many.d_bare_mm <= 2.0 * skin_depth_mm(500e3, 100.0), "strand obeys the skin limit")
    chk.raises(OPL_E_INPUT, pick_wire, 1.0, 4.0, 65e3, _msg="max_strands below 1", max_strands=0)

    # ---- skin depth across frequency ------------------------------------
    chk.close(skin_depth_mm(20e3, 20.0) / skin_depth_mm(80e3, 20.0), 2.0, 1e-9, "delta ~ 1/sqrt(f)")
    chk.true(skin_depth_mm(65e3, 150.0) > skin_depth_mm(65e3, 20.0), "hot copper has a deeper skin")
    chk.true(skin_depth_mm(1e6, 100.0) < 0.1, "skin depth at 1 MHz is under 0.1 mm")
    chk.raises(OPL_E_INPUT, skin_depth_mm, -5.0, _msg="negative frequency")
    chk.raises(OPL_E_INPUT, skin_depth_mm, 65e3, -300.0, _msg="unphysical temperature")

    # ---- illegal inputs, module by module -------------------------------
    chk.raises(OPL_E_INPUT, boundary_inductance, 10.0, 100.0, 1.5, 65e3, _msg="duty > 1")
    chk.raises(OPL_E_INPUT, peak_current_ccm, 10.0, 100.0, 0.5, 2.0, _msg="ripple_k > 1")
    chk.raises(OPL_E_RANGE, duty_dcm, 1e6, 1.0, 65e3, 10.0, _msg="no DCM solution")
    chk.raises(OPL_E_INPUT, trapezoid_rms, 1.0, 1.0, -0.1, _msg="negative duty")
    chk.raises(OPL_E_RANGE, design_flyback, spec(vac_min=1.0, vac_max=2.0),
               _msg="mains barely above the bridge drop has no usable turns ratio")
    chk.raises(OPL_E_RANGE, design_flyback, spec(vac_min=90.0, vac_max=264.0), 1200.0,
               _msg="Vor=1200 V")
    chk.raises(OPL_E_INPUT, design_magnetics, "not a design", _msg="magnetics type check")
    chk.raises(OPL_E_TABLE, design_magnetics, design_flyback(spec()), _msg="unknown core",
               core_name="EE999")
    chk.raises(OPL_E_INPUT, design_magnetics, design_flyback(spec()), _msg="j out of range",
               j_a_per_mm2=0.0)
    chk.raises(OPL_E_INPUT, select_core, -1.0, _msg="negative AP")
    chk.raises(OPL_E_NOCORE, select_core, 1e12, _msg="absurd AP")
    chk.raises(OPL_E_INPUT, bmax_of, -1.0, 1.0, 10, 1.0, _msg="negative inductance")
    chk.raises(OPL_E_INPUT, gap_mm_for_lp, 0.0, 10, 1.0, 10.0, _msg="zero inductance")

    # ---- extreme parts still evaluate -----------------------------------
    d = design_flyback(spec())
    m = design_magnetics(d)
    hot = evaluate_stress(d, Components(), m, temp_c=150.0)
    chk.true(hot.details["mosfet.rds_on_hot"] > Components().mosfet_rds_on * 2.0,
             "hot Rds(on) exceeds twice the 25 C value at 150 C")
    chk.eq(len(hot.items), 10, "derating table size is stable")
    cold = evaluate_stress(d, Components(), m, temp_c=-40.0)
    chk.true(cold.details["mosfet.rds_on_hot"] < Components().mosfet_rds_on,
             "cold Rds(on) is below the 25 C value")
    chk.true(len(cold.items) == len(hot.items), "temperature does not change the table size")

    # a MOSFET with a huge rating passes even the leakage spike
    robust = evaluate_stress(d, Components(mosfet_vds_rated=1200.0), m)
    vds_item = [it for it in robust.items if it.name == "mosfet_vds"][0]
    chk.true(vds_item.passed, "a 1200 V MOSFET passes the Vds derating")
    chk.true(vds_item.margin_pct > 40.0, "with a large margin")

    # ---- losses remain physical at the extremes --------------------------
    for label, s in cases[:6]:
        dd = design_flyback(s)
        mm = design_magnetics(dd)
        bb = loss_budget(dd, Components(), mm)
        chk.true(bb.total_w > 0.0, "positive total loss: " + label)
        chk.true(0.0 < bb.efficiency < 1.0, "efficiency in (0, 1): " + label)
        chk.close(bb.efficiency, bb.pout_w / bb.pin_w, 1e-12, "efficiency definition: " + label)
        chk.close(sum(it.pct for it in bb.items), 100.0, 1e-9, "shares sum to 100 %: " + label)

    # ---- degenerate EMI filters -----------------------------------------
    none = EmiFilter(cx_f=1e-15, cy_f=1e-15, lcm_h=1e-12, ldm_h=1e-12)
    rep_none = emi_report(none, target_db=40.0, n_points=20)
    chk.false(rep_none.dm_pass, "a nominal zero-element filter does not attenuate")
    chk.eq(len(rep_none.curve), 20, "curve respects the resolution argument")
    huge = EmiFilter(cx_f=10e-6, cy_f=4.7e-9, lcm_h=100e-3, ldm_h=1e-3)
    rep_huge = emi_report(huge, target_db=60.0, n_points=20)
    chk.true(rep_huge.f_pass_dm_hz <= rep_huge.f_start_hz * 1.001,
             "a much bigger DM filter meets 60 dB from the band start")
    chk.true(rep_huge.leakage_current_ma > 0.25, "4.7 nF Y caps leak more than 0.25 mA")
    chk.false(rep_huge.leakage_pass, "and therefore fail the class II limit")

    # ---- loop design at the extremes ------------------------------------
    for label, s in (("low line", spec(vac_min=85.0, vac_max=85.0)),
                     ("500 kHz", spec(fsw=500e3))):
        dd = design_flyback(s)
        p = power_stage_model(dd, Components())
        net = design_compensator(p, Components(), design=dd)
        res = analyze_loop(p, net, Components(), design=dd)
        chk.true(res.fc_hz > 0.0 and res.fc_hz != float("inf"), "crossover found: " + label)
        chk.true(-180.0 < res.phase_margin_deg < 180.0, "phase margin in range: " + label)
        chk.true(abs(res.fc_error_pct) < 40.0 or res.fc_error_pct == float("inf"),
                 "analytic crossover plausible: " + label)

    # ---- safety at the table edges --------------------------------------
    chk.close(check_safety(d, 0.6, 0.6, v_working_rms=30.0, insulation="basic",
                           altitude_m=0.0).requirement.clearance_mm, 0.60, 1e-12,
              "very low working voltage")
    edge = check_safety(d, 3.0, 8.0, v_working_rms=1000.0, insulation="reinforced",
                        altitude_m=6000.0)
    chk.close(edge.requirement.clearance_mm, 2.50 * 2.0 * 1.70, 1e-9,
              "1000 Vrms reinforced (2x basic) at 6000 m (x1.70)")
    chk.close(edge.requirement.creepage_mm, 8.0 * 2.0, 1e-9, "1000 Vrms reinforced creepage")
    chk.raises(OPL_E_TABLE, check_safety, d, 6.0, 6.5, _msg="working voltage above the table",
               v_working_rms=1500.0)
