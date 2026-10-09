"""offline-power-lab :: EMC input filter (CM/DM insertion loss + Y-cap leakage).

FORMULAS AND UNITS
==================
Insertion loss of a two-port network in a 50 ohm system (CISPR 17 style)::

    IL(f) = 20*log10( |H_ref| / |H_filter(f)| )        [dB]
    H_ref    = Rl / (Rs + Rl)      (the direct connection, -6 dB for 50/50)
    H_filter = Rl / [ (s*L + Rs)*(s*C*Rl + 1) + Rl ]   (series L, shunt C)

with ``s = j*2*pi*f``, ``Rs``/``Rl`` in ohm, ``L`` in H, ``C`` in F.

Differential mode (DM) equivalent circuit::

    L_dm = CM-choke leakage inductance + optional series DM inductor  [H]
    C_dm = the X capacitor (line-to-line)                             [F]

Common mode (CM) equivalent circuit - conservative convention used here::

    L_cm = 2 * L_per_winding     (the CM current flows through both windings)
    C_cm = one Y capacitor       (line-to-earth; the earth return is the
                                  reference, so the second Y capacitor is NOT
                                  counted - this *under*-estimates the
                                  attenuation, which is the safe direction for a
                                  filter design)

Earth leakage current from the Y capacitors::

    I_leak = 2*pi*f_line*(cy_count*Cy)*Vac             [A]

Noise SPECTRUM IS NOT MODELLED
------------------------------
This tool cannot tell you what attenuation a product *needs*, because that
depends on the measured (or estimated) noise spectrum of the specific layout
and magnetics.  The required attenuation is an **input** (``target_db``), and
the output is "at which frequency does this filter reach it".  No EMC
measurement or mitigation is part of this repository.
"""

from __future__ import annotations

import cmath
import math
from typing import Dict, List, Optional, Tuple

from .errors import OPL_E_INPUT, OplError, check_number, require
from .model import EmiFilter, EmiResult, FlybackDesign
from .safety import STANDARD_LEAKAGE_LIMITS_MA, leakage_current_ma

__all__ = [
    "insertion_loss_lc",
    "insertion_loss_dm",
    "insertion_loss_cm",
    "filter_gain",
    "emi_report",
]

TWO_PI = 2.0 * math.pi


def filter_gain(f_hz: float, l_h: float, c_f: float, rs_ohm: float = 50.0, rl_ohm: float = 50.0) -> complex:
    """Transfer of a series-L / shunt-C filter between ``rs_ohm`` and ``rl_ohm``.

    ``f_hz`` Hz, ``l_h`` H, ``c_f`` F.  Returns a complex ratio (dimensionless).
    """
    f_hz = check_number("f_hz", f_hz, lo=0.0, unit="Hz", lo_inclusive=False)
    l_h = check_number("l_h", l_h, lo=0.0, unit="H")
    c_f = check_number("c_f", c_f, lo=0.0, unit="F")
    rs_ohm = check_number("rs_ohm", rs_ohm, lo=0.0, unit="ohm", lo_inclusive=False)
    rl_ohm = check_number("rl_ohm", rl_ohm, lo=0.0, unit="ohm", lo_inclusive=False)
    s = 1j * TWO_PI * f_hz
    return rl_ohm / ((s * l_h + rs_ohm) * (s * c_f * rl_ohm + 1.0) + rl_ohm)


def insertion_loss_lc(
    f_hz: float,
    l_h: float,
    c_f: float,
    rs_ohm: float = 50.0,
    rl_ohm: float = 50.0,
) -> float:
    """Insertion loss in **dB** of a series-L / shunt-C filter (50/50 ohm by default).

    ``IL = 20*log10(|H_ref| / |H_filter|)``; ``H_ref = Rl/(Rs+Rl)``.
    A filter with no attenuation returns 0 dB, and the ideal roll-off is
    ``-40 dB/decade`` above ``1/(2*pi*sqrt(L*C))``.
    """
    h_ref = abs(rl_ohm / (rs_ohm + rl_ohm))
    h = abs(filter_gain(f_hz, l_h, c_f, rs_ohm, rl_ohm))
    if h <= 0.0:
        return float("inf")
    return 20.0 * math.log10(h_ref / h)


def insertion_loss_dm(f_hz: float, filt: EmiFilter) -> float:
    """Differential-mode insertion loss in **dB** (X capacitor + DM inductance)."""
    require(isinstance(filt, EmiFilter), OPL_E_INPUT, "filter must be an EmiFilter")
    return insertion_loss_lc(f_hz, filt.ldm_h, filt.cx_f, filt.rs_ohm, filt.rl_ohm)


def insertion_loss_cm(f_hz: float, filt: EmiFilter) -> float:
    """Common-mode insertion loss in **dB**.

    Uses ``2 * L_per_winding`` in series (both windings carry the CM current)
    and one Y capacitor as the shunt path - the conservative convention described
    in the module docstring.
    """
    require(isinstance(filt, EmiFilter), OPL_E_INPUT, "filter must be an EmiFilter")
    return insertion_loss_lc(f_hz, 2.0 * filt.lcm_h, filt.cy_f, filt.rs_ohm, filt.rl_ohm)


def _first_frequency_above(pairs: List[Tuple[float, float]], target_db: float, f_start: float) -> float:
    """Lowest frequency above which the value stays >= ``target_db`` to the end."""
    for idx in range(len(pairs) - 1, -1, -1):
        if pairs[idx][1] < target_db:
            if idx + 1 >= len(pairs):
                return float("inf")
            return pairs[idx + 1][0]
    return f_start


