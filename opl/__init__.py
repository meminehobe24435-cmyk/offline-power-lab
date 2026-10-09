"""offline-power-lab (opl) :: offline AC-DC switch-mode power supply design &
verification toolkit.

WHAT THIS IS
------------
A **design-calculation and verification** tool for mains-input ("offline")
AC-DC flyback switching power supplies - the power train inside wall chargers,
GaN fast chargers, USB adapters, power strips with USB ports, etc.

It turns the steps an engineer normally does from experience into a
**reviewable calculation sheet**:

1. :mod:`opl.flyback`    - flyback main circuit (CCM **and** DCM), Vor, n, Dmax/Dmin,
                           Lp, Ipk, RMS currents, duty-cycle limit check.
2. :mod:`opl.magnetics`  - AP (area-product) core selection from a built-in core
                           table, turns, air gap, Bmax saturation check, skin
                           depth and strand/parallel-wire selection.
3. :mod:`opl.stress`     - component stress and **derating verdicts** (MOSFET,
                           rectifier, capacitors, RCD clamp) as an explicit
                           actual/rated/margin/pass table.
4. :mod:`opl.loop`       - average small-signal model of the power stage plus a
                           Type-II compensator (TL431 + optocoupler form) and a
                           Bode sweep reporting crossover, phase margin and gain
                           margin, with an analytic-vs-numeric crossover check.
5. :mod:`opl.safety`     - clearance / creepage look-up from simplified
                           IEC 60950-1 / GB 4943.1 style tables, with pollution
                           degree, material group, altitude and insulation type.
6. :mod:`opl.emi`        - CM/DM equivalent circuits, insertion loss vs a target
                           attenuation, X/Y capacitor and CM-choke selection, and
                           the earth leakage current caused by the Y capacitors.
7. :mod:`opl.budget`     - item-by-item loss budget (switching, conduction,
                           Steinmetz core loss, copper, rectifier, drive,
                           sampling, clamp) -> predicted efficiency and the
                           dominant loss term.
8. :mod:`opl.report`     - Markdown design report + CSV detail files.
9. :mod:`opl.cli`        - ``python main.py {design,stress,loop,safety,emi,budget,all}``.

WHAT THIS IS **NOT**  (see README "Boundaries" - quoted verbatim there)
----------------------------------------------------------------------
* **Not a circuit simulator.** No SPICE, no time-domain waveforms, no
  switching-cycle resolution, no convergence, no device models.
* **Not a PCB tool.** No parasitic extraction, no layout, no thermal FEM.
* **No hardware was built.** There is no prototype, no bench measurement and no
  scope capture behind any number in this repository. Every number is computed
  from the formulas in the module docstrings and from public data.
* Core tables, safety tables and device parameters are **simplified subsets of
  common grades**; they cannot replace vendor datasheets or the standards text,
  and no safety verdict here can replace a safety agency's judgement.
* The loop model is an **average model**: no sampling effect, no
  high-frequency detail beyond the RHP zero; loop conclusions need bench
  verification.

UNITS
-----
SI everywhere unless the field/parameter name or docstring says otherwise:
V, A, ohm, H, F, Hz, s, W, T, m, K, and **mm** for mechanical/safety
distances (that is the unit the standards tables use).  Efficiency is a
fraction (0.80 = 80 %), never a percentage.  ``n`` is the turns ratio Np/Ns.

ERROR HANDLING
--------------
Invalid inputs raise :class:`opl.OplError` carrying a stable ``code``
(``OPL-E-INPUT``, ``OPL-E-RANGE``, ``OPL-E-TABLE``, ``OPL-E-NOCORE``,
``OPL-E-UNSAT``, ``OPL-E-NODATA``).  Soft guideline violations do **not**
raise: they are appended to the result object's ``warnings`` list.

QUICK START
-----------
>>> from opl import DesignSpec, run_spec, render_markdown
>>> spec = DesignSpec(vac_min=90, vac_max=264, vout=5.0, iout=3.0, fsw=65e3)
>>> res = run_spec(spec)
>>> res.flyback.dmax > 0.3 and res.flyback.dmax <= 0.5
True

PUBLIC API REFERENCE  (signatures, units, return values, error codes)
=====================================================================
Data model: see :mod:`opl.model` (every field is documented with its unit).
Below, "[-]" marks a dimensionless argument.

opl.flyback
-----------
``design_flyback(spec: DesignSpec, vor_target: float|None = None) -> FlybackDesign``
    ``spec`` : :class:`DesignSpec`.  ``vor_target`` : V, optional forced
    reflected voltage (``None`` = derive it from ``spec.dmax_target``).
    Returns the main-circuit design (Dmax/Dmin, n, Lp, Ipk, RMS currents).
    Raises ``OPL-E-INPUT`` / ``OPL-E-RANGE`` (e.g. resulting Vor forces
    Dmax > ``dmax_limit``, or a DCM request that cannot complete its
    discharge inside the off-time).

``duty_from_vor(vor_V, vin_dc_V) -> float`` [-] CCM duty ``Vor/(Vin+Vor)``.
``duty_ccm(vin_dc_V, vor_V) -> float`` [-] same, named for readability.
``duty_dcm(pin_W, lp_H, fsw_Hz, vin_dc_V) -> float`` [-]
    ``sqrt(2*Pin*Lp*fsw)/Vin``; raises ``OPL-E-RANGE`` when >= 1.
``peak_current_ccm(pin_W, vin_dc_V, dmax_[-], ripple_k_[-]) -> float`` [A].
``peak_current_dcm(pin_W, vin_dc_V, d_[-]) -> float`` [A].
``boundary_inductance(pin_W, vin_dc_V, d_[-], fsw_Hz) -> float`` [H]
    ``(Vin*D)^2 / (2*Pin*fsw)`` - above it the design is CCM.
``trapezoid_rms(i_start_A, i_end_A, duty_[-]) -> float`` [A]
    ``sqrt(duty*(i1^2+i1*i2+i2^2)/3)``.
``primary_rms(ipk_A, krip_[-], duty_[-]) -> float`` [A].
``secondary_rms(ipk_A, krip_[-], duty_[-], n_[-]) -> float`` [A]
    ``n * trapezoid_rms`` (ampere-turns equality ``Ns*Is = Np*Ip``).
``discharge_time_dcm(ipk_A, lp_H, n_[-], vout_ref_V) -> float`` [s]
    ``ipk*Lp/(n*Vout_ref)``.
``verify_power_balance(design) -> float`` [-]
    Self-check: power reconstructed from the computed currents divided by
    ``spec.pin``; a value ~1.0 proves the current formulas are self-consistent.

opl.magnetics
-------------
``CORE_TABLE`` : tuple of :class:`CoreSpec` (reference subset of common E/EE cores).
``MATERIALS`` : dict material name -> Steinmetz ``(k, alpha, beta)``.
``find_core(name) -> CoreSpec`` (``OPL-E-TABLE`` if unknown).
``list_cores() -> list[str]``.
``required_ap(lp_H, ipk_A, irms_A, bmax_T, ku_[-], j_A_per_mm2) -> float`` [cm^4]
    ``L*Ipk*Irms/(Ku*Bmax*J) * 1e4`` (J in A/cm^2 internally).
``select_core(ap_cm4, min_ae_cm2=0.0) -> CoreSpec`` (``OPL-E-NOCORE``).
``skin_depth_mm(fsw_Hz, temp_c=100.0) -> float`` [mm] copper
    ``66.1/sqrt(f)`` at 20 C, ``75/sqrt(f)`` at 100 C.
``nearest_awg(d_mm) -> tuple[str, float, float]`` (label, bare mm, outer mm).
``pick_wire(irms_A, j_A_per_mm2, fsw_Hz, temp_c=100.0, max_strands=12) -> WireSpec``
    Splits the required copper area into parallel strands so that each strand
    diameter <= 2*skin depth.
``gap_mm_for_lp(lp_H, np_[-], ae_cm2, le_cm, ur_[-]=2000) -> float`` [mm]
    ``mu0*Np^2*Ae/Lp - le/ur``, clamped at 0.
``bmax_of(lp_H, ipk_A, np_[-], ae_cm2) -> float`` [T].
``design_magnetics(design, bmax_target_T=0.28, ku_[-]=0.35, j_A_per_mm2=400.0,
                   core_name=None, temp_c=100.0) -> MagneticDesign``
    Raises ``OPL-E-NOCORE`` when the AP requirement cannot be met, and appends
    a warning when the integer turns ratio pushes Dmax above ``dmax_limit``.

opl.stress
----------
``derating_ratio(actual, rated) -> float`` [-].
``mosfet_stress(design, comp: Components, temp_c=100.0) -> dict[str, float]``
    keys: ``vds_ideal``, ``vds_spike``, ``vds_total``, ``id_pk``, ``id_rms``,
    ``rds_on_hot`` [ohm], ``p_cond``, ``p_sw_on``, ``p_sw_off``, ``p_coss``,
    ``p_gate``, ``p_total`` [W].
``rectifier_stress(design, comp, temp_c=100.0) -> dict[str, float]``
    keys: ``vr`` [V], ``if_pk``, ``if_avg``, ``if_rms`` [A], ``p_total`` [W].
``capacitor_stress(design, comp, temp_c=100.0) -> dict[str, float]``
    keys: ``cin_vdc`` [V], ``cin_irms`` [A], ``cin_ripple`` [-] ,
    ``cout_vdc``, ``cout_irms`` [A], ``cout_ripple`` [-], ``cout_esr_loss`` [W],
    ``cout_core_c``, ``cout_life_h`` [h].
``clamp_stress(design, comp) -> dict[str, float]``
    keys: ``llk`` [H], ``v_spike`` [V], ``v_clamp`` [V], ``p_clamp`` [W].
``evaluate_stress(design, comp, mag=None, rules=DEFAULT_DERATING_RULES,
                  temp_c=100.0) -> StressReport``
    Builds the actual/rated/ratio/margin/pass table.  Never raises for a
    failing derating check - failures are reported as ``passed=False`` items.

opl.loop
--------
``power_stage_model(design, comp, cout_f=None, esr_ohm=None) -> PowerStageModel``
    Average control-to-output model (CCM: double pole + ESR zero + RHP zero;
    DCM: single pole + ESR zero).
``power_stage_response(power, f_Hz) -> complex``.
``compensator_response(comp_net: Compensator, f_Hz) -> complex``.
``loop_response(power, comp_net, comp, f_Hz) -> complex``
    ``Gvd * (1/ctrl_vramp) * opto_gain/(1+s/wp_opto) * Hc``.
``design_compensator(power, comp, design=None, fc_target_Hz=None,
                     pm_target_deg=45.0, kind="II") -> Compensator``
    Places the zero(s)/pole(s) and sets the gain for the target crossover;
    raises ``OPL-E-UNSAT`` when no crossover inside the allowed window meets
    the phase-margin target.
``type2_components(design, power, comp, fc_Hz) -> dict[str, float]``
    R1/R2 divider [ohm], C_zero/C_pole [F], R_LED [ohm] for the TL431+opto form.
``sweep_response(func, f_start_Hz, f_stop_Hz, n_points) -> list[LoopPoint]``.
``analytic_crossover(power, comp_net, comp, f_start_Hz=10.0,
                     f_stop_Hz=1e6) -> float`` [Hz] asymptotic Bode estimate.
``numeric_crossover(power, comp_net, comp, f_start_Hz=10.0,
                    f_stop_Hz=1e6, n_points=4000) -> float`` [Hz] root find.
``analyze_loop(power, comp_net, comp, design=None, f_start_Hz=10.0,
               f_stop_Hz=1e6, n_points=400, pm_target_deg=45.0,
               gm_target_db=10.0) -> LoopResult``
    Reports crossover, phase margin, gain margin and the analytic-vs-numeric
    crossover error in percent.

opl.safety
----------
``CLEARANCE_TABLE`` / ``CREEPAGE_TABLE`` : tuple of ``(v_band, values...)``.
``ALTITUDE_FACTORS`` : tuple of ``(altitude_m, multiplier)``.
``STANDARD_LEAKAGE_LIMITS_MA`` : dict equipment class -> mA.
``lookup_clearance(v_working_rms_V, pollution_degree=2, insulation="basic",
                   altitude_m=0.0) -> tuple[float, float]`` -> (clearance mm,
    altitude multiplier applied).  ``OPL-E-TABLE`` above 1000 V or for an
    unknown pollution degree.
``lookup_creepage(v_working_rms_V, pollution_degree=2,
                  material_group="IIIa", insulation="basic") -> float`` [mm].
``leakage_current_ma(vac_V, f_line_Hz, cy_total_F) -> float`` [mA]
    ``2*pi*f*C*V`` (sinusoidal estimate through the Y capacitors).
``check_safety(design, design_clearance_mm, design_creepage_mm,
               v_working_rms_V=None, pollution_degree=2, material_group="IIIa",
               insulation="reinforced", altitude_m=2000.0, cy_f=1.0e-9,
               equipment_class="II") -> SafetyResult``
    Compares the look-up requirement with the layout numbers and the earth
    leakage current with the class limit.

opl.emi
-------
``insertion_loss_lc(f_Hz, l_H, c_F, rs_ohm=50.0, rl_ohm=50.0) -> float`` [dB]
    CISPR 17 style 50 ohm / 50 ohm insertion loss of a series-L shunt-C filter.
``insertion_loss_dm(f_Hz, filt: EmiFilter) -> float`` [dB].
``insertion_loss_cm(f_Hz, filt: EmiFilter) -> float`` [dB]
    Uses ``2*L_per_winding`` in the CM loop and one ``Cy`` as the shunt path
    (conservative convention, documented in the module).
``emi_report(filt, target_db=40.0, f_start_Hz=150e3, f_stop_Hz=30e6,
             n_points=200, vac_V=264.0, f_line_Hz=50.0, cy_count=2,
             equipment_class="II") -> EmiResult``
    Returns the DM/CM insertion-loss curves, the first frequency above which
    the target is met, and the Y-capacitor leakage current verdict.

opl.budget
----------
``steinmetz_pv(f_kHz, b_tesla, material="3C90-class") -> float`` [mW/cm^3]
    ``k * f^alpha * B^beta``; raise ``OPL-E-TABLE`` for an unknown material.
``core_loss_w(design, mag, material=None) -> float`` [W] (uses ``delta_b``).
``copper_loss_w(design, mag, temp_c=100.0) -> float`` [W]
    DC + skin-effect AC term for both windings.
``switch_losses(design, comp, temp_c=100.0) -> dict[str, float]`` [W].
``rectifier_loss_w(design, comp, temp_c=100.0) -> float`` [W].
``loss_budget(design, comp, mag, temp_c=100.0) -> LossBudget``
    Itemised losses, total, predicted efficiency, gap to ``eta_target`` and the
    dominant loss term.

opl.report
----------
``render_markdown(result: DesignResult, title=None) -> str``.
``write_outputs(result, out_dir, prefix="opl", title=None) -> dict[str, str]``
    Writes ``<prefix>_report.md`` plus ``<prefix>_losses.csv``,
    ``<prefix>_stress.csv``, ``<prefix>_loop.csv``, ``<prefix>_emi.csv`` and
    returns a mapping name -> absolute path.  All files are written with
    ``encoding="utf-8"``.
``write_csv(path, header, rows) -> str``.

opl.pipeline / opl.cli
----------------------
``default_components() -> Components``.
``EXAMPLE_SPECS`` : dict of named :class:`DesignSpec` examples.
``run_spec(spec, comp=None, stages=("design","stress","loop","safety","emi",
            "budget"), **kwargs) -> DesignResult``.
``main(argv=None) -> int`` - CLI entry point, returns a process exit code
    (0 = all requested checks pass, 1 = at least one check failed, 2 = usage
    error, 3 = :class:`OplError`).
"""

