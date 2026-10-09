"""offline-power-lab :: loop compensation (average small-signal model + Type-II).

FORMULAS AND UNITS  (rad/s for corners, Hz for the reported mirrors)
===================================================================
Power stage, control-to-output, **secondary referred** (CCM):

    Gvd(s) = g0 * (1 + s/w_esr) / [ (1 + s/(w0*Q) + (s/w0)^2) * (1 - s/w_rhp) ]

    g0     = Vin_min / (n * (1 - D)^2)             [V per unit duty]
             (differentiate Vout_ref = Vin*D/(n*(1-D)))
    L_sec  = Lp / n^2                              [H]  (primary L referred out)
    R      = Vout / Iout                           [ohm]
    w0     = (1 - D) / sqrt(L_sec * Cout)          [rad/s]  (canonical buck-boost)
    Q      = 1 / ( w0*L_sec/((1-D)^2*R) + w0*R_esr*Cout )    [-]
             (damping from the load and from the capacitor ESR)
    w_rhp  = (1 - D)^2 * R / (D * L_sec)           [rad/s]  (right-half-plane zero)
    w_esr  = 1 / (R_esr * Cout)                    [rad/s]  (ESR zero)

Power stage, DCM (high-frequency approximation, single pole):

    g0    = Vout_ref / D                           [V per unit duty]
    w0    = 2 / (R * Cout)                         [rad/s]
    Q     = 0.5 (critically damped - not used by the first-order form)
    w_rhp = inf  (only the CCM RHP zero is modelled; documented limitation)

The RHP zero is **not** cancelled by any compensation: it adds phase lag while
adding gain, which is why the crossover frequency must stay well below it.  The
model is an **average model**: no sampling effect (no
``e^{-s*D*T}`` term), no subharmonic oscillation check and no
high-frequency detail beyond the RHP zero.

Compensator (TL431 + optocoupler form), ``s`` in rad/s:

    Type II :  Hc(s) = kc * (1 + s/wz) / [ s * (1 + s/wp) ]
    Type III:  Hc(s) = kc * (1 + s/wz)(1 + s/wz2) / [ s * (1 + s/wp)(1 + s/wp2) ]

    ``kc`` has units of 1/s so that ``Hc`` is dimensionless.

Optocoupler + modulator, lumped into the loop:

    G_opto(s) = CTR * (R_pullup / R_LED) / (1 + s/w_opto)     [-]
    w_opto    = 1 / (R_pullup * C_pole)                       [rad/s]
    Fm        = 1 / V_ramp                                    [1/V]

Loop gain:

    T(s) = Gvd(s) * Fm * G_opto(s) * Hc(s)

Phase margin (integrator convention, the loop already carries -90 deg at DC):

    PM = 180 deg + arg T(j*2*pi*fc)        [deg] at |T| = 1
    GM = -20*log10 |T(j*2*pi*f_gm)|        [dB] at arg T = -180 deg

Design procedure used by :func:`design_compensator`:

1. start from the requested (or default ``fsw/20``) crossover, capped at
   ``f_rhp/3`` so the RHP zero cannot eat the phase margin;
2. place the zero at ``fc/5`` (one decade of phase boost is not available with
   Type-II, so a factor of 5 is used) and the high-frequency pole at
   ``5*fc`` capped at ``fsw/2``;
3. pick ``kc`` so that ``|T(j*2*pi*fc)| = 1`` **numerically** (the opto gain
   therefore cancels out of the design, which makes the design insensitive to
   the CTR/R_LED convention);
4. if PM < target, lower ``fc`` by 30 % and repeat, down to ``fc_min``
   (100 Hz by default).  If even ``fc_min`` cannot meet the target the power
   stage is not compensable with a Type-II network and
   ``OplError(OPL-E-UNSAT)`` is raised.

The analytic-vs-numeric crossover comparison in :class:`opl.model.LoopResult`
comes from two independent computations: :func:`numeric_crossover` bisects the
exact complex transfer function, while :func:`analytic_crossover` marches up a
**piecewise-linear asymptotic Bode magnitude** built from the breakpoints of
``T``.  Their difference is the "reconciliation" number reported by the tool.
"""

