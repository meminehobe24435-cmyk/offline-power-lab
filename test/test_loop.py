"""Checks for opl.loop - average model, Type-II design, Bode analysis.

The power-stage poles are pinned against hand calculations for the default
example (5 V / 3 A, 470 uF with 40 mohm ESR), and the compensator/loop results
are checked for the properties that must hold whatever the numbers are
(crossover lands on the request, analytic and numeric agree, a forced bad
crossover fails the verdict and a damped output filter passes it).
"""

from __future__ import annotations

import math

from opl import (
    OPL_E_INPUT,
    OPL_E_UNSAT,
    Compensator,
    Components,
    DesignSpec,
    PowerStageModel,
    analyze_loop,
    compensator_response,
    design_compensator,
    design_flyback,
    loop_response,
    numeric_crossover,
    analytic_crossover,
    power_stage_model,
    power_stage_response,
    sweep_response,
    type2_components,
)
from opl.loop import opto_response

TWO_PI = 2.0 * math.pi


def spec(**kw):
    base = dict(vac_min=90.0, vac_max=264.0, vout=5.0, iout=3.0, fsw=65.0e3,
                eta_target=0.80, mode="CCM", ripple_k=0.40)
    base.update(kw)
    return DesignSpec(**base)


# hand-calculated power-stage values for the default design ------------------
VIN_MIN = 90.0 * 2.0 ** 0.5 - 1.4
VOR = VIN_MIN * 0.45 / 0.55
N = VOR / 5.5
L_SEC = 5.265607519035243e-3 / N ** 2          # Lp/n^2 = 1.501637e-5 H
R_LOAD = 5.0 / 3.0                             # 1.6667 ohm
COUT = 470e-6
ESR = 0.040
W0 = 0.55 / math.sqrt(L_SEC * COUT)            # 6546.8 rad/s
Q = 1.0 / (W0 * L_SEC / (0.55 ** 2 * R_LOAD) + W0 * ESR * COUT)
W_RHP = 0.55 ** 2 * R_LOAD / (0.45 * L_SEC)
W_ESR = 1.0 / (ESR * COUT)
G0 = VIN_MIN / (N * 0.55 ** 2)


