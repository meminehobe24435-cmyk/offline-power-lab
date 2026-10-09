"""offline-power-lab :: public data model (the "header file" of the project).

THIS FILE IS THE CONTRACT.  Every dataclass below documents, field by field:

* the physical meaning,
* **the unit** (SI unless stated otherwise: V, A, H, F, ohm, Hz, s, W, T, m, K),
* the legal domain (validated in ``__post_init__`` where it is cheap).

Conventions used across the whole package
-----------------------------------------
* Angles/temperatures: ``*_c`` is degrees Celsius, ``*_k`` is kelvin.
* ``vac_*`` is **RMS mains voltage** (Vrms), ``vin_dc_*`` is the **rectified
  bulk voltage** (V) after the input bridge drop.
* ``n`` is always the turns ratio ``Np / Ns`` (dimensionless, > 1 for a
  step-down flyback).
* ``vor`` is the reflected (secondary-to-primary) voltage ``n * (Vout + Vf)``
  in volts.
* Losses are watts, efficiencies are fractions in (0, 1] - never percent.
* Every result object carries ``warnings: List[str]``; a *warning* means the
  numbers are still produced but the design violates a soft guideline, while a
  raised :class:`OplError` means the numbers could not be produced at all.

Sign conventions: all currents are positive into the converter; the primary
current flows during the on-time, the secondary current during the off-time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .errors import (
    OPL_E_INPUT,
    check_choice,
    check_number,
    require,
)

__all__ = [
    "DesignSpec",
    "FlybackDesign",
    "CoreSpec",
    "WireSpec",
    "MagneticDesign",
    "DeratingRule",
    "StressItem",
    "StressReport",
    "Components",
    "PowerStageModel",
    "Compensator",
    "LoopPoint",
    "LoopResult",
    "SafetyRequirement",
    "SafetyResult",
    "EmiFilter",
    "EmiResult",
    "LossItem",
    "LossBudget",
    "DesignResult",
]

# ---------------------------------------------------------------------------
# 1. Input specification
# ---------------------------------------------------------------------------


@dataclass
class DesignSpec:
    """Input specification of an offline (mains-fed) AC-DC flyback converter.

    Parameters / units
    ------------------
    vac_min, vac_max : float
        Mains input range, **Vrms** (e.g. 90.0 .. 264.0 for universal input).
        ``vac_max`` is used for the voltage stress and Dmin, ``vac_min`` for
        Dmax, Lp and Ipk.
    vout : float
        Regulated output voltage, **V** (DC).
    iout : float
        Rated output current, **A** (DC).
    fsw : float
        Switching frequency of the main switch, **Hz** (not rad/s).
    eta_target : float
        Target end-to-end efficiency as a **fraction** (0.80 = 80 %).  Used to
        derive ``pin = pout / eta_target``; the *predicted* efficiency comes
        from :mod:`opl.budget`.
    line_freq : float
        Mains frequency, **Hz** (50.0 or 60.0).  Used for the bulk-capacitor
        ripple and the leakage-current calculation.
    bridge_drop : float
        Total forward drop of the input rectifier path, **V** (typically 1.4 V
        for a bridge with two diodes in the path).
    vf_sec : float
        Secondary rectifier forward drop used for the *reflected voltage*
        calculation, **V** (diode ~0.5 V for a Schottky, ~0.3 V for a
        synchronous rectifier operating point).
    dmax_limit : float
        Hard upper bound on the duty cycle, dimensionless.  Typical 0.50; the
        tool raises/warns above it.  Must lie in (0, 1).
    dmax_target : float
        Design target for Dmax at ``vac_min``, dimensionless.  Sets Vor.
    mode : str
        ``"CCM"``, ``"DCM"`` or ``"AUTO"``.  ``AUTO`` picks CCM when the
        requested ripple ratio is < 1.
    ripple_k : float
        CCM primary ripple ratio ``(Ipk - Ip1) / Ipk``, dimensionless, in
        (0, 1].  ``ripple_k = 1`` is exactly BCM; larger Lp gives CCM.
    dcm_k : float
        DCM only: ``Lp = dcm_k * Lp_bcm``, dimensionless, in (0, 1].
    """

    vac_min: float
    vac_max: float
    vout: float
    iout: float
    fsw: float
    eta_target: float = 0.80
    line_freq: float = 50.0
    bridge_drop: float = 1.4
    vf_sec: float = 0.50
    dmax_limit: float = 0.50
    dmax_target: float = 0.45
    mode: str = "CCM"
    ripple_k: float = 0.40
    dcm_k: float = 0.60

    def __post_init__(self) -> None:
        self.vac_min = check_number("vac_min", self.vac_min, lo=1.0, hi=1000.0, unit="Vrms")
        self.vac_max = check_number("vac_max", self.vac_max, lo=1.0, hi=1000.0, unit="Vrms")
        require(
            self.vac_max >= self.vac_min,
            OPL_E_INPUT,
            "vac_max ({0:g}) must be >= vac_min ({1:g})".format(self.vac_max, self.vac_min),
        )
        self.vout = check_number("vout", self.vout, lo=0.0, hi=1000.0, unit="V", lo_inclusive=False)
        self.iout = check_number("iout", self.iout, lo=0.0, hi=1000.0, unit="A", lo_inclusive=False)
        self.fsw = check_number("fsw", self.fsw, lo=1.0, hi=5.0e6, unit="Hz")
        self.eta_target = check_number(
            "eta_target", self.eta_target, lo=0.0, hi=1.0, lo_inclusive=False
        )
        self.line_freq = check_number("line_freq", self.line_freq, lo=1.0, hi=1000.0, unit="Hz")
        self.bridge_drop = check_number("bridge_drop", self.bridge_drop, lo=0.0, hi=20.0, unit="V")
        self.vf_sec = check_number("vf_sec", self.vf_sec, lo=0.0, hi=20.0, unit="V")
        self.dmax_limit = check_number(
            "dmax_limit", self.dmax_limit, lo=0.0, hi=1.0, unit="-", lo_inclusive=False, hi_inclusive=False
        )
        self.dmax_target = check_number(
            "dmax_target", self.dmax_target, lo=0.0, hi=1.0, unit="-", lo_inclusive=False, hi_inclusive=False
        )
        self.mode = check_choice("mode", self.mode, ("CCM", "DCM", "AUTO"))
        self.ripple_k = check_number(
            "ripple_k", self.ripple_k, lo=0.0, hi=1.0, unit="-", lo_inclusive=False
        )
        self.dcm_k = check_number(
            "dcm_k", self.dcm_k, lo=0.0, hi=1.0, unit="-", lo_inclusive=False
        )
        if self.dmax_target >= self.dmax_limit:
            require(
                self.dmax_target <= self.dmax_limit,
                OPL_E_INPUT,
                "dmax_target ({0:g}) must be <= dmax_limit ({1:g})".format(
                    self.dmax_target, self.dmax_limit
                ),
            )

    # -- derived quantities (all cheap, computed on demand) -----------------

    @property
    def pout(self) -> float:
        """Output power, **W**."""
        return self.vout * self.iout

    @property
    def pin(self) -> float:
        """Assumed input power ``pout / eta_target``, **W**."""
        return self.pout / self.eta_target

    @property
    def vout_ref(self) -> float:
        """Secondary winding voltage during off-time ``Vout + vf_sec``, **V**."""
        return self.vout + self.vf_sec

    def vin_dc_min(self, ripple_v: float = 0.0) -> float:
        """Minimum bulk DC voltage at ``vac_min``, **V**.

        ``ripple_v`` is the peak-to-peak low-frequency ripple on the bulk
        capacitor; the valley of that ripple is what the converter actually
        sees at full load, so the design must use the valley.
        """
        return self.vac_min * 2.0 ** 0.5 * 1.0 - self.bridge_drop - max(0.0, ripple_v)

    def vin_dc_max(self) -> float:
        """Peak bulk DC voltage at ``vac_max`` (no load), **V**."""
        return self.vac_max * 2.0 ** 0.5 - self.bridge_drop

    def vin_dc_nom(self) -> float:
        """Bulk DC voltage at the arithmetic mean of the mains range, **V**."""
        return 0.5 * (self.vac_min + self.vac_max) * 2.0 ** 0.5 - self.bridge_drop


# ---------------------------------------------------------------------------
# 2. Flyback main-circuit design
# ---------------------------------------------------------------------------


@dataclass
class FlybackDesign:
    """Result of :func:`opl.flyback.design_flyback` - the main-circuit design.

    All quantities refer to the **worst case** operating point (full load at
    ``vac_min`` for Dmax/Ipk, at ``vac_max`` for Dmin/Vds) unless stated.

    Units
    -----
    n         : dimensionless ``Np/Ns`` (continuous value from the formula;
                the *integer* build value lives in :class:`MagneticDesign`).
    vor       : V   reflected voltage ``n * (Vout + vf_sec)``
    dmax/dmin : dimensionless duty cycles at vac_min / vac_max
    lp        : H   primary magnetising inductance
    lp_bcm    : H   boundary (critical) inductance: above it the design is CCM
    ipk       : A   primary peak current at vac_min, full load
    ip1       : A   primary current at the *start* of the on-time (0 in DCM)
    krip      : dimensionless ripple ratio ``(ipk - ip1) / ipk``
    irms_pri  : A   RMS primary switch current over a whole switching period
    irms_sec  : A   RMS secondary winding current over a whole switching period
    is_pk     : A   secondary peak current right after the switch turns off
    is_avg    : A   average secondary current = ``0.5*(is_pk*(1-krip) + is_pk)*(1-D)``
    ton/tdis  : s   on-time and (for DCM) secondary discharge time
    """

    spec: DesignSpec
    mode: str
    n: float
    vor: float
    dmax: float
    dmin: float
    lp: float
    lp_bcm: float
    ipk: float
    ip1: float
    krip: float
    irms_pri: float
    irms_sec: float
    is_pk: float
    is_avg: float
    ton: float
    tdis: float
    vin_dc_min: float
    vin_dc_max: float
    dmax_limit: float = 0.50
    warnings: List[str] = field(default_factory=list)

    @property
    def dmax_ok(self) -> bool:
        """True when ``dmax <= dmax_limit`` (the hard duty-cycle check)."""
        return self.dmax <= self.dmax_limit

    @property
    def vout_ref(self) -> float:
        """Secondary voltage during off-time ``Vout + vf_sec``, **V**."""
        return self.spec.vout_ref

    @property
    def pin(self) -> float:
        """Assumed input power, **W**."""
        return self.spec.pin

    @property
    def iin_avg(self) -> float:
        """Average bulk-capacitor current at ``vac_min``, **A** = Pin / Vin_dc_min."""
        return self.pin / self.vin_dc_min


# ---------------------------------------------------------------------------
# 3. Magnetics
# ---------------------------------------------------------------------------


@dataclass
class CoreSpec:
    """One entry of the built-in core table.

    Units
    -----
    name     : vendor-style core code, e.g. ``"EE25"`` (E/EE family).
    ae_cm2   : cm^2  effective magnetic cross-section Ae
    aw_cm2   : cm^2  bobbin winding window area Aw (usable copper window)
    le_cm    : cm    effective magnetic path length le
    ve_cm3   : cm^3  effective core volume Ve
    material : ferrite grade label used for the Steinmetz coefficients
    al_ungapped_nh : nH/N^2  ungapped inductance factor (reference value)
    mlt_cm   : cm    mean length per turn of the matching bobbin (reference value,
                     roughly +/- 15 %; it only feeds the copper-resistance estimate)
    """

    name: str
    ae_cm2: float
    aw_cm2: float
    le_cm: float
    ve_cm3: float
    mlt_cm: float = 0.0
    material: str = "3C90-class MnZn"
    al_ungapped_nh: float = 0.0

    @property
    def ap_cm4(self) -> float:
        """Area product ``Ae * Aw`` in **cm^4**."""
        return self.ae_cm2 * self.aw_cm2


@dataclass
class WireSpec:
    """Winding wire choice for one winding.

    Units
    -----
    strands   : count of parallel bare strands (integer >= 1)
    awg       : nearest AWG label for the strand
    d_bare_mm : mm   bare copper diameter of one strand
    d_out_mm  : mm   outer diameter including enamel (used for the fill factor)
    area_mm2  : mm^2 **total** copper area (strands * one strand)
    r_dc_ohm  : ohm   DC resistance of the whole winding at ``temp_c``
    r_ac_ohm  : ohm   AC resistance estimate at fsw (skin effect only)
    """

    strands: int
    awg: str
    d_bare_mm: float
    d_out_mm: float
    area_mm2: float
    turns: int
    r_dc_ohm: float
    r_ac_ohm: float
    temp_c: float = 100.0


@dataclass
class MagneticDesign:
    """Result of :func:`opl.magnetics.design_magnetics`.

    Units
    -----
    ap_required : cm^4  area product required by the AP method
    ap_margin   : dimensionless ``core.ap_cm4 / ap_required`` (>= 1 is good)
    np, ns      : turns (integers)
    n_actual    : dimensionless ``np / ns``
    gap_mm      : mm    total air gap in the centre leg (both halves if shimmed)
    bmax        : T     peak flux density at vac_min, full load
    delta_b     : T     peak-to-peak AC flux swing (what drives core loss)
    bmax_target : T     design target for Bmax
    j_pri/j_sec : A/mm^2 current density in each winding
    delta_mm    : mm    skin depth at fsw for copper at ``temp_c``
    ku_actual   : dimensionless copper fill factor of the bobbin window
    """

    core: CoreSpec
    ap_required: float
    ap_margin: float
    np: int
    ns: int
    n_actual: float
    gap_mm: float
    bmax: float
    delta_b: float
    bmax_target: float
    j_pri: float
    j_sec: float
    delta_mm: float
    ku_actual: float
    wire_pri: WireSpec
    wire_sec: WireSpec
    vor_actual: float
    dmax_actual: float
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 4. Component stress / derating
# ---------------------------------------------------------------------------


@dataclass
class DeratingRule:
    """One configurable derating rule (explicit table entry).

    ``quantity`` is matched against the ``StressItem.name`` exactly.
    ``limit`` is the maximum allowed ``actual / rated`` ratio (0.8 = use at most
    80 % of the rating).  ``ref`` documents where the rule comes from.
    """

    quantity: str
    limit: float
    ref: str = "company derating guideline (configurable)"


DEFAULT_DERATING_RULES: Tuple[DeratingRule, ...] = (
    DeratingRule("mosfet_vds", 0.80, "MOSFET Vds <= 80 % of Vds_rated"),
    DeratingRule("mosfet_id_pk", 0.80, "MOSFET pulsed Id <= 80 % of Id_pulse_rated"),
    DeratingRule("mosfet_id_rms", 0.70, "MOSFET continuous Id(rms) <= 70 % of Id_rated"),
    DeratingRule("mosfet_power", 0.70, "MOSFET dissipation <= 70 % of rated at case temp"),
    DeratingRule("diode_vr", 0.80, "rectifier reverse voltage <= 80 % of Vr_rated"),
    DeratingRule("diode_if_avg", 0.75, "rectifier average current <= 75 % of If_avg_rated"),
    DeratingRule("diode_power", 0.70, "rectifier dissipation <= 70 % of rated"),
    DeratingRule("cap_voltage", 0.80, "capacitor DC voltage <= 80 % of V_rated"),
    DeratingRule("cap_ripple", 0.80, "capacitor ripple current <= 80 % of I_ripple_rated"),
    DeratingRule("cap_temp", 0.90, "capacitor core temp <= 90 % of T_max in degC scale"),
)


@dataclass
class StressItem:
    """One checked quantity: actual vs rated, with the derating verdict.

    Units are carried in ``unit``; ``ratio = actual / rated`` (dimensionless).
    ``margin_pct = (limit - ratio) / limit * 100`` so a positive margin means
    "passes with that much headroom relative to the allowed ratio".
    """

    name: str
    actual: float
    rated: float
    unit: str
    limit: float
    ratio: float
    margin_pct: float
    passed: bool
    note: str = ""


@dataclass
class StressReport:
    """Result of :func:`opl.stress.evaluate_stress`."""

    items: List[StressItem] = field(default_factory=list)
    details: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def failed(self) -> List[StressItem]:
        """Items whose derating ratio exceeds the configured limit."""
        return [it for it in self.items if not it.passed]

    @property
    def passed(self) -> bool:
        """True when every item passes its derating rule."""
        return not self.failed


@dataclass
class Components:
    """Component choices used by the stress / loss / loop calculations.

    Units
    -----
    mosfet_vds_rated   : V   drain-source voltage rating at 25 C
    mosfet_id_rated    : A   continuous drain current rating
    mosfet_id_pulse     : A   pulsed drain current rating
    mosfet_rds_on      : ohm Rds(on) at 25 C, 10 V gate
    mosfet_qg          : C   total gate charge at the drive voltage
    mosfet_coss        : F   output capacitance (for the Coss loss term)
    mosfet_tr/tf       : s   current/voltage overlap times (datasheet-ish)
    mosfet_vgs         : V   gate drive voltage
    mosfet_rth_jc      : K/W junction-to-case thermal resistance
    mosfet_power_rated : W   dissipation this part may burn in *this* thermal
                             design (comes from your own thermal budget)
    rectifier_kind     : "diode" or "sync"
    diode_vr_rated     : V   reverse voltage rating
    diode_if_rated     : A   average forward current rating
    diode_vf           : V   forward drop at the operating point
    diode_rs           : ohm series resistance of the diode
    diode_power_rated  : W   allowed dissipation for the rectifier package
    sr_rds_on          : ohm synchronous-rectifier Rds(on) at 25 C
    sr_vds_rated       : V   SR voltage rating
    cin_cap_f          : F   bulk input capacitance
    cin_v_rated        : V   bulk cap voltage rating
    cin_ripple_rated   : A   rated ripple current at 100 kHz / 105 C
    cin_esr            : ohm bulk cap ESR
    cout_cap_f         : F   total output capacitance (all caps in parallel)
    cout_v_rated       : V   output cap voltage rating
    cout_ripple_rated  : A   rated ripple current per output cap (100 kHz)
    cout_esr          : ohm   total output ESR
    cout_n             : number of parallel output capacitors
    cout_life_h        : h   rated life at ``cout_life_temp_c``
    cout_life_temp_c   : degC rated-endurance temperature
    cout_rth_c_per_w   : K/W thermal resistance cap-to-ambient
    clamp_c_f          : F   RCD clamp capacitor
    clamp_r_ohm        : ohm RCD clamp resistor
    leakage_ratio      : dimensionless Llk / Lp of the transformer
    ctrl_vramp         : V   PWM modulator ramp amplitude (voltage mode)
    opto_ctr           : dimensionless current transfer ratio of the optocoupler
    opto_r_led         : ohm series resistor in the opto LED path
    opto_r_pullup      : ohm pull-up resistor at the opto transistor
    opto_c_pole        : F   capacitance that sets the opto pole
    ambient_c          : degC ambient inside the enclosure
    """

    mosfet_vds_rated: float = 650.0
    mosfet_id_rated: float = 6.0
    mosfet_id_pulse: float = 25.0
    mosfet_rds_on: float = 1.20
    mosfet_qg: float = 12.0e-9
    mosfet_coss: float = 60.0e-12
    mosfet_tr: float = 30.0e-9
    mosfet_tf: float = 25.0e-9
    mosfet_vgs: float = 12.0
    mosfet_rth_jc: float = 25.0
    mosfet_power_rated: float = 1.50
    rectifier_kind: str = "diode"
    diode_vr_rated: float = 100.0
    diode_if_rated: float = 10.0
    diode_vf: float = 0.45
    diode_rs: float = 0.02
    diode_power_rated: float = 1.00
    sr_vds_rated: float = 60.0
    sr_rds_on: float = 0.012
    cin_cap_f: float = 33.0e-6
    cin_v_rated: float = 450.0
    cin_ripple_rated: float = 0.60
    cin_esr: float = 1.5
    cout_cap_f: float = 470.0e-6
    cout_v_rated: float = 10.0
    cout_ripple_rated: float = 1.20
    cout_esr: float = 0.040
    cout_n: int = 3
    cout_life_h: float = 5000.0
    cout_life_temp_c: float = 105.0
    cout_rth_c_per_w: float = 35.0
    clamp_c_f: float = 2.2e-9
    clamp_r_ohm: float = 100.0e3
    leakage_ratio: float = 0.010
    ctrl_vramp: float = 2.5
    opto_ctr: float = 1.0
    opto_r_led: float = 1000.0
    opto_r_pullup: float = 10.0e3
    opto_c_pole: float = 1.0e-9
    ambient_c: float = 45.0


# ---------------------------------------------------------------------------
# 5. Loop compensation
# ---------------------------------------------------------------------------


@dataclass
class PowerStageModel:
    """Average (small-signal) model of the flyback power stage.

    Control-to-output transfer function, secondary-referred::

        Gvd(s) = g0_dc * (1 + s/w_esr) / [(1 + s/(w0*Q) + (s/w0)^2) * (1 - s/w_rhp)]

    Units: ``g0_dc`` in V per unit duty (dimensionless gain V/V), the corners in
    rad/s (``f_*`` mirrors are in Hz for reporting).
    """

    g0_dc: float
    w0: float
    q: float
    w_rhp: float
    w_esr: float
    mode: str
    l_sec_h: float
    cout_f: float
    r_load_ohm: float
    esr_ohm: float
    notes: List[str] = field(default_factory=list)

    @property
    def f0_hz(self) -> float:
        """Power-stage double pole (or single pole in DCM), **Hz**."""
        return self.w0 / (2.0 * 3.141592653589793)

    @property
    def f_rhp_hz(self) -> float:
        """Right-half-plane zero, **Hz** (``inf`` when not applicable)."""
        return self.w_rhp / (2.0 * 3.141592653589793)

    @property
    def f_esr_hz(self) -> float:
        """Output-capacitor ESR zero, **Hz**."""
        return self.w_esr / (2.0 * 3.141592653589793)


@dataclass
class Compensator:
    """Type-II / Type-III compensator (TL431 + optocoupler form).

    Transfer function (``s`` in rad/s)::

        Type II :  Hc(s) = kc * (1 + s/wz) / [s * (1 + s/wp)]
        Type III:  Hc(s) = kc * (1 + s/wz) * (1 + s/wz2) / [s * (1 + s/wp) * (1 + s/wp2)]

    Units: ``kc`` in 1/s (so that ``Hc`` is dimensionless), corners in rad/s.
    """

    kind: str
    kc: float
    wz: float
    wp: float
    wz2: float = 0.0
    wp2: float = 0.0
    components: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


@dataclass
class LoopPoint:
    """One point of a Bode sweep."""

    f_hz: float
    mag_db: float
    phase_deg: float


@dataclass
class LoopResult:
    """Result of :func:`opl.loop.analyze_loop`.

    Units / meaning
    ---------------
    fc_hz            : Hz   numeric crossover frequency (|T| = 1) from the sweep
    fc_analytic_hz   : Hz   crossover predicted from the asymptotic Bode sketch
    fc_error_pct     : %    ``(fc_numeric - fc_analytic) / fc_numeric * 100``
    phase_margin_deg : deg  ``180 + arg T(j 2 pi fc)`` (integrator convention)
    gain_margin_db   : dB   ``-20 log10|T|`` at the frequency where the phase
                            crosses -180 deg (inf when it never crosses)
    sweep            : list of :class:`LoopPoint` (log-spaced, low -> high freq)
    passed           : dimensionless verdict against ``pm_target`` / ``gm_target``
    """

    fc_hz: float
    fc_analytic_hz: float
    fc_error_pct: float
    phase_margin_deg: float
    gain_margin_db: float
    f_gm_hz: float
    pm_target_deg: float
    gm_target_db: float
    passed: bool
    sweep: List[LoopPoint] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 6. Safety distances
# ---------------------------------------------------------------------------


@dataclass
class SafetyRequirement:
    """Looked-up insulation distance requirement.

    Units: all distances in **mm** (the unit used by the standards tables).

    ``basis`` records the table actually consulted; ``altitude_factor`` is the
    multiplier already applied to the clearance.
    """

    v_working_rms: float
    pollution_degree: int
    material_group: str
    insulation: str
    altitude_m: float
    altitude_factor: float
    clearance_mm: float
    creepage_mm: float
    basis: str
    notes: List[str] = field(default_factory=list)


@dataclass
class SafetyResult:
    """Result of :func:`opl.safety.check_safety`.

    ``design_clearance_mm`` / ``design_creepage_mm`` are the measured (or
    intended) layout numbers; margins are in mm, positive = passes.
    """

    requirement: SafetyRequirement
    design_clearance_mm: float
    design_creepage_mm: float
    clearance_margin_mm: float
    creepage_margin_mm: float
    clearance_pass: bool
    creepage_pass: bool
    leakage_current_ma: float = 0.0
    leakage_limit_ma: float = 0.0
    leakage_pass: bool = True
    conclusion: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True when clearance, creepage and leakage current all pass."""
        return self.clearance_pass and self.creepage_pass and self.leakage_pass