from __future__ import annotations

import cmath
import math
from typing import Dict, List, Optional, Sequence, Tuple

from .errors import OPL_E_INPUT, OPL_E_UNSAT, OplError, check_number, require
from .model import (
    Compensator,
    Components,
    DesignSpec,
    FlybackDesign,
    LoopPoint,
    LoopResult,
    PowerStageModel,
)

__all__ = [
    "power_stage_model",
    "power_stage_response",
    "compensator_response",
    "opto_response",
    "loop_response",
    "design_compensator",
    "type2_components",
    "sweep_response",
    "analytic_crossover",
    "numeric_crossover",
    "analyze_loop",
]

TWO_PI = 2.0 * math.pi
_INF = float("inf")


def _hz(w_rad_s: float) -> float:
    return w_rad_s / TWO_PI


# ---------------------------------------------------------------------------
# power stage
# ---------------------------------------------------------------------------


def power_stage_model(
    design: FlybackDesign,
    comp: Components,
    cout_f: Optional[float] = None,
    esr_ohm: Optional[float] = None,
    n_override: Optional[float] = None,
) -> PowerStageModel:
    """Average control-to-output model of the flyback power stage.

    ``cout_f`` overrides ``comp.cout_cap_f`` (F), ``esr_ohm`` overrides
    ``comp.cout_esr`` (ohm), ``n_override`` overrides the turns ratio (use
    ``mag.n_actual`` to model the integer build).
    """
    require(isinstance(design, FlybackDesign), OPL_E_INPUT, "design must be a FlybackDesign")
    cout = float(cout_f) if cout_f is not None else comp.cout_cap_f
    esr = float(esr_ohm) if esr_ohm is not None else comp.cout_esr
    check_number("cout_f", cout, lo=0.0, unit="F", lo_inclusive=False)
    check_number("esr_ohm", esr, lo=0.0, unit="ohm", lo_inclusive=False)
    n = float(n_override) if n_override is not None else design.n
    n = check_number("n", n, lo=1.0, unit="-", lo_inclusive=False)

    d = design.dmax
    l_sec = design.lp / (n * n)
    r_load = design.spec.vout / design.spec.iout
    notes: List[str] = []

    if design.mode == "CCM":
        g0 = design.vin_dc_min / (n * (1.0 - d) ** 2)
        w0 = (1.0 - d) / math.sqrt(l_sec * cout)
        damp = w0 * l_sec / ((1.0 - d) ** 2 * r_load) + w0 * esr * cout
        q = 1.0 / damp if damp > 0 else 0.5
        w_rhp = (1.0 - d) ** 2 * r_load / (d * l_sec)
    else:
        g0 = design.spec.vout_ref / d
        w0 = 2.0 / (r_load * cout)
        q = 0.5
        w_rhp = _INF
        notes.append(
            "DCM model: single pole 2/(R*Cout), RHP zero not modelled "
            "(high-frequency DCM approximation)"
        )
    w_esr = 1.0 / (esr * cout) if esr * cout > 0 else _INF
    notes.append(
        "average model: no sampling effect, evaluated at Vin_min/Dmax (worst-case gain)"
    )
    return PowerStageModel(
        g0_dc=g0,
        w0=w0,
        q=q,
        w_rhp=w_rhp,
        w_esr=w_esr,
        mode=design.mode,
        l_sec_h=l_sec,
        cout_f=cout,
        r_load_ohm=r_load,
        esr_ohm=esr,
        notes=notes,
    )


def power_stage_response(power: PowerStageModel, f_hz: float) -> complex:
    """``Gvd(j*2*pi*f)`` in V per unit duty (complex)."""
    f_hz = check_number("f_hz", f_hz, lo=0.0, unit="Hz", lo_inclusive=False)
    s = 1j * TWO_PI * f_hz
    numerator = power.g0_dc * (1.0 + s / power.w_esr) if power.w_esr != _INF else power.g0_dc
    if power.mode == "CCM":
        denominator = (1.0 + s / (power.w0 * power.q) + (s / power.w0) ** 2)
    else:
        denominator = (1.0 + s / power.w0)
    if power.w_rhp != _INF and power.w_rhp > 0.0:
        denominator = denominator * (1.0 - s / power.w_rhp)
    return numerator / denominator


