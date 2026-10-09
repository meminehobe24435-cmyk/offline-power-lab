"""offline-power-lab :: loss breakdown and efficiency budget.

FORMULAS AND UNITS
==================
Every term is in **watts**.  ``Pin = Pout + sum(losses)`` and the predicted
efficiency is ``Pout / Pin`` (a fraction, not a percentage).

MOSFET (conduction, switching overlap, Coss, gate)::

    P_cond  = Irms_pri^2 * Rds_on(Tj)                     Rds(Tj)=Rds(25)*(1+0.01*(Tj-25))
    P_sw_on = 0.5 * Vds_ideal * Ip1 * tr * fsw            (Ip1 = current at turn-on)
    P_sw_off= 0.5 * Vds_ideal * Ipk * tf * fsw
    P_coss  = 0.5 * Coss * Vds_ideal^2 * fsw              (lost in the channel at turn-on)
    P_gate  = Qg * Vgs * fsw

Magnetic core - Steinmetz (``Pv`` in mW/cm^3, ``f`` in kHz, ``B`` in T)::

    Pv = k * f^alpha * B^beta
    P_core = Pv * Ve[cm^3] / 1000                          [W]
    B = delta_B = the peak-to-peak AC flux swing (that is what the core heats with)

Copper - DC plus a skin-effect term::

    P_cu = Irms_pri^2 * Rac_pri + Irms_sec^2 * Rac_sec      [W]
    Rac  = Rdc * (1 + (d/delta)^4/48)                      (skin only, proximity ignored)

Secondary rectifier::

    diode: P = Vf * If_avg + Rs * If_rms^2
    sync : P = If_rms^2 * Rds_on(Tj)

RCD clamp (the leakage energy is burnt there)::

    P_clamp = 0.5 * Llk * Ipk^2 * fsw * V_clamp/(V_clamp - Vor)

Input bridge and feedback::

    P_bridge = bridge_drop * Iin_avg                       (bridge_drop from the spec)
    P_fb     = I_LED*(Vout - Vf_LED) + Vout^2/(R_upper+R_lower)

ACCURACY
--------
The Steinmetz coefficients in :data:`opl.magnetics.MATERIALS` are one
representative fit (±40 %, see the README); the AC resistance ignores proximity
effect (so copper loss is a *lower* bound); the gate-drive and feedback terms
use the datasheet-style values the caller supplies.  Everything is a
**calculation**, never a measurement.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from .errors import OPL_E_INPUT, OPL_E_TABLE, OplError, check_number, require
from .magnetics import MATERIALS
from .model import Components, FlybackDesign, LossBudget, LossItem, MagneticDesign
from .stress import clamp_stress, mosfet_stress, rectifier_stress, rds_on_hot

__all__ = [
    "steinmetz_pv",
    "core_loss_w",
    "copper_loss_w",
    "switch_losses",
    "rectifier_loss_w",
    "bridge_loss_w",
    "feedback_loss_w",
    "loss_budget",
]

DEFAULT_MATERIAL = "3C90-class"

#: TL431 reference/divider values used for the feedback loss term.
TL431_VREF = 2.495
OPTO_LED_VF = 1.10
OPTO_R_LED = 1000.0


def steinmetz_pv(f_khz: float, b_tesla: float, material: str = DEFAULT_MATERIAL) -> float:
    """Steinmetz core loss density in **mW/cm^3**.

    ``Pv = k * f[kHz]^alpha * B[T]^beta`` with the coefficients from
    :data:`opl.magnetics.MATERIALS`.  ``f_khz`` in kHz, ``b_tesla`` in T.

    Raises ``OplError(OPL-E-TABLE)`` for an unknown material.
    """
    f_khz = check_number("f_khz", f_khz, lo=0.0, unit="kHz", lo_inclusive=False)
    b_tesla = check_number("b_tesla", b_tesla, lo=0.0, unit="T", lo_inclusive=False)
    key = material or DEFAULT_MATERIAL
    if key not in MATERIALS:
        raise OplError(
            OPL_E_TABLE,
            "unknown core material {0!r}; available: {1}".format(key, ", ".join(sorted(MATERIALS))),
            "add your vendor's Steinmetz fit to opl.magnetics.MATERIALS",
        )
    coef = MATERIALS[key]
    return coef["k"] * (f_khz ** coef["alpha"]) * (b_tesla ** coef["beta"])


def core_loss_w(
    design: FlybackDesign, mag: MagneticDesign, material: Optional[str] = None
) -> float:
    """Core loss in **W** from the AC flux swing ``mag.delta_b`` and ``Ve``."""
    require(isinstance(mag, MagneticDesign), OPL_E_INPUT, "mag must be a MagneticDesign")
    mat = material or mag.core.material
    if mat not in MATERIALS:
        mat = DEFAULT_MATERIAL
    pv = steinmetz_pv(design.spec.fsw / 1000.0, mag.delta_b, mat)
    return pv * mag.core.ve_cm3 / 1000.0


def copper_loss_w(design: FlybackDesign, mag: MagneticDesign, temp_c: float = 100.0) -> float:
    """Total winding loss in **W** (primary + secondary, AC resistance at fsw).

    Uses the design's RMS currents; the integer-turns build changes them by less
    than a few percent (the magnetic result carries both turn counts, and its own
    ``j_pri``/``j_sec`` show the resulting current densities).
    """
    require(isinstance(mag, MagneticDesign), OPL_E_INPUT, "mag must be a MagneticDesign")
    return design.irms_pri ** 2 * mag.wire_pri.r_ac_ohm + design.irms_sec ** 2 * mag.wire_sec.r_ac_ohm


def switch_losses(
    design: FlybackDesign, comp: Components, temp_c: float = 100.0
) -> Dict[str, float]:
    """MOSFET loss terms in **W**.

    Keys: ``mosfet_cond``, ``mosfet_sw`` (turn-on + turn-off overlap),
    ``mosfet_coss``, ``mosfet_gate``, ``mosfet_total``.
    """
    mos = mosfet_stress(design, comp, temp_c)
    return {
        "mosfet_cond": mos["p_cond"],
        "mosfet_sw": mos["p_sw_on"] + mos["p_sw_off"],
        "mosfet_coss": mos["p_coss"],
        "mosfet_gate": mos["p_gate"],
        "mosfet_total": mos["p_total"],
    }


def rectifier_loss_w(design: FlybackDesign, comp: Components, temp_c: float = 100.0) -> float:
    """Secondary rectifier loss in **W** (diode drop + series R, or SR Rds(on))."""
    return rectifier_stress(design, comp, temp_c)["p_total"]


def bridge_loss_w(design: FlybackDesign, comp: Optional[Components] = None) -> float:
    """Input bridge loss in **W**: ``bridge_drop * Iin_avg``.

    The bridge drop from the specification (1.4 V typ) already represents two
    diode drops in the conduction path.
    """
    return design.spec.bridge_drop * design.iin_avg


def feedback_loss_w(design: FlybackDesign, comp: Components) -> float:
    """Optocoupler LED bias + divider loss in **W**.

    ``I_LED ~ (Vout - Vf_LED - Vka)/R_LED`` (0 when the headroom is negative)
    plus ``Vout^2/(R_upper + R_lower)`` with a 10 k divider designed around
    ``Vref = 2.495 V``.  The controller's own quiescent current is *not* included
    (it is not in :class:`opl.model.Components`).
    """
    vout = design.spec.vout
    head = max(0.0, vout - OPTO_LED_VF - 2.5)
    p_led = (head / OPTO_R_LED) * head
    r_lower = 10.0e3
    r_upper = r_lower * max(0.0, vout / TL431_VREF - 1.0)
    p_div = vout * vout / (r_upper + r_lower) if (r_upper + r_lower) > 0 else 0.0
    return p_led + p_div


def loss_budget(
    design: FlybackDesign,
    comp: Components,
    mag: MagneticDesign,
    temp_c: float = 100.0,
    material: Optional[str] = None,
) -> LossBudget:
    """Itemised loss budget, predicted efficiency and the dominant loss.

    Parameters
    ----------
    design, comp, mag : the pipeline objects.
    temp_c : float  Winding/junction temperature used for the resistance terms, **degC**.
    material : str or None  Override the Steinmetz material of the core.

    Returns
    -------
    :class:`opl.model.LossBudget` - ``efficiency`` is a fraction,
    ``gap_pct_points`` is ``eta_target - efficiency`` in percentage points, and
    ``dominant`` names the largest single loss term (which is where the
    optimisation effort belongs).
    """
    require(isinstance(design, FlybackDesign), OPL_E_INPUT, "design must be a FlybackDesign")
    require(isinstance(mag, MagneticDesign), OPL_E_INPUT, "mag must be a MagneticDesign")

    sw = switch_losses(design, comp, temp_c)
    p_core = core_loss_w(design, mag, material)
    p_cu = copper_loss_w(design, mag, temp_c)
    p_rect = rectifier_loss_w(design, comp, temp_c)
    clamp = clamp_stress(design, comp)
    p_clamp = clamp["p_clamp"]
    p_bridge = bridge_loss_w(design, comp)
    p_fb = feedback_loss_w(design, comp)

    pout = design.spec.pout
    items: List[LossItem] = []

    def add(name: str, value: float, formula: str) -> None:
        items.append(LossItem(name=name, value_w=value, pct=0.0, formula=formula))

    add(
        "mosfet_cond",
        sw["mosfet_cond"],
        "Irms_pri^2*Rds_hot = {0:.4f}^2*{1:.3f}".format(design.irms_pri, sw["mosfet_cond"] / max(design.irms_pri ** 2, 1e-12)),
    )
    add(
        "mosfet_sw",
        sw["mosfet_sw"],
        "0.5*Vds*(Ip1*tr+Ipk*tf)*fsw, Vds={0:.1f} V".format(design.vin_dc_max + design.vor),
    )
    add("mosfet_coss", sw["mosfet_coss"], "0.5*Coss*Vds^2*fsw")
    add("mosfet_gate", sw["mosfet_gate"], "Qg*Vgs*fsw")
    add(
        "core",
        p_core,
        "Pv(f={0:.0f} kHz, B={1:.4f} T)*Ve({2:.2f} cm3)".format(
            design.spec.fsw / 1000.0, mag.delta_b, mag.core.ve_cm3
        ),
    )
    add(
        "copper",
        p_cu,
        "Irms_pri^2*Rac_pri + Irms_sec^2*Rac_sec = {0:.4f}^2*{1:.3f} + {2:.4f}^2*{3:.5f}".format(
            design.irms_pri, mag.wire_pri.r_ac_ohm, design.irms_sec, mag.wire_sec.r_ac_ohm
        ),
    )
    add(
        "rectifier",
        p_rect,
        ("Vf*If_avg + Rs*If_rms^2" if (comp.rectifier_kind or "diode").lower() == "diode" else "If_rms^2*Rds_on(SR)")
        + " = {0:.4f} W".format(p_rect),
    )
    add(
        "clamp",
        p_clamp,
        "0.5*Llk*Ipk^2*fsw*Vc/(Vc-Vor), Llk={0:.1f} uH".format(clamp["llk"] * 1e6),
    )
    add("bridge", p_bridge, "bridge_drop*Iin_avg = {0:.2f}*{1:.4f}".format(design.spec.bridge_drop, design.iin_avg))
    add("feedback", p_fb, "I_LED*(Vout-Vf_LED) + Vout^2/(R1+R2)")

    total = sum(it.value_w for it in items)
    for it in items:
        it.pct = (it.value_w / total * 100.0) if total > 0 else 0.0
    dominant = max(items, key=lambda it: it.value_w).name if items else ""

    efficiency = pout / (pout + total) if (pout + total) > 0 else 0.0
    eta_target = design.spec.eta_target
    gap = (eta_target - efficiency) * 100.0

    warnings: List[str] = []
    if efficiency < eta_target:
        warnings.append(
            "predicted efficiency {0:.1f} % is {1:.1f} points below the {2:.1f} % "
            "target; the largest term is {3} ({4:.2f} W, {5:.0f} % of the total)".format(
                efficiency * 100.0, gap, eta_target * 100.0, dominant,
                max(items, key=lambda it: it.value_w).value_w,
                max(items, key=lambda it: it.value_w).pct,
            )
        )
    if dominant and max(it.pct for it in items) > 40.0:
        warnings.append(
            "{0} alone is {1:.0f} % of all losses - fix that term first".format(
                dominant, max(it.pct for it in items)
            )
        )
    if material is not None and material not in MATERIALS:
        warnings.append(
            "unknown material {0!r}; the {1} fit was used instead".format(material, DEFAULT_MATERIAL)
        )

    return LossBudget(
        items=items,
        total_w=total,
        pout_w=pout,
        pin_w=pout + total,
        efficiency=efficiency,
        eta_target=eta_target,
        gap_pct_points=gap,
        dominant=dominant,
        warnings=warnings,
    )
