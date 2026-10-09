"""Checks for opl.flyback, opl.magnetics and opl.stress.

A deliberate mix of three kinds of assertion:

1. **Hand-computed textbook values** - numbers calculated outside this code base
   from the formulas printed in the module docstrings (see the comments).  These
   catch "consistent but wrong" formula errors that a self-consistent suite
   would never find.
2. **Invariant / conservation laws** - power balance, ampere-turn equality,
   ``D = Vor/(Vin+Vor)``, ``Lp/Lbcm = (2-kr)/kr``, RMS identities.
3. **Boundary and illegal-input cases** - every documented error code is
   exercised at least once, in both directions (negative and positive example)
   for the derating verdicts.
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
    bmax_of,
    boundary_inductance,
    design_flyback,
    design_magnetics,
    derating_ratio,
    discharge_time_dcm,
    duty_ccm,
    duty_dcm,
    duty_from_vor,
    evaluate_stress,
    find_core,
    gap_mm_for_lp,
    list_cores,
    nearest_awg,
    peak_current_ccm,
    pick_wire,
    primary_rms,
    required_ap,
    rds_on_hot,
    rectifier_stress,
    secondary_rms,
    select_core,
    skin_depth_mm,
    trapezoid_rms,
    verify_power_balance,
)
from opl.magnetics import CORE_TABLE, ENAMEL_BUILD_FACTOR, MATERIALS
from opl.stress import cap_life_hours, capacitor_stress, clamp_stress, mosfet_stress

SQRT2 = 2.0 ** 0.5


def default_spec(**kw):
    """90-264 VAC -> 5 V / 3 A, 65 kHz, 80 % target (see hand calculations)."""
    base = dict(
        vac_min=90.0,
        vac_max=264.0,
        vout=5.0,
        iout=3.0,
        fsw=65.0e3,
        eta_target=0.80,
        line_freq=50.0,
        bridge_drop=1.4,
        vf_sec=0.50,
        dmax_limit=0.50,
        dmax_target=0.45,
        mode="CCM",
        ripple_k=0.40,
        dcm_k=0.60,
    )
    base.update(kw)
    return DesignSpec(**base)


# Hand-calculated intermediates for default_spec() ------------------------
VIN_MIN = 90.0 * SQRT2 - 1.4  # 125.8792206 V
VIN_MAX = 264.0 * SQRT2 - 1.4  # 371.9523801 V
VOR = VIN_MIN * 0.45 / 0.55  # 102.9924532 V
N_RATIO = VOR / 5.5  # 18.72590058
IPK = 2.0 * 18.75 / (VIN_MIN * 0.45 * 1.6)  # 0.4137564 A
IP1 = IPK * 0.6  # 0.2482538 A
LP = VIN_MIN * 0.45 / (0.4 * IPK * 65e3)  # 5.26588 mH
LBCM = (VIN_MIN * 0.45) ** 2 / (2.0 * 18.75 * 65e3)  # 1.316401 mH


def run(chk) -> None:
    # =====================================================================
    # A. spec / derived quantities
    # =====================================================================
    s = default_spec()
    chk.close(s.pout, 15.0, 1e-12, "Pout = 5 V * 3 A")
    chk.close(s.pin, 18.75, 1e-12, "Pin = 15 / 0.8")
    chk.close(s.vout_ref, 5.5, 1e-12, "Vout_ref = 5.0 + 0.5")
    chk.close(s.vin_dc_min(), VIN_MIN, 1e-9, "Vin_dc_min = 90*sqrt(2) - 1.4")
    chk.close(s.vin_dc_max(), VIN_MAX, 1e-9, "Vin_dc_max = 264*sqrt(2) - 1.4")
    chk.close(s.vin_dc_min(30.0), VIN_MIN - 30.0, 1e-9, "bulk ripple lowers the valley")

    # =====================================================================
    # B. primitive formulas vs hand calculation
    # =====================================================================
    chk.close(duty_from_vor(100.0, 100.0), 0.5, 1e-12, "Vor=Vin -> D=0.5")
    chk.close(duty_from_vor(150.0, 100.0), 0.6, 1e-12, "Vor/(Vin+Vor) = 150/250")
    chk.close(duty_ccm(100.0, 150.0), 0.6, 1e-12, "duty_ccm arg order")
    chk.close(boundary_inductance(10.0, 100.0, 0.5, 100e3), 1.25e-3, 1e-9, "Lbcm hand value")
    chk.close(peak_current_ccm(10.0, 100.0, 0.5, 0.4), 0.25, 1e-12, "Ipk hand value")
    chk.close(duty_dcm(10.0, 1e-3, 100e3, 100.0), 0.4472136, 1e-6, "DCM duty hand value")
    chk.close(discharge_time_dcm(0.5, 1e-3, 10.0, 5.0), 1e-5, 1e-9, "tdis hand value")
    chk.close(trapezoid_rms(0.0, 2.0, 0.5), (0.5 * 4.0 / 3.0) ** 0.5, 1e-12, "triangle RMS")
    chk.close(trapezoid_rms(1.0, 1.0, 0.5), 0.5 ** 0.5, 1e-12, "rectangle RMS = I*sqrt(D)")
    chk.close(primary_rms(1.0, 0.0, 0.5), 0.5 ** 0.5, 1e-12, "kr=0 -> flat current")
    chk.close(secondary_rms(1.0, 1.0, 0.5, 10.0), 10.0 * (0.5 / 3.0) ** 0.5, 1e-12, "Is = n*Ip")

    # illegal inputs for the primitives
    chk.raises(OPL_E_INPUT, duty_from_vor, 0.0, 100.0, _msg="Vor=0")
    chk.raises(OPL_E_INPUT, duty_from_vor, -5.0, 100.0, _msg="Vor<0")
    chk.raises(OPL_E_INPUT, duty_dcm, 10.0, 1e-3, 0.0, 100.0, _msg="fsw=0")
    chk.raises(OPL_E_INPUT, peak_current_ccm, 10.0, 100.0, 1.5, 0.4, _msg="D>1")
    chk.raises(OPL_E_INPUT, peak_current_ccm, 10.0, 100.0, 0.5, 0.0, _msg="kr=0")
    chk.raises(OPL_E_INPUT, trapezoid_rms, 1.0, 1.0, 1.2, _msg="duty>1")
    chk.raises(OPL_E_INPUT, trapezoid_rms, -1.0, 1.0, 0.5, _msg="negative current")
    chk.raises(OPL_E_INPUT, boundary_inductance, 0.0, 100.0, 0.5, 65e3, _msg="Pin=0")
    chk.raises(OPL_E_RANGE, duty_dcm, 10.0, 1.0, 65e3, 10.0, _msg="no DCM solution")

    # =====================================================================
    # C. CCM design of default_spec vs hand calculation
    # =====================================================================
    d = design_flyback(s)
    chk.eq(d.mode, "CCM", "mode stays CCM")
    chk.close(d.vin_dc_min, VIN_MIN, 1e-9, "design bulk min")
    chk.close(d.vin_dc_max, VIN_MAX, 1e-9, "design bulk max")
    chk.close(d.vor, VOR, 1e-9, "Vor = Vin_min*Dmax/(1-Dmax)")
    chk.close(d.n, N_RATIO, 1e-9, "n = Vor/(Vout+Vf)")
    chk.close(d.dmax, 0.45, 1e-12, "Dmax equals the target")
    chk.close(d.dmin, VOR / (VIN_MAX + VOR), 1e-9, "Dmin = Vor/(Vin_max+Vor)")
    chk.close(d.dmin, 0.216851, 1e-4, "Dmin hand value")
    chk.close(d.lp, LP, 1e-9, "Lp hand value")
    chk.close(d.lp, 5.26561e-3, 1e-4, "Lp hand value (5.2656 mH)")
    chk.close(d.lp_bcm, LBCM, 1e-9, "Lbcm hand value")
    chk.close(d.lp / d.lp_bcm, (2.0 - 0.4) / 0.4, 1e-9, "Lp/Lbcm = (2-kr)/kr = 4")
    chk.close(d.ipk, IPK, 1e-9, "Ipk hand value")
    chk.close(d.ipk, 0.413756, 1e-4, "Ipk hand value (0.41376 A)")
    chk.close(d.ip1, IP1, 1e-9, "Ip1 = Ipk*(1-kr)")
    chk.close(d.krip, 0.40, 1e-12, "ripple ratio preserved")
    chk.close(d.irms_pri, 0.224346, 1e-4, "Irms primary hand value")
    chk.close(d.irms_sec, 4.644454, 1e-4, "Irms secondary hand value")
    chk.close(d.is_pk, 7.747934, 1e-4, "Is_pk = n*Ipk")
    chk.close(d.is_avg, 3.409091, 1e-6, "Is_avg = Pin/Vout_ref")
    chk.close(d.ton, 0.45 / 65e3, 1e-12, "ton = D/fsw")
    chk.close(d.tdis, 0.55 / 65e3, 1e-12, "tdis = (1-D)/fsw in CCM")
    chk.close(verify_power_balance(d), 1.0, 1e-9, "CCM power balance closes")
    chk.close(d.is_avg * d.vout_ref, s.pin, 1e-9, "ampere-turn identity: Is_avg*Vout_ref = Pin")
    chk.close(d.iin_avg, s.pin / VIN_MIN, 1e-9, "average input current")
    chk.true(d.dmax_ok, "Dmax within dmax_limit")
    chk.true(d.dmax <= s.dmax_limit, "Dmax <= 0.5 requirement")
    chk.eq(len([w for w in d.warnings if "Dmax" in w]), 0, "no Dmax warning for the nominal design")
    chk.true(d.lp > d.lp_bcm, "CCM above the boundary inductance")

    # =====================================================================
    # D. DCM design vs hand calculation
    # =====================================================================
    sd = default_spec(mode="DCM", dcm_k=0.60)
    dd = design_flyback(sd)
    chk.eq(dd.mode, "DCM", "mode reported as DCM")
    chk.close(dd.lp_bcm, LBCM, 1e-9, "Lbcm unchanged by mode")
    chk.close(dd.lp, 0.60 * LBCM, 1e-9, "Lp = dcm_k * Lbcm")
    chk.close(dd.lp, 7.898407e-4, 1e-6, "DCM Lp hand value (0.7898 mH)")
    chk.close(dd.dmax, 0.45 * 0.60 ** 0.5, 1e-12, "DCM Dmax = Dmax_t*sqrt(dcm_k)")
    chk.close(dd.dmax, 0.3485685, 1e-6, "DCM Dmax hand value")
    chk.close(dd.ipk, 0.8546449, 1e-5, "DCM Ipk hand value")
    chk.close(dd.ip1, 0.0, 1e-15, "DCM starts from zero current")
    chk.close(dd.krip, 1.0, 1e-12, "DCM ripple ratio is 1")
    chk.close(dd.tdis * sd.fsw, 0.55 * 0.60 ** 0.5, 1e-12, "tdis/T = (1-Dmax_t)*sqrt(k)")
    chk.close(dd.dmax + dd.tdis * sd.fsw, 0.60 ** 0.5, 1e-12, "D+D2 = sqrt(k) < 1")
    chk.true(dd.dmax + dd.tdis * sd.fsw < 1.0, "DCM discharge fits in the period")
    chk.close(dd.dmin, dd.dmax * VIN_MIN / VIN_MAX, 1e-12, "DCM Dmin scales as 1/Vin")
    chk.close(verify_power_balance(dd), 1.0, 1e-9, "DCM power balance closes")
    chk.close(dd.is_avg * dd.vout_ref, sd.pin, 1e-9, "DCM ampere-turn identity")
    chk.true(dd.ipk > d.ipk, "DCM peak current is higher than CCM at the same load")
    chk.true(dd.irms_pri > d.irms_pri, "DCM primary RMS is higher than CCM")
    chk.close(dd.irms_sec, dd.n * (dd.tdis * sd.fsw / 3.0) ** 0.5 * dd.ipk, 1e-9,
              "triangular secondary RMS = n*Ipk*sqrt(D2/3)")

    # AUTO mode picks CCM/DCM from ripple_k
    chk.eq(design_flyback(default_spec(mode="AUTO")).mode, "CCM", "AUTO with kr<1 -> CCM")
    chk.eq(
        design_flyback(default_spec(mode="AUTO", ripple_k=1.0)).mode,
        "DCM",
        "AUTO with kr=1 -> DCM branch",
    )
    # kr=1 in CCM mode is the boundary case and must still close the balance
    bcm = design_flyback(default_spec(ripple_k=1.0))
    chk.close(bcm.lp, bcm.lp_bcm, 1e-9, "kr=1 -> Lp = Lbcm exactly")
    chk.close(bcm.ip1, 0.0, 1e-12, "kr=1 -> Ip1 = 0")
    chk.close(verify_power_balance(bcm), 1.0, 1e-9, "BCM power balance closes")

    # =====================================================================
    # E. design checks / negative cases
    # =====================================================================
    # forced Vor that pushes Dmax over the limit but stays buildable
    over = design_flyback(s, vor_target=250.0)
    chk.close(over.dmax, 250.0 / (VIN_MIN + 250.0), 1e-9, "forced Vor sets Dmax")
    chk.true(over.dmax > s.dmax_limit, "forced Vor breaks the Dmax limit")
    chk.false(over.dmax_ok, "dmax_ok false when the limit is broken")
    chk.true(any("Dmax" in w for w in over.warnings), "warning raised for Dmax > limit")
    chk.raises(OPL_E_RANGE, design_flyback, s, 1500.0, _msg="Vor=1500 V -> Dmax>0.9")
    # n <= 1 is not a flyback
    chk.raises(OPL_E_RANGE, design_flyback, default_spec(vout=200.0), _msg="n<1")
    # DCM request that cannot discharge in time
    chk.raises(
        OPL_E_RANGE, duty_dcm, 18.75, 10.0e-3, 65e3, VIN_MIN, _msg="duty >= 1 in DCM"
    )

    # DesignSpec validation
    chk.raises(OPL_E_INPUT, default_spec, vac_min=-5.0, _msg="negative mains")
    chk.raises(OPL_E_INPUT, default_spec, vac_max=50.0, _msg="vac_max < vac_min")
    chk.raises(OPL_E_INPUT, default_spec, vout=0.0, _msg="zero output voltage")
    chk.raises(OPL_E_INPUT, default_spec, iout=0.0, _msg="zero output current")
    chk.raises(OPL_E_INPUT, default_spec, fsw=0.0, _msg="zero switching frequency")
    chk.raises(OPL_E_INPUT, default_spec, eta_target=1.5, _msg="eta > 1")
    chk.raises(OPL_E_INPUT, default_spec, mode="BUCK", _msg="unknown topology mode")
    chk.raises(OPL_E_INPUT, default_spec, ripple_k=0.0, _msg="ripple_k = 0")
    chk.raises(OPL_E_INPUT, default_spec, dcm_k=1.5, _msg="dcm_k > 1")
    chk.raises(OPL_E_INPUT, default_spec, dmax_limit=1.0, _msg="dmax_limit = 1")
    chk.raises(OPL_E_INPUT, default_spec, dmax_target=0.6, _msg="dmax_target > dmax_limit")
    chk.raises(OPL_E_INPUT, design_flyback, "not a spec", _msg="wrong type")

    # =====================================================================
    # F. magnetics vs hand calculation
    # =====================================================================
    # AP hand value: 1e-3 H * 1 A * 0.5 A / (0.4 * 0.25 T * 400 A/cm2) * 1e4 = 0.125 cm4
    chk.close(required_ap(1e-3, 1.0, 0.5, 0.25, 0.4, 4.0), 0.125, 1e-9, "AP hand value")
    chk.close(required_ap(2e-3, 1.0, 0.5, 0.25, 0.4, 4.0), 0.25, 1e-9, "AP doubles with L")
    chk.close(required_ap(1e-3, 2.0, 0.5, 0.25, 0.4, 4.0), 0.25, 1e-9, "AP doubles with Ipk")
    chk.close(required_ap(1e-3, 1.0, 0.5, 0.5, 0.4, 4.0), 0.0625, 1e-9, "AP halves with Bmax")
    chk.close(required_ap(1e-3, 1.0, 0.5, 0.25, 0.8, 4.0), 0.0625, 1e-9, "AP halves with Ku")
    chk.close(required_ap(1e-3, 1.0, 0.5, 0.25, 0.4, 8.0), 0.0625, 1e-9, "AP halves with J")
    chk.raises(OPL_E_INPUT, required_ap, 1e-3, 1.0, 0.5, 0.0, 0.4, 4.0, _msg="Bmax=0")
    chk.raises(OPL_E_INPUT, required_ap, 1e-3, 1.0, 0.5, 0.25, 1.5, 4.0, _msg="Ku>1")

    # skin depth: 66.1/sqrt(65e3) at 20 C, 75.66/sqrt(65e3) at 100 C
    chk.close(skin_depth_mm(65e3, 20.0), 66.1 / (65e3 ** 0.5), 1e-9, "delta at 20 C")
    chk.close(skin_depth_mm(65e3, 20.0), 0.259266, 1e-4, "delta hand value 0.2593 mm")
    chk.close(skin_depth_mm(65e3, 100.0), 0.297241, 1e-4, "delta hand value 0.2972 mm at 100 C")
    chk.close(skin_depth_mm(25e3, 20.0) / skin_depth_mm(100e3, 20.0), 2.0, 1e-9, "delta ~ 1/sqrt(f)")
    chk.raises(OPL_E_INPUT, skin_depth_mm, 0.0, _msg="fsw=0")

    # gap / flux hand values
    chk.close(gap_mm_for_lp(1e-3, 100, 1.0, 10.0, 2000.0), 1.206637, 1e-4, "gap hand value")
    chk.close(gap_mm_for_lp(1e-3, 200, 1.0, 10.0, 2000.0), 4.976548, 1e-4, "gap scales with Np^2")
    chk.close(gap_mm_for_lp(1e-2, 10, 1.0, 10.0, 2000.0), 0.0, 1e-12, "gap clamps at zero")
    chk.close(bmax_of(1e-3, 1.0, 100, 1.0), 0.1, 1e-12, "Bmax hand value 0.1 T")
    chk.close(bmax_of(2e-3, 1.0, 100, 1.0), 0.2, 1e-12, "Bmax scales with L")
    chk.close(bmax_of(1e-3, 1.0, 200, 1.0), 0.05, 1e-12, "Bmax falls with more turns")
    chk.raises(OPL_E_INPUT, bmax_of, 1e-3, 1.0, 0, 1.0, _msg="zero turns")

    # core table sanity (internal consistency, not a datasheet check)
    chk.eq(len(CORE_TABLE), 9, "core table size")
    chk.eq(list_cores()[0], "EE13", "table starts at EE13")
    chk.eq(list_cores()[-1], "EE65", "table ends at EE65")
    aps = [c.ap_cm4 for c in CORE_TABLE]
    chk.true(all(aps[i] < aps[i + 1] for i in range(len(aps) - 1)), "AP strictly increasing")
    chk.close(find_core("ee25").ae_cm2, 0.52, 1e-12, "case-insensitive lookup")
    chk.close(find_core("EE25").ap_cm4, 0.52 * 0.81, 1e-12, "AP = Ae*Aw")
    chk.close(find_core("EE25").ve_cm3, 2.99, 1e-12, "Ve in cm^3")
    chk.close(find_core("EE25").al_ungapped_nh, 2272.6, 1e-3, "ungapped AL from geometry")
    chk.raises(OPL_E_TABLE, find_core, "EE99", _msg="unknown core")
    chk.raises(OPL_E_INPUT, find_core, 42, _msg="non-string core name")
    chk.eq(select_core(0.001).name, "EE13", "small AP -> smallest core")
    chk.eq(select_core(0.14).name, "EE20", "next core up when AP is just over")
    chk.eq(select_core(0.146).name, "EE25", "AP above EE20's 0.1457 cm4 -> EE25")
    chk.eq(select_core(0.4212).name, "EE25", "exact AP of EE25 still selects EE25")
    chk.raises(OPL_E_NOCORE, select_core, 1e9, _msg="AP too large for the table")
    chk.true("3C90-class" in MATERIALS, "Steinmetz material present")

    # wire selection: 0.224 A at 4 A/mm2 = 0.056 mm2 -> AWG29 (0.286 mm), 1 strand
    w1 = pick_wire(0.2243, 4.0, 65e3, 100.0)
    chk.eq(w1.strands, 1, "single strand for the small primary current")
    chk.eq(w1.awg, "AWG29", "AWG29 chosen for 0.056 mm^2")
    chk.close(w1.area_mm2, math.pi / 4 * 0.286 ** 2, 1e-12, "strand area")
    chk.close(w1.d_out_mm, 0.286 * ENAMEL_BUILD_FACTOR, 1e-12, "enamelled diameter")
    chk.true(w1.d_bare_mm <= 2.0 * skin_depth_mm(65e3, 100.0), "strand within 2 skin depths")
    w2 = pick_wire(4.644, 4.0, 65e3, 100.0)
    chk.true(w2.strands >= 5, "large secondary current needs parallel strands")
    chk.true(w2.d_bare_mm <= 2.0 * skin_depth_mm(65e3, 100.0), "secondary strand within 2 delta")
    chk.true(w2.area_mm2 >= 4.644 / 4.0, "secondary copper meets the current density")
    chk.close(w2.area_mm2, w2.strands * math.pi / 4 * w2.d_bare_mm ** 2, 1e-12, "total area")
    w3 = pick_wire(0.01, 4.0, 65e3, 100.0)
    chk.true(w3.area_mm2 >= 0.0025, "tiny current still gets a real wire")
    chk.raises(OPL_E_INPUT, pick_wire, 0.0, 4.0, 65e3, _msg="zero current")
    chk.eq(nearest_awg(0.51)[1], 0.511, "nearest AWG for 0.51 mm")
    chk.close(nearest_awg(0.51)[2], 0.511 * ENAMEL_BUILD_FACTOR, 1e-12, "outer diameter")

    # =====================================================================
    # G. full magnetics design for default_spec
    # =====================================================================
    m = design_magnetics(d)
    chk.close(m.ap_required, 0.124688, 1e-4, "required AP hand value (0.1247 cm4)")
    chk.true(m.ap_margin >= 1.0, "selected core meets the AP requirement")
    chk.true(m.core.ap_cm4 >= m.ap_required, "AP margin >= 1 by construction")
    chk.true(m.bmax <= 0.28 * (1 + 1e-9), "Bmax at or below the 0.28 T target")
    chk.close(m.bmax, 0.28, 0.02, "Bmax close to the target")
    chk.true(m.bmax < 0.32, "Bmax far below saturation (~0.35 T at 100 C)")
    chk.close(
        m.bmax,
        d.lp * (m.n_actual / d.n) * d.ipk / (m.np * m.core.ae_cm2 * 1e-4),
        0.05,
        "Bmax = Lp*Ipk/(Np*Ae) with the integer turns",
    )
    chk.eq(m.ns, int(math.ceil(m.np / d.n - 1e-12)), "Ns = ceil(Np/n)")
    chk.close(m.n_actual, m.np / m.ns, 1e-12, "n_actual = Np/Ns")
    chk.true(m.n_actual <= d.n, "integer rounding only lowers the ratio")
    chk.close(m.vor_actual, m.n_actual * s.vout_ref, 1e-12, "Vor_actual = n_actual*Vout_ref")
    chk.close(m.dmax_actual, m.vor_actual / (VIN_MIN + m.vor_actual), 1e-12, "Dmax_actual")
    chk.true(m.dmax_actual <= s.dmax_limit, "integer build keeps Dmax under the limit")
    chk.true(m.np >= 1 and m.ns >= 1, "turns are positive integers")
    chk.true(float(m.np).is_integer() and float(m.ns).is_integer(), "turns are integers")
    chk.true(m.gap_mm > 0.0, "a positive air gap is needed")
    chk.true(m.ku_actual <= 0.65, "winding fits in the bobbin window")
    chk.true(m.ku_actual > 0.10, "winding actually uses the window")
    chk.close(m.delta_mm, skin_depth_mm(65e3, 100.0), 1e-12, "reported skin depth")
    chk.true(0.0 < m.delta_b <= m.bmax, "AC flux swing is smaller than the peak")
    chk.close(
        m.delta_b,
        m.bmax * (1.0 - d.ip1 / d.ipk),
        0.12,
        "delta_b ~ Bmax*(1-Ip1/Ipk) in CCM",
    )
    chk.true(m.wire_pri.r_ac_ohm >= m.wire_pri.r_dc_ohm, "AC resistance >= DC resistance")
    chk.true(m.wire_sec.r_ac_ohm >= m.wire_sec.r_dc_ohm, "AC resistance >= DC (secondary)")
    chk.eq(m.wire_pri.turns, m.np, "primary wire carries the primary turns")
    chk.eq(m.wire_sec.turns, m.ns, "secondary wire carries the secondary turns")
    chk.close(m.j_pri, d.irms_pri / m.wire_pri.area_mm2, 0.05, "primary current density")
    chk.close(m.j_sec, d.irms_sec / m.wire_sec.area_mm2, 0.05, "secondary current density")
    chk.true(3.0 <= m.j_pri <= 5.0, "primary current density near the 4 A/mm2 target")
    chk.true(3.0 <= m.j_sec <= 5.0, "secondary current density near the 4 A/mm2 target")

    # forced core: a too-small core must be refused, not silently accepted
    chk.raises(
        OPL_E_NOCORE,
        design_magnetics,
        d,
        _msg="EE13 cannot hold this winding",
        core_name="EE13",
    )
    big = design_magnetics(d, core_name="EE42")
    chk.eq(big.core.name, "EE42", "forced core honoured")
    chk.true(big.ap_margin > m.ap_margin, "bigger core has more AP margin")
    chk.true(big.ku_actual < m.ku_actual, "bigger core has a looser fit")
    chk.raises(OPL_E_TABLE, design_magnetics, d, _msg="unknown core", core_name="EE99")
    chk.raises(OPL_E_INPUT, design_magnetics, d, _msg="Bmax target out of range", bmax_target=0.9)

    # DCM magnetics keep the DCM invariant after integer rounding
    md = design_magnetics(dd)
    chk.true(md.n_actual <= dd.n, "DCM integer ratio also rounds down")
    chk.true(md.bmax <= 0.28, "DCM Bmax within target")
    chk.true(md.dmax_actual <= 1.0, "DCM duty sane after rounding")

    # =====================================================================
    # H. stress / derating
    # =====================================================================
    c = Components()
    chk.close(rds_on_hot(1.0, 25.0), 1.0, 1e-12, "Rds(on) at 25 C")
    chk.close(rds_on_hot(1.0, 100.0), 1.75, 1e-12, "Rds(on) 1.75x at 100 C")
    chk.close(rds_on_hot(1.2, 125.0), 1.2 * 2.0, 1e-12, "Rds(on) 2x at 125 C")
    chk.raises(OPL_E_INPUT, rds_on_hot, 0.0, 100.0, _msg="Rds(on)=0")
    chk.close(derating_ratio(8.0, 10.0), 0.8, 1e-12, "ratio hand value")
    chk.raises(OPL_E_INPUT, derating_ratio, 1.0, 0.0, _msg="unrated part")
    chk.close(cap_life_hours(1000.0, 105.0, 65.0), 16000.0, 1e-9, "life doubles per 10 C (4 steps)")
    chk.close(cap_life_hours(5000.0, 105.0, 105.0), 5000.0, 1e-9, "life = rated at rated temp")
    chk.close(cap_life_hours(5000.0, 105.0, 45.0), 5000.0 * 2.0 ** 6, 1e-9, "60 C cooler = 64x")
    chk.close(cap_life_hours(0.0, 105.0, 45.0), 0.0, 1e-12, "unrated cap has no life claim")

    cl = clamp_stress(d, c)
    chk.close(cl["llk"], 0.01 * d.lp, 1e-12, "Llk = leakage_ratio * Lp")
    chk.close(cl["v_spike"], d.ipk * math.sqrt(cl["llk"] / c.clamp_c_f), 1e-12, "spike formula")
    chk.close(cl["p_leak"], 0.5 * cl["llk"] * d.ipk ** 2 * 65e3, 1e-12, "leakage power")
    chk.close(cl["v_clamp"], d.vor + cl["v_spike"], 1e-12, "clamp voltage")
    chk.true(cl["p_clamp"] >= cl["p_leak"], "clamp loss includes the magnetising energy term")
    # synthetic hand check: Ipk=1 A, Llk=100 uH, Cc=1 nF -> 316.2 V spike
    c2 = Components(clamp_c_f=1e-9, leakage_ratio=1e-3)
    chk.close(clamp_stress(d, c2)["v_spike"], d.ipk * math.sqrt(0.001 * d.lp / 1e-9), 1e-12,
              "spike scales with sqrt(Llk/C)")

    mos = mosfet_stress(d, c, 100.0)
    chk.close(mos["vds_ideal"], VIN_MAX + d.vor, 1e-9, "Vds ideal = Vin_max + Vor")
    chk.close(mos["vds_total"], mos["vds_ideal"] + mos["vds_spike"], 1e-12, "Vds includes the spike")
    chk.close(mos["rds_on_hot"], rds_on_hot(c.mosfet_rds_on, 100.0), 1e-12, "hot Rds(on)")
    chk.close(mos["id_pk"], d.ipk, 1e-12, "switch peak current = design Ipk")
    chk.close(mos["id_rms"], d.irms_pri, 1e-12, "switch RMS current = design Irms_pri")
    chk.close(mos["p_cond"], d.irms_pri ** 2 * mos["rds_on_hot"], 1e-12, "conduction loss")
    chk.close(mos["p_gate"], c.mosfet_qg * c.mosfet_vgs * 65e3, 1e-12, "gate drive loss = Qg*Vgs*fsw")
    chk.close(mos["p_coss"], 0.5 * c.mosfet_coss * mos["vds_ideal"] ** 2 * 65e3, 1e-12, "Coss loss")
    chk.close(
        mos["p_sw_off"], 0.5 * mos["vds_ideal"] * d.ipk * c.mosfet_tf * 65e3, 1e-12,
        "turn-off overlap loss",
    )
    chk.close(
        mos["p_sw_on"], 0.5 * mos["vds_ideal"] * d.ip1 * c.mosfet_tr * 65e3, 1e-12,
        "turn-on overlap loss uses Ip1 (CCM)",
    )
    chk.close(
        mos["p_total"],
        mos["p_cond"] + mos["p_sw_on"] + mos["p_sw_off"] + mos["p_coss"] + mos["p_gate"],
        1e-12,
        "total switch loss is the sum of its parts",
    )
    chk.true(mos["p_cond"] > mos["p_gate"], "conduction dominates the gate drive here")

    rect = rectifier_stress(d, c, 100.0)
    chk.close(rect["vr"], 5.0 + VIN_MAX / d.n, 1e-9, "diode reverse voltage")
    chk.close(rect["vr"], 24.8627, 1e-4, "diode Vr hand value (24.86 V)")
    chk.close(rect["if_pk"], d.is_pk, 1e-12, "diode peak current")
    chk.close(rect["if_avg"], d.is_avg, 1e-12, "diode average current")
    chk.close(rect["if_rms"], d.irms_sec, 1e-12, "diode RMS current")
    chk.close(rect["p_dc"], c.diode_vf * d.is_avg, 1e-12, "diode drop loss")
    chk.close(rect["p_rs"], c.diode_rs * d.irms_sec ** 2, 1e-12, "diode series resistance loss")
    chk.true(rect["p_total"] > 0.0, "rectifier dissipates something")
    cs = Components(rectifier_kind="sync", sr_rds_on=0.012)
    rects = rectifier_stress(d, cs, 100.0)
    chk.close(rects["p_dc"], 0.0, 1e-12, "synchronous rectifier has no Vf term")
    chk.close(
        rects["p_total"],
        rds_on_hot(0.012, 100.0) * d.irms_sec ** 2,
        1e-12,
        "SR loss = I^2 * Rds(on)",
    )
    chk.true(rects["p_total"] < rect["p_total"], "SR beats a 0.45 V diode at 3.4 A average")
    chk.raises(OPL_E_INPUT, rectifier_stress, d, Components(rectifier_kind="igbt"),
               _msg="unknown rectifier kind")

    caps = capacitor_stress(d, c, 100.0)
    chk.close(caps["cin_vdc"], VIN_MAX, 1e-9, "bulk cap sees the peak bulk voltage")
    chk.close(caps["cout_vdc"], 5.0, 1e-12, "output cap sees Vout")
    chk.close(caps["cout_irms"], math.sqrt(d.irms_sec ** 2 - 9.0), 1e-9, "Icout_rms identity")
    chk.close(caps["cout_irms"], 3.545554, 1e-4, "Icout_rms hand value (3.545 A)")
    chk.close(caps["cin_irms"], math.sqrt(d.irms_pri ** 2 - d.iin_avg ** 2), 1e-9, "Icin_rms identity")
    chk.close(caps["cout_esr_loss"], caps["cout_irms"] ** 2 * c.cout_esr, 1e-12, "ESR loss")
    chk.close(
        caps["cout_core_c"],
        c.ambient_c + (caps["cout_esr_loss"] / c.cout_n) * c.cout_rth_c_per_w,
        1e-12,
        "core temperature model spreads the ripple over the parallel bank",
    )
    chk.close(caps["cout_esr_loss_per_cap"], caps["cout_esr_loss"] / c.cout_n, 1e-12,
              "per-capacitor ESR loss")
    chk.close(
        caps["cout_life_h"],
        cap_life_hours(c.cout_life_h, c.cout_life_temp_c, caps["cout_core_c"]),
        1e-12,
        "life from the doubling rule",
    )
    chk.true(caps["cout_life_h"] > c.cout_life_h, "cooler than rated -> longer life")

    rep = evaluate_stress(d, c, m)
    chk.true(len(rep.items) >= 9, "derating table has all items")
    names = [it.name for it in rep.items]
    for required in (
        "mosfet_vds",
        "mosfet_id_pk",
        "mosfet_id_rms",
        "mosfet_power",
        "diode_vr",
        "diode_if_avg",
        "diode_power",
        "cap_voltage",
        "cap_ripple",
        "cap_temp",
    ):
        chk.true(required in names, "derating item present: " + required)
    for it in rep.items:
        chk.close(it.ratio, it.actual / it.rated, 1e-12, "ratio = actual/rated for " + it.name)
        chk.close(
            it.margin_pct, (it.limit - it.ratio) / it.limit * 100.0, 1e-9,
            "margin formula for " + it.name,
        )
        chk.eq(it.passed, it.ratio <= it.limit + 1e-12, "verdict for " + it.name)
    chk.eq(rep.passed, len(rep.failed) == 0, "report verdict matches the item list")
    chk.true(not rep.passed, "the default 650 V part set fails at least one derating rule here")
    # the specific failures are engineering findings, not accidents
    vds_item = [it for it in rep.items if it.name == "mosfet_vds"][0]
    chk.true(vds_item.ratio > 0.80, "650 V MOSFET is used above 80 % with this clamp")
    cap_v = [it for it in rep.items if it.name == "cap_voltage"][0]
    chk.close(cap_v.rated, 450.0, 1e-12, "bulk capacitor rating in the part list")
    chk.true(cap_v.ratio > 0.80, "450 V bulk cap fails an 80 % derating rule at 264 VAC")

    # a corrected part set must flip the verdict (positive example)
    c_ok = Components(
        mosfet_vds_rated=800.0,
        cin_v_rated=500.0,
        cout_n=5,
        cout_ripple_rated=1.2,
        rectifier_kind="sync",
        sr_rds_on=0.012,
        sr_vds_rated=60.0,
        clamp_c_f=4.7e-9,
    )
    rep_ok = evaluate_stress(d, c_ok, m)
    name_ratio = dict((it.name, it.ratio) for it in rep_ok.items)
    chk.true(name_ratio["mosfet_vds"] <= 0.80, "800 V part brings Vds back under 80 %")
    chk.true(name_ratio["cap_voltage"] <= 0.80, "500 V bulk cap meets the 80 % rule")
    chk.true(name_ratio["cap_ripple"] <= 0.80, "5 output caps meet the ripple rule")
    chk.true(name_ratio["diode_power"] <= 0.70, "synchronous rectifier meets the power rule")
    chk.true(rep_ok.passed, "corrected part set passes every derating rule")
    chk.true(rep_ok.details["mosfet.vds_spike"] < rep.details["mosfet.vds_spike"],
             "larger clamp capacitor lowers the leakage spike")

    # a deliberately weak part set must fail (negative example)
    c_bad = Components(mosfet_vds_rated=400.0, mosfet_id_rated=0.2, diode_vr_rated=30.0)
    rep_bad = evaluate_stress(d, c_bad, m)
    chk.false(rep_bad.passed, "undersized parts fail the derating check")
    chk.true(len(rep_bad.failed) >= 3, "several undersized items fail")
    chk.raises(OPL_E_INPUT, evaluate_stress, "not a design", c, _msg="wrong design type")

    # =====================================================================
    # I. cross-checks between modules
    # =====================================================================
    chk.close(d.lp * d.ipk, m.np * m.core.ae_cm2 * 1e-4 * m.bmax, 0.02,
              "flux linkage Lp*Ipk = Np*Ae*Bmax")
    chk.true(m.ap_margin > 1.0, "AP margin positive")
    chk.true(m.gap_mm < 1.0, "gap stays manufacturable")
