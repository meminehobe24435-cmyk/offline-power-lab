"""offline-power-lab :: transformer / inductor design (AP method).

FORMULAS AND UNITS  (SI unless stated)
=====================================
Area-product (AP) method - sizes the core from the stored energy and the
copper area it needs:

    N        = L * Ipk / (Bmax * Ae)                  [turns]
    Aw_cu    = N * Irms / J                           [window area of copper]
    Aw       = Aw_cu / Ku                             [total window area]
    AP       = Ae * Aw = L*Ipk*Irms / (Ku*Bmax*J)     [m^4]
    AP[cm^4] = L[H]*Ipk[A]*Irms[A] / (Ku*Bmax[T]*J[A/cm^2]) * 1e4

``L`` is the primary inductance in H, ``Ipk`` the peak (not RMS) current in A
(that is what sets Bmax), ``Irms`` the winding RMS current in A, ``Ku`` the
window utilisation factor (~0.35 for a hand-wound bobbin), ``Bmax`` the flux
density target in T and ``J`` the current density in A/cm^2 (= A/mm^2 * 100).

Flux density / saturation check:

    Bmax = L * Ipk / (Np * Ae)                        [T]

Air gap (the gap is what makes Lp independent of the ferrite's permeability):

    L    = mu0 * Np^2 * Ae / (lg + le/mu_r)           [H]
    lg   = mu0 * Np^2 * Ae / Lp - le/mu_r             [m]   (>= 0 required)

with ``mu0 = 4*pi*1e-7 H/m`` and ``mu_r ~ 2000`` for a MnZn power ferrite.
A negative result means the ungapped core already stores more than Lp: the
turn count is too low and must be raised.

Skin depth (copper, so that a strand is not wastefully thick):

    delta(T) = 66.1 mm * sqrt(rho(T)/rho(20C)) / sqrt(f[Hz])
             = 66.1/sqrt(f) mm at 20 C, 75.7/sqrt(f) mm at 100 C

Practical rule used here: strand **diameter** <= 2*delta (one skin depth per
radial direction).  When the required copper area cannot be reached with such a
strand, several strands are put in parallel (Litz-style).

Window utilisation actually achieved:

    Ku = (Np * A_out_pri + Ns * A_out_sec) / Aw         [-]

where ``A_out_*`` is the *outer* (enamelled) area per turn, defined from the
strand count x outer strand diameter.

THE CORE TABLE IS A REFERENCE SUBSET
------------------------------------
:data:`CORE_TABLE` lists common E/EE ferrite cores with typical published
geometry (Ae, Aw, le, Ve) and a typical bobbin MLT.  Values are rounded to three
significant digits and are meant for **selection and sanity checking only**:
they are not a substitute for the vendor datasheet of the exact core half and
bobbin you intend to buy.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from .errors import (
    OPL_E_INPUT,
    OPL_E_NOCORE,
    OPL_E_RANGE,
    OPL_E_TABLE,
    OplError,
    check_choice,
    check_number,
    require,
)
from .flyback import duty_from_vor, trapezoid_rms
from .model import CoreSpec, DesignSpec, FlybackDesign, MagneticDesign, WireSpec

__all__ = [
    "CORE_TABLE",
    "MATERIALS",
    "AWG_TABLE",
    "ENAMEL_BUILD_FACTOR",
    "find_core",
    "list_cores",
    "required_ap",
    "select_core",
    "skin_depth_mm",
    "nearest_awg",
    "pick_wire",
    "gap_mm_for_lp",
    "bmax_of",
    "design_magnetics",
]

MU0 = 4.0e-7 * math.pi  # H/m
RHO_CU_20 = 1.724e-8  # ohm*m at 20 C
ALPHA_CU = 0.00393  # 1/K

#: Enamelled outer diameter / bare diameter.  1.10 is a typical grade-1 build
#: for the wire sizes used here (0.1 .. 1.0 mm).
ENAMEL_BUILD_FACTOR = 1.10

#: Steinmetz coefficients ``Pv[mW/cm3] = k * f[kHz]^alpha * B[T]^beta`` for a
#: 3C90-class MnZn power ferrite.  Fitted to representative published loss
#: curves around 100 C (anchors: ~80 kW/m3 at 25 kHz / 200 mT and
#: ~155 kW/m3 at 100 kHz / 100 mT).  Expect +/- 40 %: replace with your
#: vendor's Pv data (or an iGSE fit) before making a thermal decision.
MATERIALS: Dict[str, Dict[str, float]] = {
    "3C90-class": {
        "k": 17.3,
        "alpha": 1.53,
        "beta": 2.11,
        "f_min_khz": 20.0,
        "f_max_khz": 200.0,
        "b_min_t": 0.05,
        "b_max_t": 0.20,
        "ref_temp_c": 100.0,
    },
}

#: AWG -> bare copper diameter in mm (standard values).
AWG_TABLE: Tuple[Tuple[str, float], ...] = (
    ("AWG16", 1.291),
    ("AWG17", 1.149),
    ("AWG18", 1.024),
    ("AWG19", 0.912),
    ("AWG20", 0.812),
    ("AWG21", 0.723),
    ("AWG22", 0.644),
    ("AWG23", 0.573),
    ("AWG24", 0.511),
    ("AWG25", 0.455),
    ("AWG26", 0.405),
    ("AWG27", 0.361),
    ("AWG28", 0.321),
    ("AWG29", 0.286),
    ("AWG30", 0.255),
    ("AWG31", 0.227),
    ("AWG32", 0.202),
    ("AWG33", 0.180),
    ("AWG34", 0.160),
    ("AWG35", 0.143),
    ("AWG36", 0.127),
    ("AWG37", 0.113),
    ("AWG38", 0.101),
    ("AWG39", 0.0897),
    ("AWG40", 0.0799),
)


def _core(
    name: str,
    ae_mm2: float,
    aw_mm2: float,
    le_mm: float,
    ve_mm3: float,
    mlt_cm: float,
    ur: float = 2000.0,
) -> CoreSpec:
    """Build a :class:`CoreSpec` and fill in the ungapped AL from geometry."""
    ae_cm2 = ae_mm2 / 100.0
    le_cm = le_mm / 10.0
    al = MU0 * ur * (ae_mm2 * 1e-6) / (le_mm * 1e-3) * 1e9  # nH per turn^2
    return CoreSpec(
        name=name,
        ae_cm2=ae_cm2,
        aw_cm2=aw_mm2 / 100.0,
        le_cm=le_cm,
        ve_cm3=ve_mm3 / 1000.0,
        mlt_cm=mlt_cm,
        material="3C90-class",
        al_ungapped_nh=al,
    )


#: Built-in core table - a **reference subset** of common E/EE ferrite cores.
#: (name, Ae[mm2], Aw[mm2], le[mm], Ve[mm3], typical bobbin MLT[cm])
CORE_TABLE: Tuple[CoreSpec, ...] = (
    _core("EE13", 12.1, 21.0, 30.2, 366.0, 2.7),
    _core("EE16", 20.1, 32.0, 37.6, 756.0, 3.3),
    _core("EE20", 31.0, 47.0, 45.1, 1400.0, 3.9),
    _core("EE25", 52.0, 81.0, 57.5, 2990.0, 4.9),
    _core("EE30", 60.0, 120.0, 67.0, 4020.0, 5.6),
    _core("EE35", 101.0, 173.0, 79.0, 7980.0, 6.6),
    _core("EE42", 178.0, 275.0, 97.0, 17300.0, 7.9),
    _core("EE55", 354.0, 508.0, 124.0, 43900.0, 9.6),
    _core("EE65", 532.0, 780.0, 147.0, 78200.0, 11.5),
)


def list_cores() -> List[str]:
    """Names of the cores in the built-in table (ascending AP order)."""
    return [c.name for c in CORE_TABLE]


def find_core(name: str) -> CoreSpec:
    """Look up a core by name (case-insensitive).

    Raises ``OplError(OPL-E-TABLE)`` when the name is not in the table.
    """
    if not isinstance(name, str):
        raise OplError(OPL_E_INPUT, "core name must be a string, got {0!r}".format(name))
    key = name.strip().upper()
    for core in CORE_TABLE:
        if core.name.upper() == key:
            return core
    raise OplError(
        OPL_E_TABLE,
        "unknown core {0!r}; available: {1}".format(name, ", ".join(list_cores())),
    )


# ---------------------------------------------------------------------------
# AP method
# ---------------------------------------------------------------------------


def required_ap(
    lp: float,
    ipk: float,
    irms: float,
    bmax: float,
    ku: float,
    j_a_per_mm2: float,
) -> float:
    """Required area product in **cm^4**.

    ``lp`` H, ``ipk`` A (peak, sets Bmax), ``irms`` A (RMS, sets the copper
    area), ``bmax`` T, ``ku`` dimensionless in (0, 1), ``j_a_per_mm2`` A/mm^2
    (= A/cm^2 / 100).
    """
    lp = check_number("lp", lp, lo=0.0, unit="H", lo_inclusive=False)
    ipk = check_number("ipk", ipk, lo=0.0, unit="A", lo_inclusive=False)
    irms = check_number("irms", irms, lo=0.0, unit="A", lo_inclusive=False)
    bmax = check_number("bmax", bmax, lo=0.0, unit="T", lo_inclusive=False)
    ku = check_number("ku", ku, lo=0.0, hi=1.0, unit="-", lo_inclusive=False)
    j = check_number("j_a_per_mm2", j_a_per_mm2, lo=0.0, unit="A/mm2", lo_inclusive=False)
    j_a_per_cm2 = j * 100.0
    return lp * ipk * irms / (ku * bmax * j_a_per_cm2) * 1e4


def select_core(ap_cm4: float, min_ae_cm2: float = 0.0) -> CoreSpec:
    """Smallest table core whose ``Ae * Aw`` is >= ``ap_cm4`` (cm^4).

    Raises ``OplError(OPL-E-NOCORE)`` when no core is large enough.
    """
    ap_cm4 = check_number("ap_cm4", ap_cm4, lo=0.0, unit="cm4")
    min_ae_cm2 = check_number("min_ae_cm2", min_ae_cm2, lo=0.0, unit="cm2")
    for core in CORE_TABLE:
        if core.ap_cm4 >= ap_cm4 and core.ae_cm2 >= min_ae_cm2:
            return core
    raise OplError(
        OPL_E_NOCORE,
        "no core in the table reaches AP={0:.4g} cm^4 (largest is {1}, "
        "{2:.4g} cm^4)".format(ap_cm4, CORE_TABLE[-1].name, CORE_TABLE[-1].ap_cm4),
        "lower Bmax target or accept a lower current density",
    )


# ---------------------------------------------------------------------------
# wire
# ---------------------------------------------------------------------------


def skin_depth_mm(fsw: float, temp_c: float = 100.0) -> float:
    """Copper skin depth at ``fsw`` (Hz) and ``temp_c`` (degC), in **mm**."""
    fsw = check_number("fsw", fsw, lo=0.0, unit="Hz", lo_inclusive=False)
    temp_c = check_number("temp_c", temp_c, lo=-273.0, hi=300.0, unit="degC", lo_inclusive=False)
    rho_factor = (1.0 + ALPHA_CU * (temp_c - 20.0)) ** 0.5
    return 66.1 * rho_factor / (fsw ** 0.5)


def nearest_awg(d_mm: float) -> Tuple[str, float, float]:
    """Nearest AWG for a bare diameter ``d_mm``.

    Returns ``(label, d_bare_mm, d_outer_mm)`` with the outer diameter including
    :data:`ENAMEL_BUILD_FACTOR`.
    """
    d_mm = check_number("d_mm", d_mm, lo=0.0, unit="mm", lo_inclusive=False)
    best = min(AWG_TABLE, key=lambda item: abs(item[1] - d_mm))
    return best[0], best[1], best[1] * ENAMEL_BUILD_FACTOR


def _awg_at_most(d_max_mm: float) -> Tuple[str, float]:
    """Largest AWG whose bare diameter is <= ``d_max_mm`` (thinnest if none)."""
    chosen = AWG_TABLE[-1]
    for label, d in AWG_TABLE:
        if d <= d_max_mm:
            chosen = (label, d)
            break
    return chosen


def pick_wire(
    irms: float,
    j_a_per_mm2: float,
    fsw: float,
    temp_c: float = 100.0,
    max_strands: int = 12,
) -> WireSpec:
    """Choose a strand count / AWG for a winding.

    ``irms`` A, ``j_a_per_mm2`` A/mm^2, ``fsw`` Hz, ``temp_c`` degC,
    ``max_strands`` integer >= 1 (how many parallel strands we are willing to
    wind).  Strands are chosen so that the strand diameter stays below
    ``2 * skin_depth_mm(fsw, temp_c)``.

    ``r_dc_ohm`` / ``r_ac_ohm`` are left at 0 here (they need the turn count and
    the core MLT) and are filled in by :func:`design_magnetics`.
    """
    irms = check_number("irms", irms, lo=0.0, unit="A", lo_inclusive=False)
    j = check_number("j_a_per_mm2", j_a_per_mm2, lo=0.0, unit="A/mm2", lo_inclusive=False)
    max_strands = int(check_number("max_strands", max_strands, lo=1, hi=200, unit="-"))
    delta = skin_depth_mm(fsw, temp_c)
    area_req = irms / j  # mm^2
    d_skin_max = 2.0 * delta
    area_skin_max = math.pi / 4.0 * d_skin_max ** 2

    if area_req <= area_skin_max:
        # one strand is enough: pick the *thinnest* standard wire that still
        # carries the current (using the thickest allowed wire here would waste
        # window area and produce a misleadingly low current density)
        d_needed = (4.0 * area_req / math.pi) ** 0.5
        allowed = [(lab, dd) for lab, dd in AWG_TABLE if dd <= d_skin_max]
        if not allowed:
            allowed = [AWG_TABLE[-1]]
        enough = [(lab, dd) for lab, dd in allowed if dd >= d_needed]
        label, d_strand = min(enough or allowed, key=lambda item: item[1])
        area_strand = math.pi / 4.0 * d_strand ** 2
        strands = 1
    else:
        label, d_strand = _awg_at_most(d_skin_max)
        area_strand = math.pi / 4.0 * d_strand ** 2
        strands = int(math.ceil(area_req / area_strand - 1e-12))
        strands = max(1, min(strands, max_strands))

    area_total = strands * area_strand
    return WireSpec(
        strands=strands,
        awg=label,
        d_bare_mm=d_strand,
        d_out_mm=d_strand * ENAMEL_BUILD_FACTOR,
        area_mm2=area_total,
        turns=0,
        r_dc_ohm=0.0,
        r_ac_ohm=0.0,
        temp_c=temp_c,
    )


def copper_resistance(
    wire: WireSpec, turns: int, mlt_cm: float, temp_c: float = 100.0
) -> float:
    """DC resistance of one winding in **ohm**.

    ``R_dc = rho(T) * N * MLT / A_total`` with ``rho`` in ohm*m, ``MLT`` in m and
    ``A_total`` in m^2.  The AC term is applied separately by
    :func:`_ac_factor` (``R_ac = R_dc * Fr`` with the skin-effect-only
    approximation ``Fr = 1 + (d/delta)^4/48``, i.e. a *lower bound* on the AC
    resistance because proximity effect is ignored).
    """
    if turns <= 0:
        return 0.0
    rho = RHO_CU_20 * (1.0 + ALPHA_CU * (temp_c - 20.0))
    length_m = turns * (mlt_cm / 100.0)
    area_m2 = wire.area_mm2 * 1e-6
    if area_m2 <= 0.0:
        return 0.0
    return rho * length_m / area_m2


def _ac_factor(d_bare_mm: float, delta_mm: float) -> float:
    """Skin-effect-only AC/DC resistance factor ``1 + (d/delta)^4/48``."""
    if delta_mm <= 0.0:
        return 1.0
    ratio = d_bare_mm / delta_mm
    return 1.0 + (ratio ** 4) / 48.0


# ---------------------------------------------------------------------------
# gap / flux
# ---------------------------------------------------------------------------


def gap_mm_for_lp(
    lp: float, np: int, ae_cm2: float, le_cm: float, ur: float = 2000.0
) -> float:
    """Air gap in **mm** that realises ``lp`` (H) with ``np`` turns.

    ``lg = mu0*Np^2*Ae/Lp - le/ur``, clamped at 0 (0 = ungapped core already
    gives at most this inductance... a 0 result with ``lg_raw < 0`` should be
    treated as "add turns").
    """
    lp = check_number("lp", lp, lo=0.0, unit="H", lo_inclusive=False)
    np = int(check_number("np", np, lo=1, unit="-"))
    ae_cm2 = check_number("ae_cm2", ae_cm2, lo=0.0, unit="cm2", lo_inclusive=False)
    le_cm = check_number("le_cm", le_cm, lo=0.0, unit="cm", lo_inclusive=False)
    ur = check_number("ur", ur, lo=1.0, unit="-")
    ae_m2 = ae_cm2 * 1e-4
    le_m = le_cm * 1e-2
    lg = MU0 * np * np * ae_m2 / lp - le_m / ur
    return max(0.0, lg * 1000.0)


def gap_raw_mm(lp: float, np: int, ae_cm2: float, le_cm: float, ur: float = 2000.0) -> float:
    """Same as :func:`gap_mm_for_lp` but **without** clamping at 0 (mm)."""
    lp = check_number("lp", lp, lo=0.0, unit="H", lo_inclusive=False)
    np = int(check_number("np", np, lo=1, unit="-"))
    ae_m2 = ae_cm2 * 1e-4
    le_m = le_cm * 1e-2
    return (MU0 * np * np * ae_m2 / lp - le_m / ur) * 1000.0


def bmax_of(lp: float, ipk: float, np: int, ae_cm2: float) -> float:
    """Peak flux density ``L*Ipk/(Np*Ae)`` in **T**."""
    lp = check_number("lp", lp, lo=0.0, unit="H", lo_inclusive=False)
    ipk = check_number("ipk", ipk, lo=0.0, unit="A", lo_inclusive=False)
    np = int(check_number("np", np, lo=1, unit="-"))
    ae_cm2 = check_number("ae_cm2", ae_cm2, lo=0.0, unit="cm2", lo_inclusive=False)
    return lp * ipk / (np * ae_cm2 * 1e-4)


# ---------------------------------------------------------------------------
# the design routine
# ---------------------------------------------------------------------------


def _resolve_turns(
    design: FlybackDesign,
    core: CoreSpec,
    bmax_target: float,
    max_iter: int = 200,
) -> Tuple[int, int, float, float, float, float, float]:
    """Pick integer turns, then re-solve the *actual* operating point.

    Rounding turns changes ``n`` and therefore Dmax, Ipk and Bmax, so the
    operating point is **re-solved** with the integer ratio instead of assuming
    the continuous design still holds::

        D    = Vor/(Vin_min + Vor),  Vor = n_actual * Vout_ref
        dI   = Vin_min*D/(Lp*fsw)
        Ipk  = Pin/(Vin_min*D) + dI/2      (exact trapezoid power balance)
        kr   = dI/Ipk

    Returns ``(np, ns, n_actual, vor, dmax, ipk, krip)``.
    """
    lp = design.lp
    pin = design.spec.pin
    vin = design.vin_dc_min
    fsw = design.spec.fsw
    vout_ref = design.spec.vout_ref
    ae_m2 = core.ae_cm2 * 1e-4

    np = max(1, int(math.ceil(lp * design.ipk / (bmax_target * ae_m2) - 1e-12)))
    for _ in range(max_iter):
        ns = max(1, int(math.ceil(np / design.n - 1e-12)))
        n_act = float(np) / float(ns)
        vor = n_act * vout_ref
        dmax = duty_from_vor(vor, vin)
        if design.mode == "CCM":
            di = vin * dmax / (lp * fsw)
            ipk = pin / (vin * dmax) + di / 2.0
            krip = min(1.0, di / ipk)
        else:
            # DCM: D is set by the inductance, n only sets the discharge time
            d_act = (2.0 * pin * lp * fsw) ** 0.5 / vin
            ipk = 2.0 * pin / (vin * d_act)
            krip = 1.0
            dmax = d_act
        np_needed = max(1, int(math.ceil(lp * ipk / (bmax_target * ae_m2) - 1e-12)))
        if np_needed <= np:
            return np, ns, n_act, vor, dmax, ipk, krip
        np = np_needed
    raise OplError(
        OPL_E_RANGE,
        "turn-count resolution did not converge for core {0}".format(core.name),
        "widen bmax_target or pick a larger core",
    )


def design_magnetics(
    design: FlybackDesign,
    bmax_target: float = 0.28,
    ku: float = 0.35,
    j_a_per_mm2: float = 4.0,
    core_name: Optional[str] = None,
    temp_c: float = 100.0,
    ku_fit_max: float = 0.65,
    ur: float = 2000.0,
) -> MagneticDesign:
    """Select a core and design the transformer build.

    Parameters
    ----------
    design : :class:`opl.model.FlybackDesign`
        Output of :func:`opl.flyback.design_flyback`.
    bmax_target : float
        Peak flux density target in **T** (0.28 T is a safe 100 C target for a
        MnZn power ferrite whose saturation is ~0.35-0.39 T at 100 C).
    ku : float
        Window utilisation assumed by the AP method, dimensionless (0.35).
    j_a_per_mm2 : float
        Current density in **A/mm^2** (4.0 = 400 A/cm^2 is a typical forced/
        convection-cooled adapter value).
    core_name : str or None
        Force a specific core from the table.  ``None`` selects automatically
        (smallest AP that also fits the copper).
    temp_c : float
        Winding temperature in **degC** used for the resistivity.
    ku_fit_max : float
        Maximum *achieved* window utilisation acceptable for a fit.
    ur : float
        Relative permeability used for the ungapped part of the gap.

    Returns
    -------
    :class:`opl.model.MagneticDesign`

    Raises
    ------
    ``OplError(OPL-E-NOCORE)``
        Nothing in the table satisfies AP or the fit constraint.
    ``OplError(OPL-E-RANGE)``
        DCM discharge no longer fits inside the off-time with integer turns.
    """
    require(isinstance(design, FlybackDesign), OPL_E_INPUT, "design must be a FlybackDesign")
    bmax_target = check_number("bmax_target", bmax_target, lo=0.02, hi=0.45, unit="T")
    ku = check_number("ku", ku, lo=0.05, hi=0.95, unit="-")
    j = check_number("j_a_per_mm2", j_a_per_mm2, lo=1.0, hi=20.0, unit="A/mm2")
    ku_fit_max = check_number("ku_fit_max", ku_fit_max, lo=0.05, hi=1.0, unit="-")

    warnings: List[str] = []
    ap_req = required_ap(design.lp, design.ipk, design.irms_pri, bmax_target, ku, j)

    if core_name is not None:
        core = find_core(core_name)
        candidates: Sequence[CoreSpec] = (core,)
        if core.ap_cm4 < ap_req:
            warnings.append(
                "forced core {0} has AP={1:.4g} cm^4 < required {2:.4g} cm^4".format(
                    core.name, core.ap_cm4, ap_req
                )
            )
    else:
        first = select_core(ap_req)
        idx = CORE_TABLE.index(first)
        candidates = CORE_TABLE[idx:]

    chosen: Optional[MagneticDesign] = None
    last_reason = ""
    for core in candidates:
        np, ns, n_actual, vor, dmax, ipk, krip = _resolve_turns(design, core, bmax_target)
        bmax = bmax_of(design.lp, ipk, np, core.ae_cm2)
        if bmax > bmax_target * (1.0 + 1e-9):
            last_reason = "{0}: Bmax={1:.4f} T above target".format(core.name, bmax)
            continue

        gap = gap_raw_mm(design.lp, np, core.ae_cm2, core.le_cm, ur)
        if gap < 0.0:
            last_reason = "{0}: negative gap ({1:.4f} mm)".format(core.name, gap)
            continue
        gap_mm = gap * 1.0

        # currents with the actual (integer) turns ratio
        if design.mode == "CCM":
            duty_off = 1.0 - dmax
        else:
            tdis = ipk * design.lp / (n_actual * design.spec.vout_ref)
            duty_off = tdis * design.spec.fsw
            if dmax + duty_off > 1.0 + 1e-9:
                raise OplError(
                    OPL_E_RANGE,
                    "DCM discharge does not fit: D={0:.4f} + tdis/T={1:.4f} > 1 with "
                    "integer turns Np={2}/Ns={3} on {4}".format(
                        dmax, duty_off, np, ns, core.name
                    ),
                    "raise Ns (it lowers n_actual) or reduce dcm_k",
                )
        irms_pri = trapezoid_rms(ipk * (1.0 - krip), ipk, dmax)
        irms_sec = n_actual * trapezoid_rms(ipk * (1.0 - krip), ipk, duty_off)

        wire_pri = pick_wire(irms_pri, j, design.spec.fsw, temp_c)
        wire_sec = pick_wire(irms_sec, j, design.spec.fsw, temp_c)

        mlt = core.mlt_cm
        rp_dc = copper_resistance(wire_pri, np, mlt, temp_c)
        rs_dc = copper_resistance(wire_sec, ns, mlt, temp_c)
        delta = skin_depth_mm(design.spec.fsw, temp_c)
        fp = _ac_factor(wire_pri.d_bare_mm, delta)
        fs = _ac_factor(wire_sec.d_bare_mm, delta)
        wire_pri.turns = np
        wire_sec.turns = ns
        wire_pri.r_dc_ohm = rp_dc
        wire_pri.r_ac_ohm = rp_dc * fp
        wire_sec.r_dc_ohm = rs_dc
        wire_sec.r_ac_ohm = rs_dc * fs

        aw_mm2 = core.aw_cm2 * 100.0
        area_pri = np * (math.pi / 4.0 * wire_pri.d_out_mm ** 2)
        area_sec = ns * (math.pi / 4.0 * wire_sec.d_out_mm ** 2)
        ku_actual = (area_pri + area_sec) / aw_mm2

        if ku_actual > ku_fit_max:
            last_reason = "{0}: winding does not fit (Ku={1:.3f} > {2:.2f})".format(
                core.name, ku_actual, ku_fit_max
            )
            continue

        j_pri = irms_pri / wire_pri.area_mm2
        j_sec = irms_sec / wire_sec.area_mm2
        if j_pri > j * 1.15:
            warnings.append(
                "primary current density {0:.2f} A/mm2 is above the {1:.2f} A/mm2 "
                "target (strand limit of {2} reached)".format(
                    j_pri, j, wire_pri.strands
                )
            )
        if j_sec > j * 1.15:
            warnings.append(
                "secondary current density {0:.2f} A/mm2 is above the {1:.2f} A/mm2 "
                "target (strand limit of {2} reached)".format(
                    j_sec, j, wire_sec.strands
                )
            )

        delta_b = bmax * krip
        if dmax > design.spec.dmax_limit:
            warnings.append(
                "integer turns raise Dmax to {0:.4f} (limit {1:.2f})".format(
                    dmax, design.spec.dmax_limit
                )
            )
        if gap_mm > 1.0:
            warnings.append(
                "air gap {0:.3f} mm is large; expect fringing loss and a wide "
                "tolerance band".format(gap_mm)
            )
        if ku_actual > 0.60:
            warnings.append(
                "window utilisation {0:.2f} is high for hand winding".format(ku_actual)
            )

        chosen = MagneticDesign(
            core=core,
            ap_required=ap_req,
            ap_margin=core.ap_cm4 / ap_req if ap_req > 0 else float("inf"),
            np=np,
            ns=ns,
            n_actual=n_actual,
            gap_mm=gap_mm,
            bmax=bmax,
            delta_b=delta_b,
            bmax_target=bmax_target,
            j_pri=j_pri,
            j_sec=j_sec,
            delta_mm=delta,
            ku_actual=ku_actual,
            wire_pri=wire_pri,
            wire_sec=wire_sec,
            vor_actual=vor,
            dmax_actual=dmax,
            warnings=warnings,
        )
        if design.mode == "CCM" and krip > 1.0:
            chosen.warnings.append("actual ripple ratio exceeds 1.0 (DCM border)")
        break

    if chosen is None:
        raise OplError(
            OPL_E_NOCORE,
            "no core in the table can be built: {0}".format(last_reason),
            "raise bmax_target, lower j_a_per_mm2 or relax ku_fit_max",
        )
    return chosen