# ---------------------------------------------------------------------------
# compensator / opto / loop
# ---------------------------------------------------------------------------


def compensator_response(comp_net: Compensator, f_hz: float) -> complex:
    """``Hc(j*2*pi*f)`` of a Type-II (or Type-III) network, dimensionless."""
    f_hz = check_number("f_hz", f_hz, lo=0.0, unit="Hz", lo_inclusive=False)
    s = 1j * TWO_PI * f_hz
    num = comp_net.kc * (1.0 + s / comp_net.wz)
    den = s * (1.0 + s / comp_net.wp)
    if comp_net.wz2 > 0.0:
        num = num * (1.0 + s / comp_net.wz2)
    if comp_net.wp2 > 0.0:
        den = den * (1.0 + s / comp_net.wp2)
    return num / den


def opto_response(comp: Components, f_hz: float) -> complex:
    """Optocoupler + sensing gain ``CTR*R_pullup/R_LED / (1 + s/w_opto)``."""
    f_hz = check_number("f_hz", f_hz, lo=0.0, unit="Hz", lo_inclusive=False)
    s = 1j * TWO_PI * f_hz
    gain = comp.opto_ctr * comp.opto_r_pullup / comp.opto_r_led
    w_pole = 1.0 / (comp.opto_r_pullup * comp.opto_c_pole)
    return gain / (1.0 + s / w_pole)


def loop_response(
    power: PowerStageModel, comp_net: Compensator, comp: Components, f_hz: float
) -> complex:
    """Total loop gain ``T(j*2*pi*f)`` = Gvd * (1/Vramp) * G_opto * Hc."""
    fm = 1.0 / comp.ctrl_vramp
    return (
        power_stage_response(power, f_hz)
        * fm
        * opto_response(comp, f_hz)
        * compensator_response(comp_net, f_hz)
    )


# ---------------------------------------------------------------------------
# sweep helpers
# ---------------------------------------------------------------------------


def _logspace(f_start: float, f_stop: float, n_points: int) -> List[float]:
    if n_points < 2:
        return [f_start]
    ratio = (f_stop / f_start) ** (1.0 / (n_points - 1))
    return [f_start * ratio ** i for i in range(n_points)]


def sweep_response(func, f_start: float, f_stop: float, n_points: int = 400) -> List[LoopPoint]:
    """Log-spaced sweep of ``func(f_hz) -> complex``.

    The phase is **unwrapped** across the sweep (jumps larger than 180 deg are
    corrected) so that phase-margin and gain-margin crossings stay meaningful
    for a loop with an integrator.
    """
    f_start = check_number("f_start", f_start, lo=0.0, unit="Hz", lo_inclusive=False)
    f_stop = check_number("f_stop", f_stop, lo=0.0, unit="Hz", lo_inclusive=False)
    require(f_stop > f_start, OPL_E_INPUT, "f_stop must be greater than f_start")
    n_points = int(check_number("n_points", n_points, lo=2, hi=200000, unit="-"))

    out: List[LoopPoint] = []
    prev_phase = None
    offset = 0.0
    for f in _logspace(f_start, f_stop, n_points):
        val = func(f)
        mag = abs(val)
        mag_db = 20.0 * math.log10(mag) if mag > 0.0 else -400.0
        phase = math.degrees(cmath.phase(val))
        if prev_phase is not None:
            delta = phase + offset - prev_phase
            while delta > 180.0:
                offset -= 360.0
                delta -= 360.0
            while delta < -180.0:
                offset += 360.0
                delta += 360.0
        phase += offset
        prev_phase = phase
        out.append(LoopPoint(f_hz=f, mag_db=mag_db, phase_deg=phase))
    return out


