"""Checks for opl.safety and opl.emi - look-up tables, leakage and insertion loss."""

from __future__ import annotations

import math

from opl import (
    OPL_E_INPUT,
    OPL_E_TABLE,
    Components,
    DesignSpec,
    EmiFilter,
    check_safety,
    design_flyback,
    emi_report,
    insertion_loss_cm,
    insertion_loss_dm,
    insertion_loss_lc,
    leakage_current_ma,
    lookup_clearance,
    lookup_creepage,
)
from opl.safety import (
    ALTITUDE_FACTORS,
    CLEARANCE_TABLE,
    CREEPAGE_TABLE,
    STANDARD_LEAKAGE_LIMITS_MA,
    altitude_factor,
)

TWO_PI = 2.0 * math.pi


def spec(**kw):
    base = dict(vac_min=90.0, vac_max=264.0, vout=5.0, iout=3.0, fsw=65.0e3,
                eta_target=0.80, line_freq=50.0, mode="CCM", ripple_k=0.40)
    base.update(kw)
    return DesignSpec(**base)


def run(chk) -> None:
    # ---- clearance table -------------------------------------------------
    chk.eq(len(CLEARANCE_TABLE), 6, "clearance table has six bands")
    chk.close(lookup_clearance(50.0, 2, "basic")[0], 0.60, 1e-12, "50 Vrms PD2 basic = 0.6 mm")
    chk.close(lookup_clearance(50.0, 1, "basic")[0], 0.10, 1e-12, "50 Vrms PD1 basic = 0.1 mm")
    chk.close(lookup_clearance(50.0, 3, "basic")[0], 0.60, 1e-12, "50 Vrms PD3 basic = 0.6 mm")
    chk.close(lookup_clearance(100.0, 3, "basic")[0], 1.00, 1e-12, "100 Vrms PD3 = 1.0 mm")
    chk.close(lookup_clearance(150.0, 2, "basic")[0], 1.00, 1e-12, "150 Vrms PD2 = 1.0 mm")
    chk.close(lookup_clearance(250.0, 2, "basic")[0], 1.50, 1e-12, "250 Vrms PD2 basic = 1.5 mm")
    chk.close(lookup_clearance(250.0, 1, "basic")[0], 1.00, 1e-12, "250 Vrms PD1 basic = 1.0 mm")
    chk.close(lookup_clearance(250.0, 3, "basic")[0], 2.00, 1e-12, "250 Vrms PD3 basic = 2.0 mm")
    chk.close(lookup_clearance(250.0, 2, "reinforced")[0], 3.00, 1e-12, "reinforced = 2 x basic")
    chk.close(lookup_clearance(250.0, 2, "functional")[0], 0.75, 1e-12, "functional = 0.5 x basic")
    chk.close(lookup_clearance(300.0, 2, "basic")[0], 1.50, 1e-12, "264 Vrms falls in the 300 band")
    chk.close(lookup_clearance(600.0, 2, "basic")[0], 2.00, 1e-12, "600 Vrms PD2 = 2.0 mm")
    chk.close(lookup_clearance(1000.0, 2, "basic")[0], 2.50, 1e-12, "1000 Vrms PD2 = 2.5 mm")
    chk.close(lookup_clearance(250.0, 2, "basic")[0], 1.50, 1e-12, "no altitude -> factor 1.0")
    value, factor = lookup_clearance(250.0, 2, "basic", altitude_m=3000.0)
    chk.close(factor, 1.14, 1e-12, "3000 m factor 1.14")
    chk.close(value, 1.50 * 1.14, 1e-12, "clearance scaled by the altitude factor")
    chk.close(lookup_clearance(250.0, 2, "reinforced", altitude_m=4000.0)[0], 3.00 * 1.29, 1e-12,
              "reinforced plus altitude")
    chk.close(altitude_factor(0.0), 1.0, 1e-12, "sea level factor")
    chk.close(altitude_factor(2000.0), 1.0, 1e-12, "2000 m is the reference")
    chk.close(altitude_factor(2999.0), 1.14, 1e-12, "just inside the 3000 m band")
    chk.close(altitude_factor(7000.0), 2.00, 1e-12, "7000 m factor")
    chk.eq(len(ALTITUDE_FACTORS), 6, "altitude table size")
    chk.raises(OPL_E_INPUT, altitude_factor, 8000.0, _msg="altitude beyond the table")
    chk.raises(OPL_E_INPUT, altitude_factor, -1.0, _msg="negative altitude")
    chk.raises(OPL_E_TABLE, lookup_clearance, 1200.0, 2, "basic", _msg="above 1000 Vrms")
    chk.raises(OPL_E_TABLE, lookup_clearance, 250.0, 4, "basic", _msg="PD4 not tabulated")
    chk.raises(OPL_E_INPUT, lookup_clearance, 250.0, 2, "double", _msg="unknown insulation")
    chk.raises(OPL_E_INPUT, lookup_clearance, -5.0, 2, "basic", _msg="negative voltage")

    # ---- creepage table --------------------------------------------------
    chk.eq(len(CREEPAGE_TABLE), 8, "creepage table has eight bands")
    chk.close(lookup_creepage(50.0, 2, "IIIa"), 0.60, 1e-12, "50 Vrms IIIa = 0.6 mm")
    chk.close(lookup_creepage(100.0, 2, "IIIa"), 1.00, 1e-12, "100 Vrms IIIa = 1.0 mm")
    chk.close(lookup_creepage(250.0, 2, "IIIa"), 2.50, 1e-12, "250 Vrms IIIa = 2.5 mm (the classic number)")
    chk.close(lookup_creepage(250.0, 2, "IIIb"), 2.50, 1e-12, "IIIb same column")
    chk.close(lookup_creepage(250.0, 2, "I"), 1.00, 1e-12, "material group I = 1.0 mm")
    chk.close(lookup_creepage(250.0, 2, "II"), 1.00, 1e-12, "material group II = 1.0 mm")
    chk.close(lookup_creepage(250.0, 2, "IIIa", "reinforced"), 5.00, 1e-12, "reinforced creepage 5.0 mm")
    chk.close(lookup_creepage(250.0, 2, "IIIa", "functional"), 1.25, 1e-12, "functional = 0.5 x basic")
    chk.close(lookup_creepage(264.0, 2, "IIIa"), 3.20, 1e-12, "264 Vrms falls in the 400 band")
    chk.close(lookup_creepage(400.0, 2, "IIIa"), 3.20, 1e-12, "400 Vrms IIIa = 3.2 mm")
    chk.close(lookup_creepage(1000.0, 2, "IIIa"), 8.00, 1e-12, "1000 Vrms IIIa = 8.0 mm")
    chk.close(lookup_creepage(1000.0, 2, "I"), 4.00, 1e-12, "1000 Vrms group I = 4.0 mm")
    chk.raises(OPL_E_TABLE, lookup_creepage, 1200.0, 2, "IIIa", _msg="above the table")
    chk.raises(OPL_E_INPUT, lookup_creepage, 250.0, 2, "IV", _msg="unknown material group")
    chk.raises(OPL_E_TABLE, lookup_creepage, 250.0, 5, "IIIa", _msg="pollution degree 5")

    # ---- leakage current -------------------------------------------------
    chk.close(leakage_current_ma(264.0, 50.0, 2.0e-9), 0.165876, 1e-5, "2 nF at 264 V / 50 Hz")
    chk.close(leakage_current_ma(230.0, 50.0, 1.0e-6), 72.257, 1e-5, "1 uF at 230 V / 50 Hz")
    chk.close(leakage_current_ma(264.0, 50.0, 2.0e-9) / leakage_current_ma(264.0, 50.0, 1.0e-9),
              2.0, 1e-9, "leakage scales with capacitance")
    chk.close(leakage_current_ma(264.0, 60.0, 1.0e-9) / leakage_current_ma(264.0, 50.0, 1.0e-9),
              1.2, 1e-9, "leakage scales with line frequency")
    chk.close(leakage_current_ma(264.0, 50.0, 0.0), 0.0, 1e-12, "no Y caps, no leakage")
    chk.close(STANDARD_LEAKAGE_LIMITS_MA["II"], 0.25, 1e-12, "class II limit 0.25 mA")
    chk.close(STANDARD_LEAKAGE_LIMITS_MA["I"], 3.5, 1e-12, "class I limit 3.5 mA")
    chk.raises(OPL_E_INPUT, leakage_current_ma, 264.0, 50.0, -1.0, _msg="negative capacitance")

    # ---- check_safety ----------------------------------------------------
    d = design_flyback(spec())
    ok = check_safety(d, 6.0, 6.5, insulation="reinforced", altitude_m=2000.0, cy_f=1.0e-9)
    chk.close(ok.requirement.clearance_mm, 3.00, 1e-12, "reinforced clearance requirement")
    chk.close(ok.requirement.creepage_mm, 6.40, 1e-12, "reinforced creepage requirement")
    chk.close(ok.clearance_margin_mm, 3.00, 1e-12, "clearance margin")
    chk.close(ok.creepage_margin_mm, 0.10, 1e-6, "creepage margin")
    chk.true(ok.passed, "6.0/6.5 mm satisfies the reinforced requirement")
    chk.true(ok.clearance_pass and ok.creepage_pass and ok.leakage_pass, "all three sub-checks pass")
    chk.close(ok.leakage_current_ma, 0.165876, 1e-5, "leakage with 2 x 1 nF")
    chk.close(ok.leakage_limit_ma, 0.25, 1e-12, "class II limit")
    chk.true(ok.conclusion.startswith("PASS"), "conclusion string starts with PASS")
    chk.true("2K" in ok.requirement.basis or "table" in ok.requirement.basis, "basis records the tables")

    tight = check_safety(d, 1.5, 2.5, insulation="reinforced", altitude_m=2000.0, cy_f=1.0e-9)
    chk.false(tight.passed, "1.5/2.5 mm fails the reinforced requirement")
    chk.close(tight.clearance_margin_mm, 1.5 - 3.0, 1e-12, "negative clearance margin")
    chk.close(tight.creepage_margin_mm, 2.5 - 6.4, 1e-12, "negative creepage margin")
    chk.true(tight.conclusion.startswith("FAIL"), "conclusion string starts with FAIL")

    basic = check_safety(d, 1.6, 3.3, insulation="basic", altitude_m=0.0,
                         material_group="IIIa", cy_f=1.0e-9)
    chk.true(basic.passed, "1.6/3.3 mm satisfies the basic requirement at sea level")
    chk.close(basic.requirement.clearance_mm, 1.50, 1e-12, "basic clearance")
    chk.close(basic.requirement.creepage_mm, 3.20, 1e-12, "basic creepage")

    leaky = check_safety(d, 6.0, 6.5, cy_f=2.2e-9)
    chk.false(leaky.leakage_pass, "2 x 2.2 nF exceeds the class II leakage limit")
    chk.true(any("leakage" in w for w in leaky.warnings), "leakage warning raised")
    chk.true(any("nF" in w for w in leaky.warnings), "warning suggests the maximum Y value")
    chk.false(leaky.passed, "leakage failure fails the whole check")

    hi = check_safety(d, 8.0, 9.0, altitude_m=4000.0)
    chk.true(any("altitude" in w for w in hi.warnings), "altitude warning raised")
    chk.raises(OPL_E_INPUT, check_safety, dict(), 6.0, 6.5, _msg="wrong design type")
    chk.raises(OPL_E_INPUT, check_safety, d, -1.0, 6.5, _msg="negative clearance")
    chk.raises(OPL_E_INPUT, check_safety, d, 6.0, 6.5, _msg="unknown equipment class",
               equipment_class="IV")

    # ---- insertion loss --------------------------------------------------
    chk.close(insertion_loss_lc(1.0, 1.0e-3, 1.0e-6), 0.0, 1e-12, "no attenuation far below resonance",
              abs_tol=1e-6)
    chk.close(insertion_loss_lc(5032.9, 1.0e-3, 1.0e-6), 1.687902, 1e-4, "IL at the LC corner hand value")
    chk.close(insertion_loss_lc(500e3, 1.0e-3, 1.0e-6), 73.8658, 1e-3, "IL far above resonance hand value")
    chk.true(insertion_loss_lc(50e3, 1.0e-3, 1.0e-6) > insertion_loss_lc(5e3, 1.0e-3, 1.0e-6),
             "insertion loss grows with frequency")
    chk.close(insertion_loss_lc(100e3, 0.0, 1.0e-6), 23.9400, 1e-3, "single shunt capacitor case")
    chk.close(insertion_loss_lc(100e3, 1.0e-3, 0.0), 16.0722, 1e-3,
              "series inductor alone attenuates against the 50 ohm load")
    chk.close(insertion_loss_lc(503.29e3, 1.0e-3, 1.0e-6) - insertion_loss_lc(50.329e3, 1.0e-3, 1.0e-6),
              40.0, 0.02, "second-order roll-off is 40 dB per decade")
    chk.raises(OPL_E_INPUT, insertion_loss_lc, 0.0, 1e-3, 1e-6, _msg="f=0")
    chk.raises(OPL_E_INPUT, insertion_loss_lc, 1e3, -1e-3, 1e-6, _msg="negative inductance")
    chk.raises(OPL_E_INPUT, insertion_loss_lc, 1e3, 1e-3, 1e-6, 0.0, _msg="zero source impedance")

    filt = EmiFilter()
    chk.close(insertion_loss_cm(150e3, filt), 45.5147, 1e-4, "CM insertion loss at 150 kHz hand value")
    chk.close(insertion_loss_dm(150e3, filt), 14.7378, 1e-4, "DM insertion loss at 150 kHz hand value")
    chk.true(insertion_loss_cm(150e3, filt) > insertion_loss_dm(150e3, filt),
             "the CM choke dominates at 150 kHz with these values")
    chk.close(insertion_loss_dm(1.0e6, filt), insertion_loss_lc(
        1.0e6, filt.ldm_h, filt.cx_f, filt.rs_ohm, filt.rl_ohm), 1e-12, "DM delegates to the LC formula")
    chk.close(insertion_loss_cm(1.0e6, filt), insertion_loss_lc(
        1.0e6, 2.0 * filt.lcm_h, filt.cy_f, filt.rs_ohm, filt.rl_ohm), 1e-12, "CM uses 2*L per winding")
    chk.raises(OPL_E_INPUT, insertion_loss_dm, 1e3, "not a filter", _msg="wrong filter type")

    # ---- emi_report ------------------------------------------------------
    rep = emi_report(filt, target_db=40.0, design=d)
    chk.eq(len(rep.curve), 200, "default curve resolution")
    chk.close(rep.curve[0][0], 150e3, 1e-6, "curve starts at 150 kHz")
    chk.close(rep.curve[-1][0], 30e6, 1e-6, "curve ends at 30 MHz")
    chk.close(rep.f_start_hz, 150e3, 1e-12, "band recorded")
    chk.true(rep.cm_pass, "CM meets 40 dB from 150 kHz with a 10 mH choke")
    chk.close(rep.f_pass_cm_hz, 150e3, 1e-6, "CM pass frequency is the band start")
    chk.false(rep.dm_pass, "DM needs more than 20 uH to reach 40 dB at 150 kHz")
    chk.close(rep.f_pass_dm_hz, 1047581.0, 1e-3, "DM 40 dB frequency hand value")
    chk.true(rep.leakage_pass, "2 x 1 nF passes the class II leakage limit")
    chk.close(rep.leakage_current_ma, 0.165876, 1e-5, "leakage reported")
    chk.close(rep.leakage_limit_ma, 0.25, 1e-12, "limit from the equipment class")
    chk.false(rep.passed, "the default filter does not pass both targets")
    chk.true(any("noise measurement" in w for w in rep.warnings), "spectrum caveat is stated")

    better = EmiFilter(ldm_h=200e-6, cx_f=0.47e-6)
    rep2 = emi_report(better, target_db=40.0)
    chk.close(insertion_loss_dm(150e3, better), 32.6206, 1e-4, "bigger DM filter at 150 kHz")
    chk.true(rep2.f_pass_dm_hz < rep.f_pass_dm_hz, "more DM inductance lowers the pass frequency")
    chk.false(rep2.dm_pass, "40 dB at the 150 kHz band start needs even more DM filtering")
    strong = EmiFilter(ldm_h=470e-6, cx_f=1.0e-6)
    rep3 = emi_report(strong, target_db=40.0)
    chk.true(rep3.dm_pass, "1 uF + 470 uH reaches 40 dB from 150 kHz")
    chk.true(rep3.passed, "and the full filter then passes both modes")

    rep4 = emi_report(filt, target_db=200.0)
    chk.eq(rep4.f_pass_dm_hz, float("inf"), "impossible DM target never reached")
    chk.eq(rep4.f_pass_cm_hz, float("inf"), "impossible CM target never reached")
    rep5 = emi_report(filt, target_db=100.0)
    chk.true(rep5.f_pass_cm_hz > 10e6, "100 dB of CM attenuation is only reached at HF")
    lea = emi_report(EmiFilter(cy_f=2.2e-9), target_db=40.0, cy_count=2)
    chk.false(lea.leakage_pass, "2 x 2.2 nF exceeds the class II limit")
    chk.true(any("nF" in w for w in lea.warnings), "warning quotes the maximum Y capacitance")
    rep_small = emi_report(filt, n_points=10, f_start_hz=1e6, f_stop_hz=2e6)
    chk.eq(len(rep_small.curve), 10, "custom resolution honoured")
    chk.raises(OPL_E_INPUT, emi_report, filt, _msg="f_stop below f_start", f_start_hz=1e6, f_stop_hz=1e3)
    chk.raises(OPL_E_INPUT, emi_report, filt, _msg="unknown equipment class", equipment_class="IX")
    chk.raises(OPL_E_INPUT, emi_report, "not a filter", _msg="wrong filter type")
