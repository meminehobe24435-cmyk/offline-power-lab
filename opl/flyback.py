"""offline-power-lab :: flyback main-circuit design (CCM and DCM).

FORMULAS AND UNITS  (all SI unless stated: V, A, H, F, ohm, Hz, s, W)
====================================================================
Inputs (see :class:`opl.model.DesignSpec`)
    vac_min/vac_max  Vrms       mains range
    vout, iout       V, A       DC output
    fsw              Hz         switching frequency
    eta_target       -          target efficiency (0.80 = 80 %)
    vinyl drops      V          ``bridge_drop`` (input rectifier), ``vf_sec``
                                (secondary rectifier, used for Vor)

Derived operating point
    Pin      = Pout / eta_target                            [W]
    Vin_min  = vac_min * sqrt(2) - bridge_drop               [V] (bulk valley)
    Vin_max  = vac_max * sqrt(2) - bridge_drop               [V] (bulk peak)
    Vout_ref = vout + vf_sec                                 [V]

Step 1 - reflected voltage and turns ratio (from the Dmax target)
    Vor      = Vin_min * Dmax_t / (1 - Dmax_t)               [V]
    n        = Np / Ns = Vor / Vout_ref                       [-]
    and therefore, exactly, for CCM:
        D(Vin) = Vor / (Vin + Vor)                            [-]
        Dmax   = D(Vin_min) = Dmax_t,   Dmin = D(Vin_max)

Step 2 - primary inductance and peak current
    CCM (ripple ratio kr = dI/Ipk in (0,1], kr = 1 is exactly BCM):
        Pin  = 0.5 * (Ip1 + Ipk) * Vin * D      (average current over a period)
        Ipk  = 2 * Pin / (Vin * D * (2 - kr))                 [A]
        Ip1  = Ipk * (1 - kr)                                 [A]
        dI   = kr * Ipk = Vin * D / (Lp * fsw)                [A]
        Lp   = Vin * D / (dI * fsw)                           [H]
        Lp/Lbcm = (2 - kr) / kr        -> kr < 1 means CCM
    DCM (Lp = dcm_k * Lbcm, dcm_k in (0,1]):
        Lbcm = (Vin * D)^2 / (2 * Pin * fsw)                  [H]
        Lp   = dcm_k * Lbcm                                   [H]
        D    = sqrt(2 * Pin * Lp * fsw) / Vin                 [-]
             = Dmax_t * sqrt(dcm_k)  at Vin_min               [-]
        Ipk  = 2 * Pin / (Vin * D)                            [A]
    Boundary (critical) inductance, identical in both modes:
        Lbcm = (Vin * D)^2 / (2 * Pin * fsw)                   [H]

Step 3 - secondary side (ampere-turn equality Np*Ip = Ns*Is)
    Is_pk  = n * Ipk                                          [A]
    Is1    = n * Ip1                                          [A] (0 in DCM)
    Is_avg = n * 0.5 * (Is1 + Is_pk) * (1 - D) = Pin / Vout_ref   [A]
    tdis   = Ipk * Lp / (n * Vout_ref)  (DCM; = (1-D)/fsw in CCM) [s]

Step 4 - RMS currents (trapezoid of duration ``duty``)
    Irms(t) = sqrt( duty * (i1^2 + i1*i2 + i2^2) / 3 )         [A]
    Ipri_rms = Irms(Ip1, Ipk, D)                               [A]
    Isec_rms = n * Irms(Ip1, Ipk, 1 - D)                       [A]

DCM feasibility (proved, not assumed): with ``n`` from step 1 and
``Lp = dcm_k*Lbcm`` the secondary discharge time is
``tdis/T = (1 - Dmax_t) * sqrt(dcm_k)`` independent of the input voltage, so
``(ton + tdis)/T = sqrt(dcm_k) < 1`` for every Vin - the converter is in DCM
everywhere.  ``design_flyback`` still verifies it numerically.

Checks performed here
    * ``Dmax <= dmax_limit`` (spec target) - warning if a caller-forced
      ``vor_target`` breaks it, hard error above 0.90.
    * CCM: ``Lp > Lbcm`` (equivalently ``ripple_k < 1``).
    * DCM: ``ton + tdis <= T``.
    * ``verify_power_balance()`` reconstructs Pin from the computed currents.
"""

from __future__ import annotations

from typing import List, Optional

from .errors import OPL_E_INPUT, OPL_E_RANGE, OplError, check_number, require
from .model import DesignSpec, FlybackDesign

__all__ = [
    "design_flyback",
    "duty_from_vor",
    "duty_ccm",
    "duty_dcm",
    "peak_current_ccm",
    "peak_current_dcm",
    "boundary_inductance",
    "trapezoid_rms",
    "primary_rms",
    "secondary_rms",
    "discharge_time_dcm",
    "verify_power_balance",
]