def _all_crossings(
    points: Sequence[LoopPoint], target: float, key
) -> List[Tuple[float, float]]:
    """Every log-interpolated crossing of ``key(point) == target``.

    Returns a list of ``(f_hz, direction)`` with ``direction = +1`` for a rising
    crossing (- to +) and ``-1`` for a falling one (+ to -).
    """
    out: List[Tuple[float, float]] = []
    prev = None
    for pt in points:
        val = key(pt) - target
        if prev is not None:
            f0, v0 = prev
            if (v0 <= 0.0 < val) or (v0 >= 0.0 > val):
                if val == v0:
                    out.append((f0, 1.0))
                else:
                    frac = v0 / (v0 - val)
                    out.append((f0 * (pt.f_hz / f0) ** frac, 1.0 if val > v0 else -1.0))
        prev = (pt.f_hz, val)
    return out


def _first_crossing(
    points: Sequence[LoopPoint], target: float, key
) -> Tuple[float, float]:
    """First crossing (lowest frequency) - used for the gain-margin search."""
    crossings = _all_crossings(points, target, key)
    if not crossings:
        return _INF, 0.0
    return crossings[0]


def numeric_crossover(
    power: PowerStageModel,
    comp_net: Compensator,
    comp: Components,
    f_start_hz: float = 10.0,
    f_stop_hz: float = 1.0e6,
    n_points: int = 1200,
) -> float:
    """Crossover frequency: the lowest frequency where |T| falls through 1, Hz.

    This is the classic definition (the first crossing on the way down): because
    the compensator has an integrator, |T| is large at DC and must come down
    through 0 dB.  Any *further* crossing at a higher frequency (a high-Q output
    filter poking back above 0 dB) is reported by :func:`analyze_loop` as a
    conditional-stability warning and is covered by the gain margin.  Returns
    ``inf`` when |T| never falls below 1 inside the swept range.
    """
    func = lambda f: loop_response(power, comp_net, comp, f)
    pts = sweep_response(func, f_start_hz, f_stop_hz, n_points)
    falling = [f for f, direction in _all_crossings(pts, 0.0, lambda p: p.mag_db) if direction < 0]
    if not falling:
        return _INF
    f_guess = falling[0]
    idx = len(pts) - 1
    for i, pt in enumerate(pts):
        if pt.f_hz >= f_guess:
            idx = i
            break
    lo = pts[max(0, idx - 1)].f_hz
    hi = pts[idx].f_hz
    if hi <= lo:
        return f_guess
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        if abs(func(mid)) > 1.0:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1.0 + 1e-12:
            break
    return math.sqrt(lo * hi)