def run(chk) -> None:
    d = design_flyback(spec())
    comp = Components()
    p = power_stage_model(d, comp)

    # ---- power stage vs hand calculation --------------------------------
    chk.close(p.g0_dc, G0, 1e-9, "g0 = Vin/(n*(1-D)^2) hand value")
    chk.close(p.g0_dc, 22.2224, 1e-4, "g0 hand value (22.22 V per unit duty)")
    chk.close(p.l_sec_h, L_SEC, 1e-9, "L_sec = Lp/n^2 hand value")
    chk.close(p.r_load_ohm, R_LOAD, 1e-12, "R_load = Vout/Iout")
    chk.close(p.w0, W0, 1e-9, "w0 = (1-D)/sqrt(L_sec*Cout) hand value")
    chk.close(p.f0_hz, W0 / TWO_PI, 1e-9, "f0 mirror in Hz")
    chk.close(p.f0_hz, 1042.0, 1e-3, "f0 hand value 1042 Hz")
    chk.close(p.q, Q, 1e-9, "Q hand value (load + ESR damping)")
    chk.close(p.q, 3.144, 1e-3, "Q hand value 3.14")
    chk.close(p.w_rhp, W_RHP, 1e-9, "RHP zero hand value")
    chk.close(p.f_rhp_hz, 11874.5, 1e-4, "RHP zero 11.87 kHz")
    chk.close(p.w_esr, W_ESR, 1e-9, "ESR zero hand value")
    chk.close(p.f_esr_hz, 8465.7, 1e-4, "ESR zero 8.47 kHz")
    chk.eq(p.mode, "CCM", "mode reported")
    chk.close(p.g0_dc, 125.87922061357855 / (N * 0.3025), 1e-9, "g0 consistency")
    chk.true(len(p.notes) >= 1, "model carries its assumptions in notes")
    chk.true(any("average model" in n for n in p.notes), "average-model caveat present")

    # DC response equals the DC gain, and the double pole shows up as a peak
    chk.close(abs(power_stage_response(p, 1e-3)), G0, 1e-3, "Gvd(0) = g0")
    chk.close(abs(power_stage_response(p, p.f0_hz)), G0 * Q, 0.05, "Gvd(f0) ~ g0*Q")
    chk.true(abs(power_stage_response(p, p.f0_hz)) > abs(power_stage_response(p, 10.0 * p.f0_hz)),
             "magnitude falls above the resonance")
    chk.raises(OPL_E_INPUT, power_stage_response, p, 0.0, _msg="f=0")
    chk.raises(OPL_E_INPUT, power_stage_model, "not a design", comp, _msg="wrong type")

    # a damped output filter must lower Q (positive example)
    p_damped = power_stage_model(d, Components(cout_esr=0.30))
    chk.true(p_damped.q < p.q, "more ESR lowers Q")
    chk.close(p_damped.f_esr_hz, 1.0 / (TWO_PI * 0.30 * COUT), 1e-9, "ESR zero moves with ESR")
    p_big = power_stage_model(d, Components(cout_cap_f=2000e-6))
    chk.true(p_big.f0_hz < p.f0_hz, "more Cout lowers f0")
    chk.close(p_big.w0, 0.55 / math.sqrt(L_SEC * 2000e-6), 1e-9, "w0 with 2000 uF")

    # DCM power stage: single pole, no RHP zero modelled
    dcm = design_flyback(spec(mode="DCM"))
    p_dcm = power_stage_model(dcm, comp)
    chk.eq(p_dcm.mode, "DCM", "DCM mode reported")
    chk.close(p_dcm.g0_dc, dcm.spec.vout_ref / dcm.dmax, 1e-9, "DCM g0 = Vout_ref/D")
    chk.close(p_dcm.w0, 2.0 / (R_LOAD * COUT), 1e-9, "DCM w0 = 2/(R*C)")
    chk.eq(p_dcm.w_rhp, float("inf"), "DCM RHP zero not modelled")
    chk.true(any("DCM" in n for n in p_dcm.notes), "DCM caveat in notes")

    # ---- optocoupler / modulator ----------------------------------------
    chk.close(abs(opto_response(comp, 1.0)), comp.opto_ctr * comp.opto_r_pullup / comp.opto_r_led,
              1e-6, "opto DC gain = CTR*Rpull/Rled = 10")
    chk.close(abs(opto_response(comp, 1.0)), 10.0, 1e-4, "opto DC gain hand value")
    w_opto = 1.0 / (comp.opto_r_pullup * comp.opto_c_pole)
    chk.close(abs(opto_response(comp, w_opto / TWO_PI)) / 10.0, 2.0 ** -0.5, 1e-6, "opto pole at -3 dB")
    chk.close(comp.ctrl_vramp, 2.5, 1e-12, "modulator ramp from the part list")

    # ---- compensator transfer function ----------------------------------
    net = Compensator(kind="II", kc=1.0, wz=1000.0, wp=10000.0)
    mag_at_zero = abs(compensator_response(net, 1000.0 / TWO_PI))
    hand = math.sqrt(2.0) / (1000.0 * math.sqrt(1.0 + 0.01))
    chk.close(mag_at_zero, hand, 1e-9, "|Hc| at wz hand value")
    chk.close(mag_at_zero, 1.40727e-3, 1e-4, "|Hc| hand value")
    phase_low = math.degrees(__import__("cmath").phase(compensator_response(net, 0.1)))
    chk.close(phase_low, -90.0, 1e-3, "integrator gives -90 deg at low frequency")
    mag_high = abs(compensator_response(net, 1.0e6 / TWO_PI))
    chk.true(mag_high < mag_at_zero, "Type-II rolls off above the zero")
    net3 = Compensator(kind="III", kc=1.0, wz=1000.0, wp=1.0e6, wz2=100.0, wp2=1.0e7)
    chk.true(abs(compensator_response(net3, 500.0 / TWO_PI)) > 0.0, "Type-III evaluates")
    chk.raises(OPL_E_INPUT, compensator_response, net, 0.0, _msg="f=0")

    # ---- sweep helper ----------------------------------------------------
    pts = sweep_response(lambda f: loop_response(p, net, comp, f), 10.0, 1.0e5, 50)
    chk.eq(len(pts), 50, "sweep returns the requested number of points")
    chk.close(pts[0].f_hz, 10.0, 1e-12, "sweep starts at f_start")
    chk.close(pts[-1].f_hz, 1.0e5, 1e-9, "sweep ends at f_stop")
    chk.true(pts[1].f_hz > pts[0].f_hz, "sweep is ascending")
    chk.true(all(pts[i].f_hz < pts[i + 1].f_hz for i in range(len(pts) - 1)), "sweep strictly ascending")
    chk.close(pts[0].phase_deg, -90.0, 0.1, "loop phase starts near -90 deg")
    chk.raises(OPL_E_INPUT, sweep_response, lambda f: 1 + 0j, 1e5, 10.0, 10, _msg="f_stop < f_start")
    chk.raises(OPL_E_INPUT, sweep_response, lambda f: 1 + 0j, 0.0, 10.0, 10, _msg="f_start=0")

    # ---- automatic design ------------------------------------------------
    auto = design_compensator(p, comp, design=d)
    chk.true(auto.kc > 0.0, "kc positive")
    chk.true(auto.wz > 0.0 and auto.wp > auto.wz, "Type-II corners ordered")
    chk.eq(auto.kind, "II", "default kind is II")
    chk.true("r_upper_ohm" in auto.components, "component synthesis attached")
    r = analyze_loop(p, auto, comp, design=d)
    chk.true(r.fc_hz > 0.0, "crossover found")
    chk.true(abs(r.fc_error_pct) < 25.0, "analytic crossover agrees with the sweep (<25 %)")
    chk.close(r.fc_error_pct, (r.fc_hz - r.fc_analytic_hz) / r.fc_hz * 100.0, 1e-9, "error definition")
    chk.true(r.phase_margin_deg > 0.0, "positive phase margin")
    chk.close(r.pm_target_deg, 45.0, 1e-12, "default PM target")
    chk.eq(r.passed, r.phase_margin_deg >= r.pm_target_deg and
           (r.gain_margin_db == float("inf") or r.gain_margin_db >= r.gm_target_db),
           "verdict follows PM and GM")
    chk.eq(len(r.sweep), 400, "default sweep resolution")
    chk.close(abs(loop_response(p, auto, comp, r.fc_hz)), 1.0, 1e-2, "|T(fc)| = 1")
    chk.true(any("crosses 0 dB" in w for w in r.warnings),
             "high-Q resonance produces a conditional-stability warning")
    chk.false(r.passed, "the un-damped 40 mohm output filter fails the gain-margin target")

    # forced crossover requests are honoured
    high = analyze_loop(p, design_compensator(p, comp, design=d, fc_target_hz=20e3), comp, design=d)
    chk.true(high.fc_hz > r.fc_hz, "a higher fc request gives a higher crossover")
    chk.false(high.passed, "forcing the crossover to 20 kHz fails the verdict")
    low = analyze_loop(p, design_compensator(p, comp, design=d, fc_target_hz=150.0), comp, design=d)
    chk.true(low.fc_hz < r.fc_hz, "a lower fc request gives a lower crossover")
    chk.close(low.fc_hz, 150.0, 0.6, "requested crossover achieved within 60 %")
    chk.true(low.phase_margin_deg > 45.0, "slower loop has plenty of phase margin")

    # a damped output filter must PASS
    comp_d = Components(cout_cap_f=940e-6, cout_esr=0.20)
    p_d = power_stage_model(d, comp_d)
    net_d = design_compensator(p_d, comp_d, design=d)
    r_d = analyze_loop(p_d, net_d, comp_d, design=d)
    chk.true(r_d.passed, "damped output filter passes PM and GM targets")
    chk.true(r_d.phase_margin_deg > 60.0, "damped loop has a comfortable phase margin")
    chk.true(abs(r_d.fc_error_pct) < 10.0, "analytic agrees closely for the damped case")

    # explicit targets are respected
    strict = analyze_loop(p_d, net_d, comp_d, design=d, pm_target_deg=80.0)
    chk.true(strict.pm_target_deg == 80.0, "custom PM target recorded")
    chk.eq(strict.passed, strict.phase_margin_deg >= 80.0 and
           (strict.gain_margin_db == float("inf") or strict.gain_margin_db >= strict.gm_target_db),
           "verdict follows the custom target")

    # ---- type2 component synthesis --------------------------------------
    comps = type2_components(d, 500.0, TWO_PI * 500.0, TWO_PI * 5000.0)
    chk.close(comps["r_lower_ohm"], 10000.0, 1e-12, "divider lower resistor default")
    chk.close(comps["r_upper_ohm"], 10000.0 * (5.0 / 2.495 - 1.0), 1e-9, "R_upper = R_lower*(Vout/Vref-1)")
    chk.close(comps["r_upper_ohm"], 10040.08, 1e-5, "R_upper hand value")
    chk.close(comps["r_par_ohm"], 10040.08 * 10000.0 / (10040.08 + 10000.0), 1e-4, "divider Thevenin")
    chk.close(comps["c_zero_f"], 1.0 / (TWO_PI * 500.0 * comps["r_upper_ohm"]), 1e-9, "C_zero from fz")
    chk.close(comps["c_pole_f"], 1.0 / (TWO_PI * 5000.0 * comps["r_par_ohm"]), 1e-9, "C_pole from fp")
    chk.close(comps["i_led_ma"], 1.4, 1e-9, "opto LED bias current hand value (1.4 mA)")

    # ---- failure modes ---------------------------------------------------
    chk.raises(OPL_E_INPUT, design_compensator, p, comp, _msg="bad kind", kind="IV")
    chk.raises(OPL_E_INPUT, design_compensator, p, comp, _msg="bad PM target", pm_target_deg=120.0)
    chk.raises(OPL_E_INPUT, analyze_loop, "not a model", auto, comp, _msg="wrong power stage")
    chk.raises(OPL_E_INPUT, analyze_loop, p, "not a compensator", comp, _msg="wrong compensator")
    # a power stage whose RHP zero sits at a few Hz cannot be compensated
    bad = PowerStageModel(
        g0_dc=20.0, w0=TWO_PI * 12.0, q=1.0, w_rhp=TWO_PI * 1.8, w_esr=TWO_PI * 5000.0,
        mode="CCM", l_sec_h=0.1, cout_f=470e-6, r_load_ohm=1.667, esr_ohm=0.04,
    )
    chk.raises(OPL_E_UNSAT, design_compensator, bad, comp, _msg="uncompensatable power stage")

    # numeric/analytic crossover agree on a well-behaved hand-made model
    good = PowerStageModel(
        g0_dc=20.0, w0=TWO_PI * 1000.0, q=1.0, w_rhp=TWO_PI * 80000.0,
        w_esr=TWO_PI * 20000.0, mode="CCM", l_sec_h=1.0e-4, cout_f=470e-6,
        r_load_ohm=1.667, esr_ohm=0.04,
    )
    good_net = design_compensator(good, comp)
    fc_num = numeric_crossover(good, good_net, comp)
    fc_ana = analytic_crossover(good, good_net, comp)
    chk.true(fc_num != float("inf"), "crossover exists for the hand-made model")
    chk.close(fc_ana / fc_num, 1.0, 0.15, "analytic and numeric agree within 15 %")
    good_loop = analyze_loop(good, good_net, comp)
    chk.true(good_loop.passed, "a low-Q power stage passes the loop targets")
    chk.true(good_loop.phase_margin_deg > 45.0, "phase margin above target")