def emi_report(
    filt: EmiFilter,
    target_db: float = 40.0,
    f_start_hz: float = 150.0e3,
    f_stop_hz: float = 30.0e6,
    n_points: int = 200,
    vac_v: float = 264.0,
    f_line_hz: float = 50.0,
    cy_count: int = 2,
    equipment_class: str = "II",
    design: Optional[FlybackDesign] = None,
) -> EmiResult:
    """Sweep the filter, compare with a target attenuation, check the leakage.

    Parameters
    ----------
    filt : :class:`opl.model.EmiFilter`  Element values (see the class docstring).
    target_db : float
        Required insertion loss in **dB** (an *input*: this tool has no noise
        spectrum, see the module docstring).
    f_start_hz, f_stop_hz : float
        Swept band in **Hz** (default the CISPR 150 kHz - 30 MHz band).
    n_points : int  Number of log-spaced points.
    vac_v : float  Mains voltage used for the leakage check, **Vrms**.
    f_line_hz : float  Mains frequency, **Hz**.
    cy_count : int  How many Y capacitors (line-to-earth) are fitted.
    equipment_class : str  ``"I"`` / ``"II"`` / ``"III"`` for the leakage limit.
    design : optional  Only used to add a note about the switching frequency.

    Returns
    -------
    :class:`opl.model.EmiResult` with the DM/CM curves, the frequency from which
    the target is met, and the Y-capacitor leakage verdict.
    """
    require(isinstance(filt, EmiFilter), OPL_E_INPUT, "filter must be an EmiFilter")
    target_db = check_number("target_db", target_db, lo=0.0, hi=200.0, unit="dB")
    f_start_hz = check_number("f_start_hz", f_start_hz, lo=1.0, hi=1.0e9, unit="Hz")
    f_stop_hz = check_number("f_stop_hz", f_stop_hz, lo=1.0, hi=1.0e9, unit="Hz")
    require(f_stop_hz > f_start_hz, OPL_E_INPUT, "f_stop_hz must be greater than f_start_hz")
    n_points = int(check_number("n_points", n_points, lo=2, hi=100000, unit="-"))
    cy_count = int(check_number("cy_count", cy_count, lo=0, hi=10, unit="-"))

    ratio = (f_stop_hz / f_start_hz) ** (1.0 / (n_points - 1))
    curve: List[Tuple[float, float, float]] = []
    dm_pairs: List[Tuple[float, float]] = []
    cm_pairs: List[Tuple[float, float]] = []
    for i in range(n_points):
        f = f_start_hz * ratio ** i
        dm = insertion_loss_dm(f, filt)
        cm = insertion_loss_cm(f, filt)
        curve.append((f, dm, cm))
        dm_pairs.append((f, dm))
        cm_pairs.append((f, cm))

    f_pass_dm = _first_frequency_above(dm_pairs, target_db, f_start_hz)
    f_pass_cm = _first_frequency_above(cm_pairs, target_db, f_start_hz)
    dm_pass = f_pass_dm <= f_start_hz * (1.0 + 1e-9)
    cm_pass = f_pass_cm <= f_start_hz * (1.0 + 1e-9)

    cls = (equipment_class or "II").strip().upper()
    if cls not in STANDARD_LEAKAGE_LIMITS_MA:
        raise OplError(
            OPL_E_INPUT,
            "equipment_class must be one of {0}, got {1!r}".format(
                list(STANDARD_LEAKAGE_LIMITS_MA), equipment_class
            ),
        )
    limit_ma = STANDARD_LEAKAGE_LIMITS_MA[cls]
    leak_ma = leakage_current_ma(vac_v, f_line_hz, cy_count * filt.cy_f)
    leak_pass = leak_ma <= limit_ma

    warnings: List[str] = []
    if not dm_pass:
        warnings.append(
            "DM insertion loss reaches {0:.0f} dB only at {1:.0f} Hz, above the "
            "{2:.0f} Hz start of the band".format(target_db, f_pass_dm, f_start_hz)
        )
    if not cm_pass:
        warnings.append(
            "CM insertion loss reaches {0:.0f} dB only at {1:.0f} Hz, above the "
            "{2:.0f} Hz start of the band".format(target_db, f_pass_cm, f_start_hz)
        )
    if not leak_pass:
        max_cy = limit_ma / (TWO_PI * f_line_hz * vac_v * 1000.0)
        warnings.append(
            "{0} x {1:.2f} nF of Y capacitance leaks {2:.3f} mA at {3:.0f} Vrms, above the "
            "class {4} limit of {5:.2f} mA (maximum {6:.2f} nF total)".format(
                cy_count, filt.cy_f * 1e9, leak_ma, vac_v, cls, limit_ma, max_cy * 1e9
            )
        )
    if design is not None:
        warnings.append(
            "note: the switching frequency is {0:.0f} Hz, so the first DM harmonic sits "
            "at {0:.0f} Hz - the attenuation target must come from a noise measurement "
            "or estimate, which this tool does not have".format(design.spec.fsw)
        )

    return EmiResult(
        curve=curve,
        target_db=target_db,
        f_start_hz=f_start_hz,
        f_stop_hz=f_stop_hz,
        f_pass_dm_hz=f_pass_dm,
        f_pass_cm_hz=f_pass_cm,
        dm_pass=dm_pass,
        cm_pass=cm_pass,
        leakage_current_ma=leak_ma,
        leakage_limit_ma=limit_ma,
        leakage_pass=leak_pass,
        warnings=warnings,
    )