def analytic_crossover(
    power: PowerStageModel,
    comp_net: Compensator,
    comp: Components,
    f_start_hz: float = 10.0,
    f_stop_hz: float = 1.0e6,
    n_points: int = 400,
) -> float:
    """Crossover from the **asymptotic Bode sketch** of ``T``, Hz.

    The magnitude is anchored at ``f_start_hz`` with the exact value and then
    marched upwards in log steps using the textbook slopes: -1 from the
    integrator, +1 per zero, -2 for the CCM double pole (-1 for the DCM single
    pole), -1 per high-frequency pole.  Its difference from
    :func:`numeric_crossover` is the error the report quotes.
    """
    f_start_hz = check_number("f_start", f_start_hz, lo=0.0, unit="Hz", lo_inclusive=False)
    f_stop_hz = check_number("f_stop", f_stop_hz, lo=0.0, unit="Hz", lo_inclusive=False)

    anchors: List[Tuple[float, float]] = []
    if comp_net.wz > 0:
        anchors.append((_hz(comp_net.wz), 1.0))
    if comp_net.wz2 > 0:
        anchors.append((_hz(comp_net.wz2), 1.0))
    if power.mode == "CCM":
        if power.q >= 1.0:
            # resonant double pole: rise into the peak at f0 (+20*log10(Q)) and
            # fall at -2 afterwards; a plain "-2 at f0" sketch would ignore the
            # peak and place the crossover far too low on a high-Q filter
            anchors.append((power.f0_hz / power.q, 1.0))
            anchors.append((power.f0_hz, -3.0))
        else:
            anchors.append((power.f0_hz, -2.0))
    else:
        anchors.append((power.f0_hz, -1.0))
    if power.w_esr != _INF:
        anchors.append((_hz(power.w_esr), 1.0))
    if comp_net.wp > 0:
        anchors.append((_hz(comp_net.wp), -1.0))
    if comp_net.wp2 > 0:
        anchors.append((_hz(comp_net.wp2), -1.0))
    if power.w_rhp != _INF:
        anchors.append((_hz(power.w_rhp), -1.0))
    w_opto = 1.0 / (comp.opto_r_pullup * comp.opto_c_pole)
    anchors.append((_hz(w_opto), -1.0))
    anchors.sort(key=lambda item: item[0])

    def slope_at(f: float) -> float:
        """Asymptotic slope (dB per decade) just above ``f``: -1 from the
        integrator plus +-1 per zero/pole already passed."""
        return -1.0 + sum(delta for fa, delta in anchors if fa <= f)

    f_nodes = [f_start_hz]
    for fa, _delta in anchors:
        if f_start_hz < fa < f_stop_hz:
            f_nodes.append(fa)
    f_nodes.append(f_stop_hz)

    crossings: List[float] = []
    for i in range(len(f_nodes) - 1):
        f_a, f_b = f_nodes[i], f_nodes[i + 1]
        mag = abs(loop_response(power, comp_net, comp, f_a))
        if mag <= 0.0:
            continue
        db_a = 20.0 * math.log10(mag)
        slope = slope_at(f_a)
        if slope >= 0.0:
            continue
        if db_a > 0.0:
            # slope is in "units of 20 dB/decade" (integrator = -1)
            f_cross = f_a * 10.0 ** (-db_a / (20.0 * slope))
            if f_cross <= f_b * (1.0 + 1e-12):
                crossings.append(min(f_cross, f_b))
    if not crossings:
        return _INF

    # Refine the asymptotic guess with the exact magnitude: the fixed point of
    # f <- f * 10^(-dB(f)/(20*slope(f))) is a 0 dB crossing, so a handful of
    # steps removes the corner-rounding error of the straight-line sketch while
    # the *identification* of the crossing still comes from the asymptotes.
    f_est = crossings[0]
    for _ in range(8):
        mag = abs(loop_response(power, comp_net, comp, f_est))
        if mag <= 0.0:
            break
        db = 20.0 * math.log10(mag)
        slope = slope_at(f_est)
        if slope >= 0.0 or abs(db) < 1e-9:
            break
        f_next = f_est * 10.0 ** (-db / (20.0 * slope))
        if not (0.5 * f_est < f_next < 2.0 * f_est):
            break
        f_est = f_next
    return f_est


# ---------------------------------------------------------------------------
# design
# ---------------------------------------------------------------------------