from __future__ import annotations

__version__ = "0.3.0"
__all__ = [
    "__version__",
    # errors
    "OplError",
    "OPL_E_INPUT",
    "OPL_E_RANGE",
    "OPL_E_TABLE",
    "OPL_E_NOCORE",
    "OPL_E_UNSAT",
    "OPL_E_NODATA",
    "ERROR_CODES",
    # model
    "DesignSpec",
    "FlybackDesign",
    "CoreSpec",
    "WireSpec",
    "MagneticDesign",
    "DeratingRule",
    "DEFAULT_DERATING_RULES",
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
    # flyback
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
    # magnetics
    "CORE_TABLE",
    "MATERIALS",
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
    # stress
    "derating_ratio",
    "rds_on_hot",
    "cap_life_hours",
    "mosfet_stress",
    "rectifier_stress",
    "capacitor_stress",
    "clamp_stress",
    "evaluate_stress",
    # loop
    "power_stage_model",
    "power_stage_response",
    "compensator_response",
    "loop_response",
    "design_compensator",
    "type2_components",
    "sweep_response",
    "analytic_crossover",
    "numeric_crossover",
    "analyze_loop",
    # safety
    "CLEARANCE_TABLE",
    "CREEPAGE_TABLE",
    "ALTITUDE_FACTORS",
    "lookup_clearance",
    "lookup_creepage",
    "leakage_current_ma",
    "STANDARD_LEAKAGE_LIMITS_MA",
    "check_safety",
    # emi
    "insertion_loss_lc",
    "insertion_loss_dm",
    "insertion_loss_cm",
    "emi_report",
    # budget
    "steinmetz_pv",
    "core_loss_w",
    "copper_loss_w",
    "switch_losses",
    "rectifier_loss_w",
    "loss_budget",
    # report / pipeline / cli
    "render_markdown",
    "write_outputs",
    "write_csv",
    "default_components",
    "EXAMPLE_SPECS",
    "run_spec",
    "main",
]

