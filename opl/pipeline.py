"""offline-power-lab :: pipeline - run the stages in the right order.

Stage order and data flow::

    DesignSpec
      -> design_flyback()                  flyback main circuit (CCM/DCM)
      -> design_magnetics()                core, turns, gap, Bmax, wire
      -> evaluate_stress()                 stress + derating verdicts
      -> power_stage_model()               average small-signal model
      -> design_compensator() + analyze_loop()
      -> check_safety()                    clearance / creepage / leakage
      -> emi_report()                      CM & DM insertion loss + leakage
      -> loss_budget()                     losses, predicted efficiency

Each stage is independent enough that a failure in a later stage does not
invalidate the earlier ones; ``run_spec(stages=...)`` runs only what you ask for.

EXAMPLE_SPECS holds the specifications used in the README and by the CLI demo.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from .budget import loss_budget
from .emi import emi_report
from .errors import OPL_E_INPUT, OplError, require
from .flyback import design_flyback
from .loop import analyze_loop, design_compensator, power_stage_model
from .magnetics import design_magnetics
from .model import (
    Compensator,
    Components,
    DesignResult,
    DesignSpec,
    EmiFilter,
    EmiResult,
    FlybackDesign,
    LoopResult,
    LossBudget,
    MagneticDesign,
    PowerStageModel,
    SafetyResult,
    StressReport,
)
from .safety import check_safety
from .stress import evaluate_stress

__all__ = ["EXAMPLE_SPECS", "default_components", "run_spec", "ALL_STAGES"]

ALL_STAGES = ("design", "stress", "loop", "safety", "emi", "budget")

#: The example designs quoted in the README.  ``default`` is the universal-input
#: 5 V / 3 A adapter; ``gan_20v`` is a 65 W USB-PD style flyback; ``dcm_5v`` runs
#: the same adapter deliberately in DCM.
EXAMPLE_SPECS: Dict[str, DesignSpec] = {
    "default": DesignSpec(
        vac_min=90.0, vac_max=264.0, vout=5.0, iout=3.0, fsw=65.0e3,
        eta_target=0.80, mode="CCM", ripple_k=0.40,
    ),
    "dcm_5v": DesignSpec(
        vac_min=90.0, vac_max=264.0, vout=5.0, iout=3.0, fsw=65.0e3,
        eta_target=0.80, mode="DCM", dcm_k=0.60,
    ),
    "gan_20v": DesignSpec(
        vac_min=90.0, vac_max=264.0, vout=20.0, iout=3.25, fsw=100.0e3,
        eta_target=0.90, vf_sec=0.10, mode="CCM", ripple_k=0.50,
    ),
}


def default_components() -> Components:
    """The screening part set used by the CLI and the README tables.

    Concentrated on a 5 V / 3 A class design: 650 V MOSFET, Schottky rectifier,
    450 V bulk capacitor, three 470 uF output capacitors.  These are plausible
    *screening* values, **not** a bill of materials - replace them with your own
    datasheet numbers (see :class:`opl.model.Components` for every unit).
    """
    return Components()


def run_spec(
    spec: DesignSpec,
    comp: Optional[Components] = None,
    stages: Sequence[str] = ALL_STAGES,
    bmax_target: float = 0.28,
    j_a_per_mm2: float = 4.0,
    core_name: Optional[str] = None,
    temp_c: float = 100.0,
    material: Optional[str] = None,
    fc_target_hz: Optional[float] = None,
    pm_target_deg: float = 45.0,
    gm_target_db: float = 10.0,
    design_clearance_mm: float = 6.0,
    design_creepage_mm: float = 6.5,
    insulation: str = "reinforced",
    material_group: str = "IIIa",
    pollution_degree: int = 2,
    altitude_m: float = 2000.0,
    equipment_class: str = "II",
    emi_filter: Optional[EmiFilter] = None,
    emi_target_db: float = 40.0,
) -> DesignResult:
    """Run the requested stages for ``spec`` and return a :class:`DesignResult`.

    Keyword arguments map 1:1 onto the stage functions; see
    :mod:`opl.flyback`, :mod:`opl.magnetics`, :mod:`opl.stress`,
    :mod:`opl.loop`, :mod:`opl.safety`, :mod:`opl.emi` and :mod:`opl.budget`
    for their units.  Unknown stage names raise ``OplError(OPL-E-INPUT)``.
    """
    require(isinstance(spec, DesignSpec), OPL_E_INPUT, "spec must be a DesignSpec")
    comp = comp if comp is not None else default_components()
    wanted: List[str] = []
    for stage in stages:
        name = str(stage).strip().lower()
        if name == "all":
            for extra in ALL_STAGES:
                if extra not in wanted:
                    wanted.append(extra)
            continue
        if name not in ALL_STAGES:
            raise OplError(
                OPL_E_INPUT,
                "unknown stage {0!r}; valid stages are {1} (or 'all')".format(stage, list(ALL_STAGES)),
            )
        if name not in wanted:
            wanted.append(name)

    result = DesignResult(spec=spec, components=comp, stages_run=tuple(wanted))
    warnings: List[str] = []

    design: Optional[FlybackDesign] = None
    if any(s in wanted for s in ("design", "stress", "loop", "budget")):
        design = design_flyback(spec)
        result.flyback = design
        warnings.extend(design.warnings)

    mag: Optional[MagneticDesign] = None
    if any(s in wanted for s in ("stress", "budget")):
        mag = design_magnetics(
            design, bmax_target=bmax_target, j_a_per_mm2=j_a_per_mm2, core_name=core_name,
            temp_c=temp_c,
        )
        result.magnetics = mag
        warnings.extend(mag.warnings)

    if "stress" in wanted:
        stress: StressReport = evaluate_stress(design, comp, mag, temp_c=temp_c)
        result.stress = stress
        warnings.extend(stress.warnings)

    if "loop" in wanted:
        power: PowerStageModel = power_stage_model(design, comp, n_override=None)
        result.loop_power_stage = power
        net: Compensator = design_compensator(
            power, comp, design=design, fc_target_hz=fc_target_hz, pm_target_deg=pm_target_deg
        )
        result.compensator = net
        loop_res: LoopResult = analyze_loop(
            power, net, comp, design=design, pm_target_deg=pm_target_deg, gm_target_db=gm_target_db
        )
        result.loop = loop_res
        warnings.extend(loop_res.warnings)

    if "safety" in wanted:
        safety: SafetyResult = check_safety(
            design,
            design_clearance_mm=design_clearance_mm,
            design_creepage_mm=design_creepage_mm,
            pollution_degree=pollution_degree,
            material_group=material_group,
            insulation=insulation,
            altitude_m=altitude_m,
            equipment_class=equipment_class,
        )
        result.safety = safety
        warnings.extend(safety.warnings)

    if "emi" in wanted:
        filt = emi_filter if emi_filter is not None else EmiFilter()
        result.emi_filter = filt
        emi: EmiResult = emi_report(
            filt, target_db=emi_target_db, equipment_class=equipment_class, design=design
        )
        result.emi = emi
        warnings.extend(emi.warnings)

    if "budget" in wanted:
        budget: LossBudget = loss_budget(design, comp, mag, temp_c=temp_c, material=material)
        result.budget = budget
        warnings.extend(budget.warnings)

    result.warnings = warnings
    return result