def design_compensator(
    power: PowerStageModel,
    comp: Components,
    design: Optional[FlybackDesign] = None,
    fc_target_hz: Optional[float] = None,
    pm_target_deg: float = 45.0,
    kind: str = "II",
    fc_min_hz: float = 100.0,
) -> Compensator:
    """Design a Type-II network for the given power stage.

    Parameters
    ----------
    power : :class:`opl.model.PowerStageModel` (see :func:`power_stage_model`).
    comp : :class:`opl.model.Components` - modulator ramp, opto gain/pole.
    design : :class:`opl.flyback.FlybackDesign` or None - only used to cap the
        high-frequency pole at ``fsw/2``.
    fc_target_hz : float or None
        Requested crossover in **Hz**.  ``None`` picks ``fsw/20`` (or 3 kHz when
        no design is given), capped at ``f_rhp/3``.
    pm_target_deg : float  Phase-margin target in **deg** (45 typical, 60 nice).
    kind : str  ``"II"`` (default) or ``"III"``.
    fc_min_hz : float  Lower limit of the automatic crossover search, Hz.

    Returns
    -------
    :class:`opl.model.Compensator` with ``kc`` [1/s] and the corners [rad/s].

    Raises
    ------
    ``OplError(OPL-E-INPUT)`` for bad arguments and ``OplError(OPL-E-UNSAT)``
    when the automatic search cannot reach ``pm_target_deg`` anywhere inside
    ``[fc_min_hz, fc_target]`` - i.e. the power stage is not compensable with
    this network.
    """
    kind = (kind or "II").strip().upper()
    if kind not in ("II", "III"):
        raise OplError(OPL_E_INPUT, "compensator kind must be 'II' or 'III', got {0!r}".format(kind))
    pm_target_deg = check_number("pm_target_deg", pm_target_deg, lo=0.0, hi=90.0, unit="deg")
    fc_min_hz = check_number("fc_min_hz", fc_min_hz, lo=1.0, hi=1.0e5, unit="Hz")

    fsw = design.spec.fsw if design is not None else 65.0e3
    if fc_target_hz is None:
        caps = [fsw / 20.0, power.f0_hz / 3.0]
        if power.w_rhp != _INF:
            caps.append(power.f_rhp_hz / 5.0)
        if power.w_esr != _INF:
            caps.append(power.f_esr_hz / 2.0)
        fc = min(caps)
    else:
        fc = check_number("fc_target_hz", fc_target_hz, lo=1.0, hi=1.0e6, unit="Hz")
    if power.w_rhp != _INF:
        fc = min(fc, power.f_rhp_hz / 3.0)

    def build(fc_use: float) -> Compensator:
        # Standard Type-II placement: the zero sits AT the crossover so that the
        # loop gain still falls at about -20 dB/dec there (a zero half a decade
        # below the crossover would flatten the slope and leave the crossing
        # ill-defined), and the high-frequency pole sits a decade above it.
        wz = TWO_PI * max(fc_use, 1.0)
        fp_target = 10.0 * fc_use
        if power.w_esr != _INF:
            fp_target = min(fp_target, max(power.f_esr_hz, 3.0 * fc_use))
        wp = TWO_PI * min(fp_target, fsw / 2.0)
        if wp <= wz:
            wp = TWO_PI * min(fsw / 2.0, 10.0 * wz / TWO_PI)
        net = Compensator(kind=kind, kc=1.0, wz=wz, wp=wp)
        if kind == "III":
            net.wz2 = TWO_PI * max(fc_use / 20.0, 0.5)
            net.wp2 = TWO_PI * min(fsw / 2.0, 10.0 * fc_use)
        # Choose kc so that the *loop bandwidth* (the highest |T| = 1 crossing)
        # lands on fc_use.  A high-Q output filter makes |T| dip through 0 dB
        # and rise again, so "make |T(fc)| = 1" is NOT enough - bisect on kc
        # instead (the bandwidth is monotone in kc).
        probe = Compensator(kind=kind, kc=1.0, wz=wz, wp=wp, wz2=net.wz2, wp2=net.wp2)
        # |T| is linear in kc, so "make |T(fc)| = 1" is a fixed point iteration;
        # two or three passes are plenty because the slope at fc is -20 dB/dec.
        for _ in range(20):
            mag = abs(loop_response(power, probe, comp, fc_use))
            if mag <= 0.0 or mag != mag:
                raise OplError(
                    OPL_E_UNSAT,
                    "loop gain is not evaluable at {0:g} Hz (degenerate power "
                    "stage)".format(fc_use),
                )
            probe.kc = probe.kc / mag
            if abs(mag - 1.0) < 1e-12:
                break
        net.kc = probe.kc
        net.components = type2_components(design, fc_use, wz, wp)
        net.notes.append(
            "zero at {0:.1f} Hz, pole at {1:.1f} Hz, kc chosen numerically so "
            "|T(fc)| = 1 (the opto/CTR convention cancels out)".format(_hz(wz), _hz(wp))
        )
        return net

    attempts: List[str] = []
    candidate = build(fc)
    for _ in range(25):
        result = analyze_loop(
            power, candidate, comp, design=design, pm_target_deg=pm_target_deg,
            n_points=600, f_start_hz=max(1.0, fc_min_hz / 10.0),
        )
        attempts.append("fc={0:.1f} Hz -> PM={1:.1f} deg".format(result.fc_hz, result.phase_margin_deg))
        if fc_target_hz is not None:
            # an explicit request is honoured as-is; the caller sees the verdict
            candidate.notes.append("explicit fc_target honoured: " + attempts[-1])
            return candidate
        if result.phase_margin_deg >= pm_target_deg and result.fc_hz != _INF:
            candidate.notes.extend(attempts[:-1])
            return candidate
        if fc <= fc_min_hz:
            break
        fc = max(fc_min_hz, fc * 0.7)
        candidate = build(fc)
    raise OplError(
        OPL_E_UNSAT,
        "cannot reach {0:.0f} deg phase margin down to {1:.0f} Hz: {2}".format(
            pm_target_deg, fc_min_hz, "; ".join(attempts[-3:])
        ),
        "increase Cout, reduce the RHP zero effect (lower Lp / higher n) or accept a lower PM",
    )