from .errors import (
    ERROR_CODES,
    OPL_E_INPUT,
    OPL_E_NOCORE,
    OPL_E_NODATA,
    OPL_E_RANGE,
    OPL_E_TABLE,
    OPL_E_UNSAT,
    OplError,
)
from .model import (
    Compensator,
    Components,
    CoreSpec,
    DEFAULT_DERATING_RULES,
    DeratingRule,
    DesignResult,
    DesignSpec,
    EmiFilter,
    EmiResult,
    FlybackDesign,
    LoopPoint,
    LoopResult,
    LossBudget,
    LossItem,
    MagneticDesign,
    PowerStageModel,
    SafetyRequirement,
    SafetyResult,
    StressItem,
    StressReport,
    WireSpec,
)
from .flyback import (
    boundary_inductance,
    design_flyback,
    discharge_time_dcm,
    duty_ccm,
    duty_dcm,
    duty_from_vor,
    peak_current_ccm,
    peak_current_dcm,
    primary_rms,
    secondary_rms,
    trapezoid_rms,
    verify_power_balance,
)
from .magnetics import (
    CORE_TABLE,
    MATERIALS,
    bmax_of,
    design_magnetics,
    find_core,
    gap_mm_for_lp,
    list_cores,
    nearest_awg,
    pick_wire,
    required_ap,
    select_core,
    skin_depth_mm,
)
from .stress import (
    cap_life_hours,
    capacitor_stress,
    clamp_stress,
    derating_ratio,
    evaluate_stress,
    mosfet_stress,
    rds_on_hot,
    rectifier_stress,
)
from .loop import (
    analytic_crossover,
    analyze_loop,
    compensator_response,
    design_compensator,
    loop_response,
    numeric_crossover,
    power_stage_model,
    power_stage_response,
    sweep_response,
    type2_components,
)
from .safety import (
    ALTITUDE_FACTORS,
    CLEARANCE_TABLE,
    CREEPAGE_TABLE,
    STANDARD_LEAKAGE_LIMITS_MA,
    check_safety,
    leakage_current_ma,
    lookup_clearance,
    lookup_creepage,
)
from .emi import (
    emi_report,
    insertion_loss_cm,
    insertion_loss_dm,
    insertion_loss_lc,
)
from .budget import (
    core_loss_w,
    copper_loss_w,
    loss_budget,
    rectifier_loss_w,
    steinmetz_pv,
    switch_losses,
)
from .report import render_markdown, write_csv, write_outputs
from .pipeline import EXAMPLE_SPECS, default_components, run_spec
from .cli import main