_SQRT2 = 2.0 ** 0.5


# ---------------------------------------------------------------------------
# primitive formulas (each is used by the tests against hand calculations)
# ---------------------------------------------------------------------------


def duty_from_vor(vor: float, vin_dc: float) -> float:
    """CCM duty cycle ``Vor / (Vin + Vor)``, dimensionless.

    ``vor`` in V (reflected voltage), ``vin_dc`` in V (bulk DC voltage).
    Raises ``OPL-E-INPUT`` for a non-positive sum.
    """
    vor = check_number("vor", vor, lo=0.0, unit="V", lo_inclusive=False)
    vin_dc = check_number("vin_dc", vin_dc, lo=0.0, unit="V")
    require(vin_dc + vor > 0.0, OPL_E_INPUT, "vin_dc + vor must be > 0")
    return vor / (vin_dc + vor)


def duty_ccm(vin_dc: float, vor: float) -> float:
    """Alias of :func:`duty_from_vor` (argument order Vin, Vor)."""
    return duty_from_vor(vor, vin_dc)


def duty_dcm(pin: float, lp: float, fsw: float, vin_dc: float) -> float:
    """DCM duty cycle ``sqrt(2*Pin*Lp*fsw)/Vin``, dimensionless.

    ``pin`` W, ``lp`` H, ``fsw`` Hz, ``vin_dc`` V.
    Raises ``OPL-E-RANGE`` when the result is >= 1 (no DCM solution).
    """
    pin = check_number("pin", pin, lo=0.0, unit="W", lo_inclusive=False)
    lp = check_number("lp", lp, lo=0.0, unit="H", lo_inclusive=False)
    fsw = check_number("fsw", fsw, lo=0.0, unit="Hz", lo_inclusive=False)
    vin_dc = check_number("vin_dc", vin_dc, lo=0.0, unit="V", lo_inclusive=False)
    d = (2.0 * pin * lp * fsw) ** 0.5 / vin_dc
    if d >= 1.0:
        raise OplError(
            OPL_E_RANGE,
            "DCM duty cycle {0:.3f} >= 1 at Vin={1:g} V".format(d, vin_dc),
            "reduce Lp (smaller dcm_k) or raise the switching frequency",
        )
    return d


def peak_current_ccm(pin: float, vin_dc: float, dmax: float, ripple_k: float) -> float:
    """CCM primary peak current ``2*Pin / (Vin*D*(2-kr))``, A.

    ``pin`` W, ``vin_dc`` V, ``dmax`` dimensionless, ``ripple_k`` dimensionless.
    """
    pin = check_number("pin", pin, lo=0.0, unit="W", lo_inclusive=False)
    vin_dc = check_number("vin_dc", vin_dc, lo=0.0, unit="V", lo_inclusive=False)
    dmax = check_number("dmax", dmax, lo=0.0, hi=1.0, unit="-", lo_inclusive=False)
    ripple_k = check_number(
        "ripple_k", ripple_k, lo=0.0, hi=1.0, unit="-", lo_inclusive=False
    )
    return 2.0 * pin / (vin_dc * dmax * (2.0 - ripple_k))


def peak_current_dcm(pin: float, vin_dc: float, duty: float) -> float:
    """DCM primary peak current ``2*Pin / (Vin*D)``, A."""
    pin = check_number("pin", pin, lo=0.0, unit="W", lo_inclusive=False)
    vin_dc = check_number("vin_dc", vin_dc, lo=0.0, unit="V", lo_inclusive=False)
    duty = check_number("duty", duty, lo=0.0, hi=1.0, unit="-", lo_inclusive=False)
    return 2.0 * pin / (vin_dc * duty)


def boundary_inductance(pin: float, vin_dc: float, duty: float, fsw: float) -> float:
    """Boundary (critical) inductance ``(Vin*D)^2 / (2*Pin*fsw)``, H.

    Above this value the flyback runs in CCM at that operating point; below it,
    in DCM.
    """
    pin = check_number("pin", pin, lo=0.0, unit="W", lo_inclusive=False)
    vin_dc = check_number("vin_dc", vin_dc, lo=0.0, unit="V", lo_inclusive=False)
    duty = check_number("duty", duty, lo=0.0, hi=1.0, unit="-", lo_inclusive=False)
    fsw = check_number("fsw", fsw, lo=0.0, unit="Hz", lo_inclusive=False)
    return (vin_dc * duty) ** 2 / (2.0 * pin * fsw)