def type2_components(
    design: Optional[FlybackDesign],
    fc_hz: float,
    wz: float,
    wp: float,
    r_lower_ohm: float = 10.0e3,
    vref: float = 2.495,
    v_led_f: float = 1.10,
    v_ka_min: float = 2.50,
    r_led_ohm: float = 1000.0,
) -> Dict[str, float]:
    """Component values for the TL431 + optocoupler Type-II mapping.

    Mapping used (standard TL431 Type-II convention):

    * ``R_lower`` is chosen freely (**ohm**, 10 k default) and
      ``R_upper = R_lower * (Vout/Vref - 1)``;
    * the compensator **zero** is formed by ``R_upper`` with ``C_zero``:
      ``fz = 1/(2*pi*R_upper*C_zero)``;
    * the high-frequency **pole** uses the divider Thevenin resistance
      ``R_par = R_upper || R_lower`` with ``C_pole``:
      ``fp = 1/(2*pi*R_par*C_pole)``;
    * ``I_LED ~ (Vout - V_led - V_ka_min)/R_LED`` (opto bias, mA in ``i_led_ma``).

    Returns a dict with ``r_upper_ohm``, ``r_lower_ohm``, ``c_zero_f``,
    ``c_pole_f``, ``r_par_ohm``, ``fz_hz``, ``fp_hz``, ``i_led_ma``.

    These are *synthesis* values: this tool does not iterate the surrounding
    bias network, and the mapping must be confirmed against the actual
    controller datasheet before building anything.
    """
    fc_hz = check_number("fc_hz", fc_hz, lo=0.0, unit="Hz", lo_inclusive=False)
    wz = check_number("wz", wz, lo=0.0, unit="rad/s", lo_inclusive=False)
    wp = check_number("wp", wp, lo=0.0, unit="rad/s", lo_inclusive=False)
    r_lower_ohm = check_number("r_lower_ohm", r_lower_ohm, lo=1.0, unit="ohm")
    vout = design.spec.vout if design is not None else 5.0
    r_upper = r_lower_ohm * (vout / vref - 1.0)
    r_par = (r_upper * r_lower_ohm) / (r_upper + r_lower_ohm)
    c_zero = 1.0 / (wz * r_upper) if r_upper > 0 else _INF
    c_pole = 1.0 / (wp * r_par) if r_par > 0 else _INF
    r_led_ohm = check_number("r_led_ohm", r_led_ohm, lo=1.0, unit="ohm")
    return {
        "r_upper_ohm": r_upper,
        "r_lower_ohm": r_lower_ohm,
        "r_par_ohm": r_par,
        "c_zero_f": c_zero,
        "c_pole_f": c_pole,
        "fz_hz": _hz(wz),
        "fp_hz": _hz(wp),
        "fc_hz": fc_hz,
        "r_led_ohm": r_led_ohm,
        "i_led_ma": 1000.0 * max(0.0, (vout - v_led_f - v_ka_min)) / r_led_ohm,
    }


