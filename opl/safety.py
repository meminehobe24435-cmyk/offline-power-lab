"""offline-power-lab :: insulation distance (clearance / creepage) checks.

FORMULAS AND UNITS
==================
All distances in **millimetres** - the unit the standards tables use.

    clearance_required = table_clearance(V_working, pollution_degree, insulation)
                         * altitude_factor(altitude)
    creepage_required  = table_creepage(V_working, material_group, insulation)

    reinforced = 2 x basic        (this tool's simplification, see below)
    V_working  = the RMS mains voltage the barrier must withstand [Vrms]

Earth leakage current caused by the Y capacitors (the other safety-relevant
number this module produces)::

    I_leak = 2*pi*f_line*C_y_total*Vac      [A]   (sinusoidal estimate)
    C_y_total = number_of_Y_caps * C_per_cap [F]  (line-to-earth each)

SIMPLIFIED SUBSET - READ THIS
-----------------------------
:data:`CLEARANCE_TABLE`, :data:`CREEPAGE_TABLE` and :data:`ALTITUDE_FACTORS`
below are a **small, rounded subset of the commonly used bands** from the
IEC 60950-1 / GB 4943.1 family (tables 2K/2L-style), covering 50 Vrms to
1000 Vrms for pollution degrees 1-3, material groups I/II and IIIa/IIIb, and
2000-6000 m altitude.

They are intended for **engineering sanity checks during design**, not for
compliance:

* the real standards specify different values for different insulation types,
  for frequencies above 30 kHz, for voltages not in the table, for reduced
  clearance with controlled overvoltage categories, and for material groups
  with different CTI;
* the ``reinforced = 2 x basic`` rule used here is a simplification - the
  standards derive reinforced distances from the tables, not always as an exact
  factor of two;
* creepage values are taken from the pollution-degree-2 column for every
  pollution degree (conservative for PD1);
* **no result from this module replaces the standards text or a safety
  agency's judgement**, and a layout that passes here has not been certified.

Altitude correction uses the IEC 60664-1-style multiplicative factors, which
apply to the **clearance** (the air can break down more easily at low pressure);
creepage does not need them.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .errors import OPL_E_INPUT, OPL_E_TABLE, OplError, check_number, require
from .model import DesignSpec, FlybackDesign, SafetyRequirement, SafetyResult

__all__ = [
    "CLEARANCE_TABLE",
    "CREEPAGE_TABLE",
    "ALTITUDE_FACTORS",
    "STANDARD_LEAKAGE_LIMITS_MA",
    "MATERIAL_GROUPS",
    "INSULATION_TYPES",
    "lookup_clearance",
    "lookup_creepage",
    "altitude_factor",
    "leakage_current_ma",
    "check_safety",
]

#: Clearance (mm) for **basic** insulation, sea level, as a function of the
#: working voltage in Vrms and the pollution degree.
#: ``(v_max_rms, pd1_mm, pd2_mm, pd3_mm)`` - simplified subset, see module docstring.
CLEARANCE_TABLE: Tuple[Tuple[float, float, float, float], ...] = (
    (50.0, 0.10, 0.60, 0.60),
    (100.0, 0.10, 0.60, 1.00),
    (150.0, 0.50, 1.00, 1.50),
    (300.0, 1.00, 1.50, 2.00),
    (600.0, 1.50, 2.00, 2.50),
    (1000.0, 2.00, 2.50, 3.20),
)

#: Creepage (mm) for **basic** insulation, pollution degree 2, as a function of
#: the working voltage in Vrms: ``(v_max_rms, group_I_II_mm, group_IIIa_IIIb_mm)``.
CREEPAGE_TABLE: Tuple[Tuple[float, float, float], ...] = (
    (50.0, 0.60, 0.60),
    (125.0, 0.60, 1.00),
    (250.0, 1.00, 2.50),
    (400.0, 1.60, 3.20),
    (500.0, 2.00, 4.00),
    (630.0, 2.50, 5.00),
    (800.0, 3.20, 6.30),
    (1000.0, 4.00, 8.00),
)

#: ``(altitude_m, clearance multiplier)`` - 2000 m is the reference (1.0).
ALTITUDE_FACTORS: Tuple[Tuple[float, float], ...] = (
    (2000.0, 1.00),
    (3000.0, 1.14),
    (4000.0, 1.29),
    (5000.0, 1.48),
    (6000.0, 1.70),
    (7000.0, 2.00),
)

#: Maximum earth leakage current in **mA** by equipment class (60950-1 style,
#: 50/60 Hz, sinusoidal).  Class II is the unearthed (double-insulated) wall
#: charger case; class I is earthed.
STANDARD_LEAKAGE_LIMITS_MA: Dict[str, float] = {
    "I": 3.5,
    "II": 0.25,
    "III": 0.25,
}

MATERIAL_GROUPS = ("I", "II", "IIIa", "IIIb")
INSULATION_TYPES = ("basic", "reinforced", "functional")

TWO_PI = 2.0 * math.pi


def _lookup_band(table, value: float, label: str):
    """First band whose upper bound is >= ``value``."""
    for row in table:
        if value <= row[0]:
            return row
    raise OplError(
        OPL_E_TABLE,
        "{0}={1:g} is above the largest tabulated band ({2:g})".format(label, value, table[-1][0]),
        "this simplified table stops at 1000 Vrms - use the standards text",
    )


def altitude_factor(altitude_m: float) -> float:
    """Clearance multiplier for an operating altitude, dimensionless.

    ``altitude_m`` in **m** (0..7000).  Values below 2000 m return 1.0.
    """
    altitude_m = check_number("altitude_m", altitude_m, lo=0.0, hi=7000.0, unit="m")
    for limit, factor in ALTITUDE_FACTORS:
        if altitude_m <= limit:
            return factor
    return ALTITUDE_FACTORS[-1][1]


def lookup_clearance(
    v_working_rms: float,
    pollution_degree: int = 2,
    insulation: str = "basic",
    altitude_m: float = 0.0,
) -> Tuple[float, float]:
    """Required **clearance** in mm (air path) for a working voltage.

    ``v_working_rms`` in Vrms, ``pollution_degree`` 1..3, ``insulation`` one of
    ``"basic"`` / ``"reinforced"`` / ``"functional"``, ``altitude_m`` in m.

    Returns ``(clearance_mm, altitude_factor_applied)``.

    Raises ``OplError(OPL-E-TABLE)`` above 1000 Vrms or for an unknown
    pollution degree / insulation type.
    """
    v_working_rms = check_number("v_working_rms", v_working_rms, lo=0.0, hi=1.0e6, unit="Vrms")
    pd = int(check_number("pollution_degree", pollution_degree, lo=1, hi=10, unit="-"))
    if pd not in (1, 2, 3):
        raise OplError(OPL_E_TABLE, "pollution degree {0} is not tabulated".format(pd))
    key = (insulation or "basic").strip().lower()
    if key not in INSULATION_TYPES:
        raise OplError(
            OPL_E_INPUT,
            "insulation must be one of {0}, got {1!r}".format(list(INSULATION_TYPES), insulation),
        )
    row = _lookup_band(CLEARANCE_TABLE, v_working_rms, "v_working_rms")
    basic = row[pd]  # row = (v, pd1, pd2, pd3)
    factor = altitude_factor(altitude_m)
    if key == "reinforced":
        value = 2.0 * basic
    elif key == "functional":
        value = 0.5 * basic
    else:
        value = basic
    return value * factor, factor


def lookup_creepage(
    v_working_rms: float,
    pollution_degree: int = 2,
    material_group: str = "IIIa",
    insulation: str = "basic",
) -> float:
    """Required **creepage** in mm (surface path) for a working voltage.

    ``material_group`` is ``"I"``/``"II"`` (CTI >= 400) or ``"IIIa"``/``"IIIb"``
    (CTI < 400).  ``pollution_degree`` is accepted for traceability but the
    simplified table always uses the PD2 column (conservative for PD1).
    """
    v_working_rms = check_number("v_working_rms", v_working_rms, lo=0.0, hi=1.0e6, unit="Vrms")
    pd = int(check_number("pollution_degree", pollution_degree, lo=1, hi=10, unit="-"))
    if pd not in (1, 2, 3):
        raise OplError(OPL_E_TABLE, "pollution degree {0} is not tabulated".format(pd))
    group = (material_group or "IIIa").strip()
    key = group.upper().replace("IIIA", "IIIa").replace("IIIB", "IIIb")
    if key not in MATERIAL_GROUPS:
        raise OplError(
            OPL_E_INPUT,
            "material_group must be one of {0}, got {1!r}".format(
                list(MATERIAL_GROUPS), material_group
            ),
        )
    ins = (insulation or "basic").strip().lower()
    if ins not in INSULATION_TYPES:
        raise OplError(
            OPL_E_INPUT,
            "insulation must be one of {0}, got {1!r}".format(list(INSULATION_TYPES), insulation),
        )
    row = _lookup_band(CREEPAGE_TABLE, v_working_rms, "v_working_rms")
    basic = row[1] if key in ("I", "II") else row[2]
    if ins == "reinforced":
        return 2.0 * basic
    if ins == "functional":
        return 0.5 * basic
    return basic


def leakage_current_ma(vac: float, f_line: float, cy_total_f: float) -> float:
    """Earth leakage current through the Y capacitors, in **mA**.

    ``vac`` Vrms, ``f_line`` Hz, ``cy_total_f`` F (all line-to-earth Y
    capacitors added together).  Sinusoidal estimate ``2*pi*f*C*V``; real
    leakage also has resistive and harmonic components that this does not model.
    """
    vac = check_number("vac", vac, lo=0.0, hi=1000.0, unit="Vrms")
    f_line = check_number("f_line", f_line, lo=0.0, hi=1000.0, unit="Hz")
    cy_total_f = check_number("cy_total_f", cy_total_f, lo=0.0, hi=1.0e-3, unit="F")
    return TWO_PI * f_line * cy_total_f * vac * 1000.0


def check_safety(
    design: FlybackDesign,
    design_clearance_mm: float,
    design_creepage_mm: float,
    v_working_rms: Optional[float] = None,
    pollution_degree: int = 2,
    material_group: str = "IIIa",
    insulation: str = "reinforced",
    altitude_m: float = 2000.0,
    cy_f: float = 1.0e-9,
    cy_count: int = 2,
    equipment_class: str = "II",
) -> SafetyResult:
    """Compare the design's insulation distances with the look-up requirement.

    Parameters
    ----------
    design : :class:`opl.model.FlybackDesign`
    design_clearance_mm, design_creepage_mm : float
        The distances actually provided by the layout (mm).
    v_working_rms : float or None
        Working voltage across the barrier in Vrms; default
        ``design.spec.vac_max`` (the highest mains voltage).
    pollution_degree, material_group, insulation, altitude_m
        Conditions for the look-up (see :func:`lookup_clearance`).
    cy_f, cy_count : float, int
        Y capacitor value per line (F) and how many (line-to-earth).  The earth
        leakage is computed from ``cy_count * cy_f``.
    equipment_class : str
        ``"I"``, ``"II"`` or ``"III"`` - selects the leakage-current limit from
        :data:`STANDARD_LEAKAGE_LIMITS_MA`.

    Returns
    -------
    :class:`opl.model.SafetyResult` with the required vs provided distances,
    their margins, the leakage verdict and a one-line conclusion.
    """
    require(isinstance(design, FlybackDesign), OPL_E_INPUT, "design must be a FlybackDesign")
    if not isinstance(design.spec, DesignSpec):  # pragma: no cover - structural
        raise OplError(OPL_E_INPUT, "design.spec must be a DesignSpec")
    design_clearance_mm = check_number(
        "design_clearance_mm", design_clearance_mm, lo=0.0, hi=100.0, unit="mm"
    )
    design_creepage_mm = check_number(
        "design_creepage_mm", design_creepage_mm, lo=0.0, hi=100.0, unit="mm"
    )
    if v_working_rms is None:
        v_working_rms = design.spec.vac_max

    clearance_req, factor = lookup_clearance(
        v_working_rms, pollution_degree, insulation, altitude_m
    )
    creepage_req = lookup_creepage(v_working_rms, pollution_degree, material_group, insulation)

    warnings: List[str] = []
    cls = (equipment_class or "II").strip().upper()
    if cls not in STANDARD_LEAKAGE_LIMITS_MA:
        raise OplError(
            OPL_E_INPUT,
            "equipment_class must be one of {0}, got {1!r}".format(
                list(STANDARD_LEAKAGE_LIMITS_MA), equipment_class
            ),
        )
    limit_ma = STANDARD_LEAKAGE_LIMITS_MA[cls]
    leak_ma = leakage_current_ma(v_working_rms, design.spec.line_freq, cy_count * cy_f)
    leak_pass = leak_ma <= limit_ma
    if not leak_pass:
        max_cy = limit_ma / (TWO_PI * design.spec.line_freq * v_working_rms * 1000.0)
        warnings.append(
            "Y capacitors ({0} x {1:.1f} nF) give {2:.3f} mA of earth leakage, above the "
            "class {3} limit of {4:.2f} mA; keep the total below {5:.2f} nF".format(
                cy_count, cy_f * 1e9, leak_ma, cls, limit_ma, max_cy * 1e9
            )
        )

    clearance_margin = design_clearance_mm - clearance_req
    creepage_margin = design_creepage_mm - creepage_req
    clearance_pass = clearance_margin >= 0.0
    creepage_pass = creepage_margin >= 0.0
    if altitude_m > 2000.0:
        warnings.append(
            "altitude {0:.0f} m multiplies the clearance requirement by {1:.2f}".format(
                altitude_m, factor
            )
        )

    requirement = SafetyRequirement(
        v_working_rms=v_working_rms,
        pollution_degree=pollution_degree,
        material_group=material_group,
        insulation=insulation,
        altitude_m=altitude_m,
        altitude_factor=factor,
        clearance_mm=clearance_req,
        creepage_mm=creepage_req,
        basis=(
            "simplified IEC 60950-1 / GB 4943.1 style tables (clearance table "
            "2K-like, creepage table 2L-like), reinforced = 2 x basic"
        ),
        notes=[
            "PD{0}, material group {1}, {2} insulation, {3:.0f} m".format(
                pollution_degree, material_group, insulation, altitude_m
            )
        ],
    )
    conclusion = "PASS" if (clearance_pass and creepage_pass and leak_pass) else "FAIL"
    details = []
    if not clearance_pass:
        details.append("clearance short by {0:.2f} mm".format(-clearance_margin))
    if not creepage_pass:
        details.append("creepage short by {0:.2f} mm".format(-creepage_margin))
    if not leak_pass:
        details.append("earth leakage {0:.3f} mA > {1:.2f} mA".format(leak_ma, limit_ma))
    return SafetyResult(
        requirement=requirement,
        design_clearance_mm=design_clearance_mm,
        design_creepage_mm=design_creepage_mm,
        clearance_margin_mm=clearance_margin,
        creepage_margin_mm=creepage_margin,
        clearance_pass=clearance_pass,
        creepage_pass=creepage_pass,
        leakage_current_ma=leak_ma,
        leakage_limit_ma=limit_ma,
        leakage_pass=leak_pass,
        conclusion="{0}: required clearance {1:.2f} mm / creepage {2:.2f} mm vs "
        "design {3:.2f} / {4:.2f} mm{5}".format(
            conclusion,
            clearance_req,
            creepage_req,
            design_clearance_mm,
            design_creepage_mm,
            ("; " + "; ".join(details)) if details else "",
        ),
        warnings=warnings,
    )