def trapezoid_rms(i_start: float, i_end: float, duty: float) -> float:
    """RMS of a trapezoidal current of duration fraction ``duty``, A.

    ``sqrt(duty*(i1^2 + i1*i2 + i2^2)/3)`` with ``i1, i2`` in A and ``duty``
    dimensionless in (0, 1].  Reduces to a rectangle for ``i1 == i2`` and to a
    triangle for ``i1 == 0``.
    """
    i_start = check_number("i_start", i_start, lo=0.0, unit="A")
    i_end = check_number("i_end", i_end, lo=0.0, unit="A")
    duty = check_number("duty", duty, lo=0.0, hi=1.0, unit="-", lo_inclusive=False)
    return (duty * (i_start * i_start + i_start * i_end + i_end * i_end) / 3.0) ** 0.5


def primary_rms(ipk: float, krip: float, duty: float) -> float:
    """RMS switch (primary) current over a full period, A.

    ``ipk`` A, ``krip`` dimensionless (0 = flat, 1 = triangular), ``duty``
    dimensionless (the on-time fraction).
    """
    ipk = check_number("ipk", ipk, lo=0.0, unit="A")
    krip = check_number("krip", krip, lo=0.0, hi=1.0, unit="-")
    return trapezoid_rms(ipk * (1.0 - krip), ipk, duty)


def secondary_rms(ipk: float, krip: float, duty_off: float, n: float) -> float:
    """RMS secondary winding current over a full period, A.

    Ampere-turn equality gives ``Is = n * Ip`` with ``n = Np/Ns``, so this is
    ``n * trapezoid_rms(ipk*(1-krip), ipk, duty_off)``.
    """
    n = check_number("n", n, lo=0.0, unit="-", lo_inclusive=False)
    return n * primary_rms(ipk, krip, duty_off)


def discharge_time_dcm(ipk: float, lp: float, n: float, vout_ref: float) -> float:
    """DCM secondary discharge time ``Ipk*Lp/(n*Vout_ref)``, s."""
    ipk = check_number("ipk", ipk, lo=0.0, unit="A")
    lp = check_number("lp", lp, lo=0.0, unit="H", lo_inclusive=False)
    n = check_number("n", n, lo=0.0, unit="-", lo_inclusive=False)
    vout_ref = check_number("vout_ref", vout_ref, lo=0.0, unit="V", lo_inclusive=False)
    return ipk * lp / (n * vout_ref)


# ---------------------------------------------------------------------------
# the design routine
# ---------------------------------------------------------------------------


