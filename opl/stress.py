"""offline-power-lab :: component stress and derating verification.

FORMULAS AND UNITS  (SI unless stated)
=====================================
Worst-case voltages
    Vds_ideal = Vin_max + Vor                        [V]
        (the switch sees the bulk peak plus the reflected voltage; the leakage
        spike comes on top of that)
    Vds_total = Vds_ideal + V_spike                  [V]
RCD clamp / leakage spike (energy-balance estimate):
    Llk       = leakage_ratio * Lp                   [H]
    V_spike   = Ipk * sqrt(Llk / Cclamp)             [V]
    V_clamp   = Vor + V_spike                        [V]
    P_clamp   = 0.5 * Llk * Ipk^2 * fsw * V_clamp/(V_clamp - Vor)   [W]
        The factor ``V_clamp/(V_clamp - Vor)`` accounts for the energy the clamp
        also takes out of the magnetising inductance while the spike is being
        absorbed; ``0.5*Llk*Ipk^2*fsw`` alone is the pure leakage term.

MOSFET
    Rds_on(Tj) = Rds_on(25C) * (1 + 0.010 * (Tj - 25))     [ohm]  (linear fit of
        a typical normalised Rds(on)-vs-temperature curve, ~1.75x at 100 C)
    P_cond     = Irms_pri^2 * Rds_on(Tj)                    [W]
    P_sw_on    = 0.5 * Vds_ideal * Ip1 * tr * fsw           [W]
    P_sw_off   = 0.5 * Vds_ideal * Ipk * tf * fsw           [W]
    P_coss     = 0.5 * Coss * Vds_ideal^2 * fsw             [W] (dissipated in
        the channel at turn-on; Coss(V) is taken as constant - a datasheet
        Coss(25 V)-style value)
    P_gate     = Qg * Vgs * fsw                             [W]
    P_total    = P_cond + P_sw_on + P_sw_off + P_coss + P_gate

Secondary rectifier
    diode:  Vr = Vout + Vin_max/n                           [V]
            If_pk  = Is_pk, If_avg = Is_avg, If_rms = Isec_rms   [A]
            P = Vf*If_avg + Rs*If_rms^2                     [W]
    sync:   Vr = Vin_max/n   (plus the ringing allowance)
            P = If_rms^2 * Rds_on(Tj)                       [W]

Capacitors
    Bulk (input): Cin is charged every half line cycle, so its low-frequency
        ripple is estimated as ``Vpp ~= Iin_avg / (2*pi*f_line*Cin)`` and the
        high-frequency RMS current from the pulsed switch current:
        ``Icin_rms ~= sqrt(Ipri_rms^2 - Iin_avg^2)``.
        Life: ``L = L_rated * 2^((T_max - T_core)/10) * (V_rated/V_applied)^-1``... 
        (only the temperature term is used here):
        ``T_core = Tambient + P_esr * Rth_ca``, ``Lx = L_rated * 2^((Tmax-Tcore)/10)``
    Output: ``Icout_rms = sqrt(Isec_rms^2 - Iout^2)``,
        ``P_esr = Icout_rms^2 * ESR``, same life model.

Derating: every item is compared with an explicit rule from
:data:`opl.model.DEFAULT_DERATING_RULES` (``ratio = actual/rated`` must be
``<= limit``).  A failing item is **reported**, never raised - the point of the
tool is to show the margin, not to hide it.

QUANTITIES ARE ESTIMATES
------------------------
Every number here comes from the formulas above plus the device parameters the
caller supplies in :class:`opl.model.Components`.  There is no measurement
behind them (see the README "Boundaries" section).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

from .errors import OPL_E_INPUT, OplError, check_number, require
from .flyback import trapezoid_rms
from .model import (
    DEFAULT_DERATING_RULES,
    Components,
    DeratingRule,
    FlybackDesign,
    MagneticDesign,
    StressItem,
    StressReport,
)

__all__ = [
    "derating_ratio",
    "rds_on_hot",
    "clamp_stress",
    "mosfet_stress",
    "rectifier_stress",
    "capacitor_stress",
    "cap_life_hours",
    "evaluate_stress",
]

TWO_PI = 2.0 * math.pi


def derating_ratio(actual: float, rated: float) -> float:
    """``actual / rated``, dimensionless.

    Raises ``OPL-E-INPUT`` for a non-positive rating (an unrated part cannot be
    checked, and silently returning 0 would hide a design error).
    """
    rated = check_number("rated", rated, lo=0.0, unit="-", lo_inclusive=False)
    actual = check_number("actual", actual, lo=0.0, unit="-")
    return actual / rated


def rds_on_hot(rds_on_25: float, temp_c: float) -> float:
    """Hot ``Rds(on)`` in **ohm** from the 25 C value and the junction temp.

    Linear approximation ``Rds(T) = Rds(25) * (1 + 0.010*(T-25))``.
    """
    rds_on_25 = check_number("rds_on_25", rds_on_25, lo=0.0, unit="ohm", lo_inclusive=False)
    temp_c = check_number("temp_c", temp_c, lo=-55.0, hi=200.0, unit="degC")
    return rds_on_25 * (1.0 + 0.010 * (temp_c - 25.0))


# ---------------------------------------------------------------------------
# clamp
# ---------------------------------------------------------------------------


def clamp_stress(design: FlybackDesign, comp: Components) -> Dict[str, float]:
    """RCD clamp / leakage spike estimates.

    Returns a dict with ``llk`` [H], ``v_spike`` [V], ``v_clamp`` [V],
    ``p_clamp`` [W], ``p_leak`` [W] (the pure ``0.5*Llk*Ipk^2*fsw`` term) and
    ``energy_leak`` [J].
    """
    require(isinstance(design, FlybackDesign), OPL_E_INPUT, "design must be a FlybackDesign")
    llk = comp.leakage_ratio * design.lp
    v_spike = design.ipk * math.sqrt(llk / comp.clamp_c_f) if comp.clamp_c_f > 0 else 0.0
    v_clamp = design.vor + v_spike
    e_leak = 0.5 * llk * design.ipk ** 2
    p_leak = e_leak * design.spec.fsw
    if v_clamp > design.vor:
        factor = v_clamp / (v_clamp - design.vor)
    else:  # pragma: no cover - structurally impossible
        factor = 1.0
    return {
        "llk": llk,
        "v_spike": v_spike,
        "v_clamp": v_clamp,
        "energy_leak": e_leak,
        "p_leak": p_leak,
        "p_clamp": p_leak * factor,
        "clamp_factor": factor,
        "clamp_tau": comp.clamp_r_ohm * comp.clamp_c_f,
    }


# ---------------------------------------------------------------------------
# MOSFET
# ---------------------------------------------------------------------------


def mosfet_stress(
    design: FlybackDesign, comp: Components, temp_c: float = 100.0, mag: Optional[MagneticDesign] = None
) -> Dict[str, float]:
    """MOSFET voltage/current stress and dissipation in W.

    ``temp_c`` is the assumed junction temperature in **degC** for Rds(on).
    ``mag`` (optional) lets the leak/spike use the *build* inductance; unused
    here because the clamp is dominated by ``Llk`` and ``Ipk``.

    Keys: ``vds_ideal``, ``vds_spike``, ``vds_total`` [V]; ``id_pk``, ``id_rms``
    [A]; ``rds_on_hot`` [ohm]; ``p_cond``, ``p_sw_on``, ``p_sw_off``,
    ``p_coss``, ``p_gate``, ``p_total`` [W].
    """
    clamp = clamp_stress(design, comp)
    vds_ideal = design.vin_dc_max + design.vor
    vds_total = vds_ideal + clamp["v_spike"]
    r_hot = rds_on_hot(comp.mosfet_rds_on, temp_c)

    ipk = design.ipk
    id_rms = design.irms_pri
    p_cond = id_rms ** 2 * r_hot
    p_sw_on = 0.5 * vds_ideal * design.ip1 * comp.mosfet_tr * design.spec.fsw
    p_sw_off = 0.5 * vds_ideal * ipk * comp.mosfet_tf * design.spec.fsw
    p_coss = 0.5 * comp.mosfet_coss * vds_ideal ** 2 * design.spec.fsw
    p_gate = comp.mosfet_qg * comp.mosfet_vgs * design.spec.fsw
    return {
        "vds_ideal": vds_ideal,
        "vds_spike": clamp["v_spike"],
        "vds_total": vds_total,
        "id_pk": ipk,
        "id_rms": id_rms,
        "rds_on_hot": r_hot,
        "p_cond": p_cond,
        "p_sw_on": p_sw_on,
        "p_sw_off": p_sw_off,
        "p_coss": p_coss,
        "p_gate": p_gate,
        "p_total": p_cond + p_sw_on + p_sw_off + p_coss + p_gate,
        "tj_est": comp.ambient_c + (p_cond + p_sw_on + p_sw_off + p_coss) * comp.mosfet_rth_jc,
    }


# ---------------------------------------------------------------------------
# rectifier
# ---------------------------------------------------------------------------


def rectifier_stress(
    design: FlybackDesign, comp: Components, temp_c: float = 100.0
) -> Dict[str, float]:
    """Secondary rectifier stress and dissipation.

    Returns keys ``kind`` is reported separately by the caller; the dict has
    ``vr`` [V], ``if_pk``, ``if_avg``, ``if_rms`` [A], ``p_dc``, ``p_rs``,
    ``p_total`` [W].
    """
    kind = (comp.rectifier_kind or "diode").strip().lower()
    if kind not in ("diode", "sync"):
        raise OplError(
            OPL_E_INPUT,
            "rectifier_kind must be 'diode' or 'sync', got {0!r}".format(comp.rectifier_kind),
        )
    # off-state voltage: for the diode the full secondary voltage plus the
    # reflected input; for a synchronous switch the same (it must block while
    # the primary conducts).
    vr = design.spec.vout + design.vin_dc_max / design.n
    if_pk = design.is_pk
    if_avg = design.is_avg
    if_rms = design.irms_sec
    if kind == "diode":
        p_dc = comp.diode_vf * if_avg
        p_rs = comp.diode_rs * if_rms ** 2
    else:
        p_dc = 0.0
        p_rs = rds_on_hot(comp.sr_rds_on, temp_c) * if_rms ** 2
    return {
        "vr": vr,
        "if_pk": if_pk,
        "if_avg": if_avg,
        "if_rms": if_rms,
        "p_dc": p_dc,
        "p_rs": p_rs,
        "p_total": p_dc + p_rs,
    }


# ---------------------------------------------------------------------------
# capacitors
# ---------------------------------------------------------------------------


def cap_life_hours(
    life_rated_h: float,
    temp_rated_c: float,
    core_temp_c: float,
) -> float:
    """Electrolytic life estimate in **hours**.

    ``L = L_rated * 2^((T_rated - T_core)/10)`` - the standard Arrhenius-style
    doubling rule for aluminium electrolytics (a 10 C drop doubles the life,
    and a core hotter than the rated temperature *shortens* it).
    """
    life_rated_h = check_number("life_rated_h", life_rated_h, lo=0.0, hi=1.0e8, unit="h")
    if life_rated_h <= 0.0:
        return 0.0
    return life_rated_h * 2.0 ** ((temp_rated_c - core_temp_c) / 10.0)


def capacitor_stress(
    design: FlybackDesign, comp: Components, temp_c: float = 100.0
) -> Dict[str, float]:
    """Input/output capacitor ripple and life estimates.

    Keys: ``cin_vdc`` [V], ``cin_ripple_pp`` [V], ``cin_irms`` [A],
    ``cin_esr_loss`` [W], ``cout_vdc`` [V], ``cout_irms`` [A],
    ``cout_esr_loss`` [W], ``cout_core_c`` [degC], ``cout_life_h`` [h],
    ``cin_life_h`` [h].
    """
    f_line = design.spec.line_freq
    cin = comp.cin_cap_f
    cout = comp.cout_cap_f

    # --- input bulk capacitor: low-frequency valley + HF pulsed current -----
    cin_vdc = design.vin_dc_max
    iin_avg = design.pin / design.vin_dc_min
    cin_ripple_pp = iin_avg / (TWO_PI * f_line * cin) if cin > 0 else float("inf")
    hf = design.irms_pri ** 2 - iin_avg ** 2
    cin_irms = math.sqrt(hf) if hf > 0 else 0.0
    cin_esr_loss = cin_irms ** 2 * comp.cin_esr

    # --- output capacitor ---------------------------------------------------
    cout_vdc = design.spec.vout
    rms2 = design.irms_sec ** 2 - design.spec.iout ** 2
    cout_irms = math.sqrt(rms2) if rms2 > 0 else 0.0
    cout_esr_total = comp.cout_esr
    cout_esr_loss = cout_irms ** 2 * cout_esr_total
    cout_core_c = comp.ambient_c + cout_esr_loss * comp.cout_rth_c_per_w
    cout_life_h = cap_life_hours(
        comp.cout_life_h, comp.cout_life_temp_c, cout_core_c
    )
    # the bulk cap is rated for the same endurance class in this tool
    cin_life_h = cap_life_hours(
        comp.cout_life_h, comp.cout_life_temp_c, comp.ambient_c + cin_esr_loss * comp.cout_rth_c_per_w
    )
    return {
        "cin_vdc": cin_vdc,
        "cin_ripple_pp": cin_ripple_pp,
        "cin_irms": cin_irms,
        "cin_esr_loss": cin_esr_loss,
        "cin_life_h": cin_life_h,
        "cout_vdc": cout_vdc,
        "cout_irms": cout_irms,
        "cout_esr_loss": cout_esr_loss,
        "cout_core_c": cout_core_c,
        "cout_life_h": cout_life_h,
        "cout_ripple_rated_total": comp.cout_ripple_rated * comp.cout_n,
    }


# ---------------------------------------------------------------------------
# derating table assembly
# ---------------------------------------------------------------------------


def _item(
    name: str,
    actual: float,
    rated: float,
    unit: str,
    limit: float,
    note: str = "",
) -> StressItem:
    ratio = derating_ratio(actual, rated) if rated > 0 else float("inf")
    margin = (limit - ratio) / limit * 100.0 if limit > 0 else 0.0
    return StressItem(
        name=name,
        actual=actual,
        rated=rated,
        unit=unit,
        limit=limit,
        ratio=ratio,
        margin_pct=margin,
        passed=ratio <= limit + 1e-12,
        note=note,
    )


def _limit_for(rules: Sequence[DeratingRule], quantity: str, default: float = 0.80) -> float:
    for rule in rules:
        if rule.quantity == quantity:
            return rule.limit
    return default


def evaluate_stress(
    design: FlybackDesign,
    comp: Components,
    mag: Optional[MagneticDesign] = None,
    rules: Sequence[DeratingRule] = DEFAULT_DERATING_RULES,
    temp_c: float = 100.0,
) -> StressReport:
    """Build the full actual/rated/margin/verdict derating table.

    Parameters
    ----------
    design : FlybackDesign
    comp : Components
        Ratings and parasitics of the chosen parts.
    mag : MagneticDesign or None
        Included in the result's ``details`` when given (copper loss is checked
        by :mod:`opl.budget`, not here).
    rules : sequence of :class:`DeratingRule`
        The explicit rule table; edit or replace it to match your own company
        guideline.  Unknown quantities fall back to 80 %.
    temp_c : float
        Assumed junction/winding temperature in **degC**.

    Returns
    -------
    :class:`StressReport` - never raises for a failing check.
    """
    require(isinstance(design, FlybackDesign), OPL_E_INPUT, "design must be a FlybackDesign")
    require(isinstance(comp, Components), OPL_E_INPUT, "comp must be a Components")

    mos = mosfet_stress(design, comp, temp_c)
    rect = rectifier_stress(design, comp, temp_c)
    caps = capacitor_stress(design, comp, temp_c)
    clamp = clamp_stress(design, comp)

    items: List[StressItem] = []
    items.append(
        _item(
            "mosfet_vds",
            mos["vds_total"],
            comp.mosfet_vds_rated,
            "V",
            _limit_for(rules, "mosfet_vds"),
            note="{0:.1f} V ideal + {1:.1f} V leakage spike".format(
                mos["vds_ideal"], mos["vds_spike"]
            ),
        )
    )
    items.append(
        _item(
            "mosfet_id_pk",
            mos["id_pk"],
            comp.mosfet_id_pulse,
            "A",
            _limit_for(rules, "mosfet_id_pk"),
            note="pulsed rating",
        )
    )
    items.append(
        _item(
            "mosfet_id_rms",
            mos["id_rms"],
            comp.mosfet_id_rated,
            "A",
            _limit_for(rules, "mosfet_id_rms"),
            note="continuous rating",
        )
    )
    items.append(
        _item(
            "mosfet_power",
            mos["p_total"],
            comp.mosfet_power_rated,
            "W",
            _limit_for(rules, "mosfet_power"),
            note="allowed dissipation from the thermal budget ({0:.1f} K/W J-C)".format(
                comp.mosfet_rth_jc
            ),
        )
    )

    if (comp.rectifier_kind or "diode").strip().lower() == "diode":
        items.append(
            _item(
                "diode_vr",
                rect["vr"],
                comp.diode_vr_rated,
                "V",
                _limit_for(rules, "diode_vr"),
                note="Vout + Vin_max/n",
            )
        )
        items.append(
            _item(
                "diode_if_avg",
                rect["if_avg"],
                comp.diode_if_rated,
                "A",
                _limit_for(rules, "diode_if_avg"),
                note="average forward current",
            )
        )
    else:
        items.append(
            _item(
                "diode_vr",
                rect["vr"],
                comp.sr_vds_rated,
                "V",
                _limit_for(rules, "diode_vr"),
                note="synchronous rectifier Vds rating",
            )
        )
    items.append(
        _item(
            "diode_power",
            rect["p_total"],
            comp.diode_power_rated,
            "W",
            _limit_for(rules, "diode_power"),
            note="allowed dissipation for the rectifier package",
        )
    )

    items.append(
        _item(
            "cap_voltage",
            caps["cin_vdc"],
            comp.cin_v_rated,
            "V",
            _limit_for(rules, "cap_voltage"),
            note="bulk capacitor at vac_max (no load)",
        )
    )
    items.append(
        _item(
            "cap_ripple",
            caps["cout_irms"],
            comp.cout_ripple_rated * comp.cout_n,
            "A",
            _limit_for(rules, "cap_ripple"),
            note="{0} x {1:.1f} A output caps in parallel".format(
                comp.cout_n, comp.cout_ripple_rated
            ),
        )
    )
    tmax_limit_c = 0.90 * comp.cout_life_temp_c
    items.append(
        _item(
            "cap_temp",
            caps["cout_core_c"],
            tmax_limit_c,
            "degC",
            0.90,
            note="core temperature, life rated at {0:.0f} C".format(comp.cout_life_temp_c),
        )
    )

    details: Dict[str, float] = {}
    for key, val in mos.items():
        details["mosfet." + key] = val
    for key, val in rect.items():
        details["rect." + key] = val
    for key, val in caps.items():
        details["caps." + key] = val
    for key, val in clamp.items():
        details["clamp." + key] = val
    if mag is not None:
        details["mag.bmax"] = mag.bmax
        details["mag.gap_mm"] = mag.gap_mm
        details["mag.ku_actual"] = mag.ku_actual
        details["mag.p_cu_w"] = (
            design.irms_pri ** 2 * mag.wire_pri.r_ac_ohm
            + design.irms_sec ** 2 * mag.wire_sec.r_ac_ohm
        )
    details["pout_w"] = design.spec.pout
    details["pin_assumed_w"] = design.spec.pin

    warnings: List[str] = []
    if not comp.rectifier_kind:
        warnings.append("rectifier_kind empty; assumed 'diode'")
    if mos["tj_est"] > 125.0:
        warnings.append(
            "estimated junction temperature {0:.1f} C exceeds 125 C screening "
            "limit".format(mos["tj_est"])
        )

    return StressReport(items=items, details=details, warnings=warnings)