# ---------------------------------------------------------------------------
# 7. EMC input filter
# ---------------------------------------------------------------------------


@dataclass
class EmiFilter:
    """Two-stage-ish mains EMI filter element values.

    Units
    -----
    cx_f   : F  total differential-mode X capacitance (line-to-line)
    cy_f   : F  **per line** Y capacitance (line-to-earth); the physical
                capacitor count is 2 (L-E and N-E)
    lcm_h  : H  common-mode inductance **per winding**
    ldm_h  : H  differential-mode inductance (CM-choke leakage + optional
                series DM inductor)
    rs_ohm : ohm source impedance of the 50 ohm CISPR 17 measurement system
    rl_ohm : ohm load impedance of the measurement system
    """

    cx_f: float = 0.22e-6
    cy_f: float = 1.0e-9
    lcm_h: float = 10.0e-3
    ldm_h: float = 20.0e-6
    rs_ohm: float = 50.0
    rl_ohm: float = 50.0


@dataclass
class EmiResult:
    """Result of :func:`opl.emi.emi_report`.

    ``curve`` is a list of ``(f_hz, il_dm_db, il_cm_db)`` tuples.
    ``f_pass_dm_hz`` / ``f_pass_cm_hz`` are the lowest frequencies above which
    the insertion loss stays >= ``target_db`` up to ``f_stop_hz``
    (``float('inf')`` when never reached).
    """

    curve: List[Tuple[float, float, float]] = field(default_factory=list)
    target_db: float = 40.0
    f_start_hz: float = 150.0e3
    f_stop_hz: float = 30.0e6
    f_pass_dm_hz: float = float("inf")
    f_pass_cm_hz: float = float("inf")
    dm_pass: bool = False
    cm_pass: bool = False
    leakage_current_ma: float = 0.0
    leakage_limit_ma: float = 0.25
    leakage_pass: bool = True
    warnings: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True when both DM and CM attenuation targets and leakage limits pass."""
        return self.dm_pass and self.cm_pass and self.leakage_pass


# ---------------------------------------------------------------------------
# 8. Loss / efficiency budget
# ---------------------------------------------------------------------------


@dataclass
class LossItem:
    """One loss term.

    ``value_w`` in W, ``pct`` is the share of the total loss in percent,
    ``formula`` is the one-line formula with the substituted numbers (ASCII).
    """

    name: str
    value_w: float
    pct: float = 0.0
    formula: str = ""


@dataclass
class LossBudget:
    """Result of :func:`opl.budget.loss_budget`.

    ``efficiency`` is the predicted end-to-end efficiency as a fraction;
    ``gap`` is ``eta_target - efficiency`` in *percentage points*.
    ``dominant`` is the name of the largest loss item.
    """

    items: List[LossItem] = field(default_factory=list)
    total_w: float = 0.0
    pout_w: float = 0.0
    pin_w: float = 0.0
    efficiency: float = 0.0
    eta_target: float = 0.0
    gap_pct_points: float = 0.0
    dominant: str = ""
    warnings: List[str] = field(default_factory=list)

    def get(self, name: str) -> float:
        """Loss value in W for ``name`` (0.0 if the item does not exist)."""
        for it in self.items:
            if it.name == name:
                return it.value_w
        return 0.0


# ---------------------------------------------------------------------------
# 9. Pipeline bundle
# ---------------------------------------------------------------------------


@dataclass
class DesignResult:
    """Everything the pipeline computed - the single object the CLI/report use.

    Any member may be ``None`` when the corresponding stage was not requested.
    """

    spec: DesignSpec
    flyback: Optional[FlybackDesign] = None
    magnetics: Optional[MagneticDesign] = None
    components: Optional[Components] = None
    stress: Optional[StressReport] = None
    loop: Optional[LoopResult] = None
    loop_power_stage: Optional[PowerStageModel] = None
    compensator: Optional[Compensator] = None
    safety: Optional[SafetyResult] = None
    emi: Optional[EmiResult] = None
    emi_filter: Optional[EmiFilter] = None
    budget: Optional[LossBudget] = None
    warnings: List[str] = field(default_factory=list)
    stages_run: Sequence[str] = field(default_factory=tuple)