def design_flyback(spec: DesignSpec, vor_target: Optional[float] = None) -> FlybackDesign:
    """Design the flyback main circuit for ``spec``.

    Parameters
    ----------
    spec : :class:`opl.model.DesignSpec`
        Input specification (see the class docstring for every unit).
    vor_target : float or None
        Optional **forced reflected voltage in V**.  ``None`` derives Vor from
        ``spec.dmax_target`` - the normal path.  A forced value is still checked
        against ``spec.dmax_limit``.

    Returns
    -------
    :class:`opl.model.FlybackDesign`
        ``mode`` is ``"CCM"`` or ``"DCM"`` (never ``"AUTO"``).

    Raises
    ------
    ``OplError(OPL-E-INPUT)``
        Malformed arguments (validated by :class:`DesignSpec`).
    ``OplError(OPL-E-RANGE)``
        The requested operating point has no physical solution: D >= 1, DCM
        discharge not finishing inside the off-time, or D > 0.90.
    """
    require(isinstance(spec, DesignSpec), OPL_E_INPUT, "spec must be a DesignSpec")

    pout = spec.pout
    pin = spec.pin
    fsw = spec.fsw
    vout_ref = spec.vout_ref
    vin_min = spec.vin_dc_min(0.0)
    vin_max = spec.vin_dc_max()
    warnings: List[str] = []

    require(
        vin_min > 0.0,
        OPL_E_INPUT,
        "vac_min={0:g} Vrms leaves no bulk voltage after a {1:g} V bridge drop".format(
            spec.vac_min, spec.bridge_drop
        ),
    )

    mode = spec.mode
    if mode == "AUTO":
        mode = "CCM" if spec.ripple_k < 1.0 else "DCM"

    # --- step 1: reflected voltage and turns ratio -------------------------
    dmax_design = spec.dmax_target
    if vor_target is None:
        vor = vin_min * dmax_design / (1.0 - dmax_design)
        vor_forced = False
    else:
        vor = check_number("vor_target", vor_target, lo=0.0, unit="V", lo_inclusive=False)
        vor_forced = True
    if vor <= 0.0:
        raise OplError(OPL_E_INPUT, "reflected voltage must be > 0")
    n = vor / vout_ref
    require(
        n > 1.0,
        OPL_E_RANGE,
        "turns ratio n={0:.3f} <= 1: the reflected voltage {1:.2f} V is below the "
        "secondary voltage {2:.2f} V".format(n, vor, vout_ref),
        "raise dmax_target or lower vout/vf_sec",
    )
    dmax = duty_from_vor(vor, vin_min)
    dmin = duty_from_vor(vor, vin_max)

    if dmax >= 0.90:
        raise OplError(
            OPL_E_RANGE,
            "Dmax={0:.3f} is not buildable (>= 0.90)".format(dmax),
            "lower vor_target or dmax_target",
        )
    if dmax > spec.dmax_limit:
        warnings.append(
            "Dmax={0:.4f} exceeds dmax_limit={1:.2f} "
            "({2})".format(dmax, spec.dmax_limit, "forced vor_target" if vor_forced else "spec")
        )

    # --- step 2/3/4: mode-specific inductance, currents, RMS ---------------
    lbcm = boundary_inductance(pin, vin_min, dmax, fsw)

    if mode == "CCM":
        kr = spec.ripple_k
        if kr >= 1.0:
            warnings.append(
                "ripple_k={0:.3f} means boundary/DCM operation; CCM formulas "
                "degenerate to the BCM case".format(kr)
            )
        ipk = peak_current_ccm(pin, vin_min, dmax, kr)
        ip1 = ipk * (1.0 - kr)
        # dI = kr*Ipk ; Lp = Vin*D/(dI*fsw)   (= Lbcm*(2-kr)/kr)
        lp = vin_min * dmax / (kr * ipk * fsw)
        require(
            lp > lbcm * 0.999,
            OPL_E_RANGE,
            "CCM requested but Lp={0:.6g} H is not above the boundary "
            "inductance {1:.6g} H".format(lp, lbcm),
            "increase ripple_k towards 1.0 (this moves the design towards BCM/DCM)",
        )
        tdis = (1.0 - dmax) / fsw
        krip = kr
    else:  # DCM
        k = spec.dcm_k
        lp = k * lbcm
        dmax = dmax_design * k ** 0.5
        dmin = dmax * vin_min / vin_max
        # DCM discharge: tdis/T = (1 - Dmax_t)*sqrt(k), independent of Vin
        d2 = (1.0 - dmax_design) * k ** 0.5
        tdis = d2 / fsw
        ipk = peak_current_dcm(pin, vin_min, dmax)
        ip1 = 0.0
        krip = 1.0
        if dmax + tdis * fsw > 1.0 + 1e-12:
            raise OplError(
                OPL_E_RANGE,
                "DCM requested but ton+tdis = {0:.4f} T > T at Vin_min".format(
                    dmax + tdis * fsw
                ),
                "reduce dcm_k",
            )
        if spec.mode == "DCM" and dmax > spec.dmax_limit:
            warnings.append(
                "DCM Dmax={0:.4f} exceeds dmax_limit={1:.2f}".format(dmax, spec.dmax_limit)
            )

    irms_pri = primary_rms(ipk, krip, dmax)
    duty_off = 1.0 - dmax if mode == "CCM" else tdis * fsw
    irms_sec = secondary_rms(ipk, krip, duty_off, n)
    is_pk = n * ipk
    is_avg = pin / vout_ref  # ampere-turn balance identity, see module docstring

    design = FlybackDesign(
        spec=spec,
        mode=mode,
        n=n,
        vor=vor,
        dmax=dmax,
        dmin=dmin,
        lp=lp,
        lp_bcm=lbcm,
        ipk=ipk,
        ip1=ip1,
        krip=krip,
        irms_pri=irms_pri,
        irms_sec=irms_sec,
        is_pk=is_pk,
        is_avg=is_avg,
        ton=(dmax if mode == "CCM" else dmax) / fsw,
        tdis=tdis,
        vin_dc_min=vin_min,
        vin_dc_max=vin_max,
        dmax_limit=spec.dmax_limit,
        warnings=warnings,
    )

    # self-consistency: reconstruct Pin from the computed currents
    ratio = verify_power_balance(design)
    if abs(ratio - 1.0) > 1e-6:
        design.warnings.append(
            "power balance self-check deviates by {0:.3e} (relative)".format(ratio - 1.0)
        )
    if pout <= 0.0:  # pragma: no cover - guarded by DesignSpec
        raise OplError(OPL_E_INPUT, "output power must be > 0")
    return design


def verify_power_balance(design: FlybackDesign) -> float:
    """Reconstruct ``Pin`` from the computed currents; return the ratio [-].

    CCM: ``Pin = 0.5*(Ip1+Ipk) * Vin_min * Dmax``.
    DCM: ``Pin = 0.5 * Lp * Ipk^2 * fsw``.

    A value of exactly 1.0 proves the duty/inductance/current formulas agree
    with the power balance - this is what the test suite pins down.
    """
    if design.mode == "CCM":
        pin_calc = 0.5 * (design.ip1 + design.ipk) * design.vin_dc_min * design.dmax
    else:
        pin_calc = 0.5 * design.lp * design.ipk ** 2 * design.spec.fsw
    return pin_calc / design.spec.pin