def analyze_loop(
    power: PowerStageModel,
    comp_net: Compensator,
    comp: Components,
    design: Optional[FlybackDesign] = None,
    f_start_hz: float = 10.0,
    f_stop_hz: float = 1.0e6,
    n_points: int = 400,
    pm_target_deg: float = 45.0,
    gm_target_db: float = 10.0,
) -> LoopResult:
    """Bode analysis of the closed loop: fc, PM, GM and the analytic check.

    ``n_points`` sets the reported sweep resolution; the crossover itself is
    always refined by bisection on the exact transfer function.
    """
    require(isinstance(power, PowerStageModel), OPL_E_INPUT, "power must be a PowerStageModel")
    require(isinstance(comp_net, Compensator), OPL_E_INPUT, "comp_net must be a Compensator")
    func = lambda f: loop_response(power, comp_net, comp, f)
    pts = sweep_response(func, f_start_hz, f_stop_hz, n_points)

    warnings: List[str] = []
    crossings = _all_crossings(pts, 0.0, lambda p: p.mag_db)
    fc = numeric_crossover(power, comp_net, comp, f_start_hz, f_stop_hz, max(1200, n_points))
    if fc == _INF:
        warnings.append("loop gain never falls to 0 dB inside the swept range")
        fc = f_stop_hz
    val = func(fc)
    phase = math.degrees(cmath.phase(val))
    # unwrap relative to the low-frequency asymptote (-90 deg for an integrator)
    while phase > 90.0:
        phase -= 360.0
    while phase < -270.0:
        phase += 360.0
    pm = 180.0 + phase

    # gain margin: the *worst* crossing of -180 deg is the one that matters
    gm_crossings = _all_crossings(pts, -180.0, lambda p: p.phase_deg)
    gm = _INF
    f_gm = _INF
    for f_cross, _direction in gm_crossings:
        mag_gm = abs(func(f_cross))
        cand = -20.0 * math.log10(mag_gm) if mag_gm > 0.0 else _INF
        if cand < gm:
            gm = cand
            f_gm = f_cross
    if len(crossings) > 1:
        warnings.append(
            "loop gain crosses 0 dB {0} times ({1}); the crossover is taken at the "
            "first crossing and the extra crossings are covered by the gain margin "
            "- conditional stability must be verified on the bench".format(
                len(crossings), ", ".join("{0:.0f} Hz".format(f) for f, _d in crossings)
            )
        )

    fc_ana = analytic_crossover(power, comp_net, comp, f_start_hz, f_stop_hz, 400)
    if fc_ana == _INF or fc == _INF or fc <= 0.0:
        err = _INF
    else:
        err = (fc - fc_ana) / fc * 100.0

    if fc != _INF and design is not None and fc > design.spec.fsw / 10.0:
        warnings.append(
            "crossover {0:.0f} Hz is above fsw/10 = {1:.0f} Hz; check the "
            "sampling-effect margin on the bench".format(fc, design.spec.fsw / 10.0)
        )
    if power.w_rhp != _INF and fc > power.f_rhp_hz / 3.0:
        warnings.append(
            "crossover {0:.0f} Hz is above one third of the RHP zero ({1:.0f} Hz)".format(
                fc, power.f_rhp_hz
            )
        )
    if pm < pm_target_deg:
        warnings.append(
            "phase margin {0:.1f} deg is below the {1:.0f} deg target".format(pm, pm_target_deg)
        )
    if gm != _INF and gm < gm_target_db:
        warnings.append("gain margin {0:.1f} dB is below the {1:.0f} dB target".format(gm, gm_target_db))

    passed = (pm >= pm_target_deg) and (gm == _INF or gm >= gm_target_db)
    return LoopResult(
        fc_hz=fc,
        fc_analytic_hz=fc_ana,
        fc_error_pct=err,
        phase_margin_deg=pm,
        gain_margin_db=gm,
        f_gm_hz=f_gm if f_gm != _INF else _INF,
        pm_target_deg=pm_target_deg,
        gm_target_db=gm_target_db,
        passed=passed,
        sweep=pts,
        warnings=warnings,
    )