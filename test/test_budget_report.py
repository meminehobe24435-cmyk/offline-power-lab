"""Checks for opl.budget, opl.report, opl.pipeline and opl.cli."""

from __future__ import annotations

import csv
import math
import os
import shutil
import sys
import tempfile

from opl import (
    OPL_E_INPUT,
    OPL_E_NODATA,
    OPL_E_TABLE,
    Components,
    DesignSpec,
    EmiFilter,
    bridge_loss_w,
    core_loss_w,
    copper_loss_w,
    design_flyback,
    design_magnetics,
    feedback_loss_w,
    loss_budget,
    rectifier_loss_w,
    render_markdown,
    run_spec,
    steinmetz_pv,
    switch_losses,
    write_csv,
    write_outputs,
)
from opl.cli import build_parser, spec_from_args, verdict_of
from opl.pipeline import ALL_STAGES, EXAMPLE_SPECS, default_components


def spec(**kw):
    base = dict(vac_min=90.0, vac_max=264.0, vout=5.0, iout=3.0, fsw=65.0e3,
                eta_target=0.80, mode="CCM", ripple_k=0.40)
    base.update(kw)
    return DesignSpec(**base)


def rds_hot_sr(design, sr_rds_on=0.012, temp_c=100.0):
    """SR conduction loss: If_rms^2 * Rds(on) at the hot junction temp."""
    from opl.stress import rds_on_hot

    return rds_on_hot(sr_rds_on, temp_c) * design.irms_sec ** 2


def run(chk) -> None:
    d = design_flyback(spec())
    m = design_magnetics(d)
    c = Components()

    # ---- Steinmetz -------------------------------------------------------
    chk.close(steinmetz_pv(100.0, 0.1), 154.1864, 1e-4, "Pv(100 kHz, 0.1 T) hand value")
    chk.close(steinmetz_pv(200.0, 0.1) / steinmetz_pv(100.0, 0.1), 2.0 ** 1.53, 1e-6,
              "Pv scales as f^alpha")
    chk.close(steinmetz_pv(100.0, 0.2) / steinmetz_pv(100.0, 0.1), 2.0 ** 2.11, 1e-6,
              "Pv scales as B^beta")
    chk.true(steinmetz_pv(100.0, 0.2) > 4.0 * steinmetz_pv(100.0, 0.1),
             "B exponent above 2 makes the loss grow faster than B^2")
    chk.raises(OPL_E_INPUT, steinmetz_pv, 0.0, 0.1, _msg="f=0")
    chk.raises(OPL_E_INPUT, steinmetz_pv, 100.0, 0.0, _msg="B=0")
    chk.raises(OPL_E_TABLE, steinmetz_pv, 100.0, 0.1, "unobtainium", _msg="unknown material")

    # ---- individual loss terms ------------------------------------------
    chk.close(core_loss_w(d, m), 0.132815, 1e-4, "core loss hand value")
    chk.close(core_loss_w(d, m), steinmetz_pv(65.0, m.delta_b) * m.core.ve_cm3 / 1000.0, 1e-12,
              "core loss = Pv * Ve")
    chk.true(core_loss_w(d, m) < 0.5, "core loss is a small term in this design")
    chk.close(copper_loss_w(d, m), 0.446256, 1e-4, "copper loss hand value")
    chk.close(copper_loss_w(d, m),
              d.irms_pri ** 2 * m.wire_pri.r_ac_ohm + d.irms_sec ** 2 * m.wire_sec.r_ac_ohm,
              1e-12, "copper loss = sum of I^2*Rac")
    chk.true(copper_loss_w(d, m) > d.irms_pri ** 2 * m.wire_pri.r_dc_ohm, "AC term included")
    chk.close(bridge_loss_w(d), 1.4 * d.iin_avg, 1e-12, "bridge loss = drop * Iin_avg")
    chk.close(bridge_loss_w(d), 0.208533, 1e-4, "bridge loss hand value")
    chk.close(feedback_loss_w(d, c), 0.003208, 1e-3, "feedback loss hand value")
    chk.true(feedback_loss_w(d, c) < 0.05, "feedback loss is negligible at 5 V")
    sw = switch_losses(d, c)
    chk.close(sw["mosfet_total"],
              sw["mosfet_cond"] + sw["mosfet_sw"] + sw["mosfet_coss"] + sw["mosfet_gate"],
              1e-12, "switch losses add up")
    chk.close(sw["mosfet_gate"], c.mosfet_qg * c.mosfet_vgs * d.spec.fsw, 1e-12, "gate loss formula")
    p_rect = rectifier_loss_w(d, c)
    chk.close(p_rect, c.diode_vf * d.is_avg + c.diode_rs * d.irms_sec ** 2, 1e-12,
              "diode loss = Vf*Iavg + Rs*Irms^2")
    p_rect_sr = rectifier_loss_w(d, Components(rectifier_kind="sync"))
    chk.true(p_rect_sr < p_rect, "SR beats the Schottky at this current")

    # ---- full budget -----------------------------------------------------
    b = loss_budget(d, c, m)
    chk.eq(len(b.items), 10, "ten loss terms")
    names = [it.name for it in b.items]
    for required in ("mosfet_cond", "mosfet_sw", "mosfet_coss", "mosfet_gate", "core",
                     "copper", "rectifier", "clamp", "bridge", "feedback"):
        chk.true(required in names, "loss term present: " + required)
    chk.close(b.total_w, sum(it.value_w for it in b.items), 1e-12, "total is the sum of the items")
    chk.close(b.pout_w, 15.0, 1e-12, "Pout recorded")
    chk.close(b.pin_w, 15.0 + b.total_w, 1e-12, "Pin = Pout + losses")
    chk.close(b.efficiency, 15.0 / (15.0 + b.total_w), 1e-12, "efficiency = Pout/Pin")
    chk.close(b.efficiency, 0.7752, 1e-3, "predicted efficiency hand value (77.5 %)")
    chk.close(b.gap_pct_points, (b.eta_target - b.efficiency) * 100.0, 1e-12, "gap definition")
    chk.true(b.gap_pct_points > 0.0, "predicted efficiency is below the 80 % target")
    chk.eq(b.dominant, max(b.items, key=lambda it: it.value_w).name, "dominant term is the largest")
    chk.eq(b.dominant, "rectifier", "the Schottky dominates this design")
    chk.close(b.get("rectifier"), p_rect, 1e-12, "get() returns the item value")
    chk.close(b.get("nope"), 0.0, 1e-12, "get() of an unknown item is 0")
    chk.close(sum(it.pct for it in b.items), 100.0, 1e-9, "shares add up to 100 %")
    chk.true(any("below the" in w for w in b.warnings), "gap warning raised")
    chk.true(any("fix that term first" in w for w in b.warnings), "dominant-term advice raised")

    b_sr = loss_budget(d, Components(rectifier_kind="sync", sr_rds_on=0.012), m)
    chk.true(b_sr.total_w < b.total_w, "synchronous rectification lowers the total loss")
    chk.true(b_sr.efficiency > b.efficiency, "and raises the predicted efficiency")
    chk.true(b_sr.get("rectifier") < b.get("rectifier"), "the SR term is smaller than the diode term")
    chk.close(b_sr.get("rectifier"), rds_hot_sr(d), 0.05, "SR loss matches I^2*Rds(on)")
    b_wide = loss_budget(d, c, m, material="nope")
    chk.true(any("unknown material" in w for w in b_wide.warnings), "unknown material warns")
    chk.close(b_wide.get("core"), b.get("core"), 1e-12, "fallback material gives the default fit")
    chk.raises(OPL_E_INPUT, loss_budget, "not a design", c, m, _msg="wrong design")
    chk.raises(OPL_E_INPUT, loss_budget, d, c, "not magnetics", _msg="wrong magnetics")
    chk.raises(OPL_E_INPUT, core_loss_w, d, "not magnetics", _msg="core_loss_w type check")

    # ---- pipeline --------------------------------------------------------
    res = run_spec(spec())
    chk.eq(tuple(res.stages_run), ALL_STAGES, "all stages ran by default")
    chk.true(res.flyback is not None, "design stage filled")
    chk.true(res.magnetics is not None, "magnetics stage filled")
    chk.true(res.stress is not None, "stress stage filled")
    chk.true(res.loop is not None and res.loop_power_stage is not None, "loop stage filled")
    chk.true(res.compensator is not None, "compensator attached")
    chk.true(res.safety is not None, "safety stage filled")
    chk.true(res.emi is not None and res.emi_filter is not None, "emi stage filled")
    chk.true(res.budget is not None, "budget stage filled")
    chk.true(len(res.warnings) > 0, "warnings collected from every stage")

    only_design = run_spec(spec(), stages=("design",))
    chk.true(only_design.flyback is not None, "design-only run produces the main circuit")
    chk.true(only_design.magnetics is None, "design-only run skips the transformer")
    chk.true(only_design.budget is None, "design-only run skips the budget")
    chk.eq(tuple(only_design.stages_run), ("design",), "stages_run records the request")
    stress_only = run_spec(spec(), stages=("stress",))
    chk.true(stress_only.magnetics is not None, "stress pulls in the magnetics it needs")
    chk.true(stress_only.loop is None, "stress does not run the loop")
    chk.raises(OPL_E_INPUT, run_spec, spec(), _msg="unknown stage", stages=("nope",))
    chk.raises(OPL_E_INPUT, run_spec, "not a spec", _msg="wrong spec type")
    both = run_spec(spec(), stages=("all", "design"))
    chk.eq(tuple(both.stages_run), ALL_STAGES, "'all' expands without duplicates")
    chk.true("default" in EXAMPLE_SPECS and "dcm_5v" in EXAMPLE_SPECS and "gan_20v" in EXAMPLE_SPECS,
             "example specifications present")
    chk.close(EXAMPLE_SPECS["gan_20v"].pout, 65.0, 1e-9, "65 W example output power")
    chk.close(default_components().mosfet_vds_rated, 650.0, 1e-12, "default part set")

    # ---- report ----------------------------------------------------------
    md = render_markdown(res, title="Unit test design book")
    for token in ("# Unit test design book", "## 1. Summary", "## 2. Flyback main circuit",
                  "## 3. Transformer", "## 4. Component stress and derating",
                  "## 5. Loop compensation", "## 6. Insulation distances (safety)",
                  "## 7. EMC input filter", "## 8. Loss budget",
                  "## 9. Boundaries of this document", "not a circuit simulator"):
        chk.true(token in md, "report contains: " + token)
    chk.true("PASS" in md and "FAIL" in md, "report shows both verdicts")
    chk.true("formula" in md.lower(), "report mentions formulas")
    chk.true(md.count("|") > 200, "report contains tables")
    chk.true("17.75" in md or "0.7752" in md or "77." in md, "predicted efficiency appears")
    partial = render_markdown(only_design)
    chk.true("## 2. Flyback main circuit" in partial, "partial report keeps the design section")
    chk.false("## 4. Component stress" in partial, "partial report omits the stages not run")
    chk.raises(OPL_E_NODATA, render_markdown, None, _msg="render needs a result")

    tmp = tempfile.mkdtemp(prefix="opl_test_")
    try:
        nested = os.path.join(tmp, "a", "b", "c")
        written = write_outputs(res, nested, prefix="ut")
        chk.true(os.path.isdir(nested), "output directory created by Python")
        chk.eq(sorted(written.keys()),
               ["emi", "loop", "losses", "report", "stress", "summary"], "all outputs written")
        for key, path in written.items():
            chk.true(os.path.isfile(path), "file exists: " + key)
            chk.true(os.path.getsize(path) > 0, "file is not empty: " + key)
        with open(written["report"], "r", encoding="utf-8") as handle:
            chk.true(handle.read().startswith("# "), "report file starts with a heading")
        with open(written["stress"], "r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        chk.eq(len(rows), 11, "stress CSV has a header plus ten items")
        chk.eq(rows[0][0], "item", "stress CSV header")
        chk.true(all(len(row) == 9 for row in rows), "stress CSV rows are rectangular")
        with open(written["losses"], "r", encoding="utf-8", newline="") as handle:
            lrows = list(csv.reader(handle))
        chk.eq(len(lrows), 11, "loss CSV has a header plus ten items")
        chk.close(float(lrows[1][1]), res.budget.items[0].value_w, 1e-6,
                  "loss CSV value parses back", abs_tol=1e-6)
        with open(written["loop"], "r", encoding="utf-8", newline="") as handle:
            loop_rows = list(csv.reader(handle))
        chk.eq(len(loop_rows), 401, "loop CSV has a header plus the 400 sweep points")
        with open(written["emi"], "r", encoding="utf-8", newline="") as handle:
            emi_rows = list(csv.reader(handle))
        chk.eq(len(emi_rows), 201, "EMI CSV has a header plus 200 points")
        with open(written["summary"], "r", encoding="utf-8", newline="") as handle:
            sum_rows = list(csv.reader(handle))
        chk.true(len(sum_rows) > 15, "summary CSV has all the headline numbers")
        chk.eq(sum_rows[0], ["quantity", "value", "unit", "note"], "summary CSV header")
        manual = write_csv(os.path.join(tmp, "manual.csv"), ["a", "b"], [[1, 2], [3, 4]])
        chk.true(os.path.isfile(manual), "write_csv creates the file")
        with open(manual, "r", encoding="utf-8") as handle:
            content = handle.read()
        chk.true(content.startswith("a,b"), "CSV header written")
        chk.eq(content.replace("\r\n", "\n").strip(), "a,b\n1,2\n3,4", "CSV content is exact")
        with open(manual, "rb") as handle:
            raw = handle.read()
        chk.true(b"\r\n" in raw, "CSV uses CRLF line terminators")
        chk.true(b"\x1a" not in raw, "no 0x1A byte anywhere in the file")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- CLI -------------------------------------------------------------
    parser = build_parser()
    chk.true(len(parser._actions) > 20, "CLI exposes the full option set")
    args = parser.parse_args(["all", "--vout", "12", "--iout", "2.5", "--out", "tmp_out"])
    s2 = spec_from_args(args)
    chk.close(s2.vout, 12.0, 1e-12, "CLI override reaches the spec")
    chk.close(s2.iout, 2.5, 1e-12, "CLI override for the current")
    chk.eq(args.out, "tmp_out", "output directory parsed")
    args_ex = parser.parse_args(["design", "--example", "gan_20v"])
    s3 = spec_from_args(args_ex)
    chk.close(s3.vout, 20.0, 1e-12, "example spec loaded")
    chk.close(s3.fsw, 100e3, 1e-9, "example switching frequency")
    args_mix = parser.parse_args(["design", "--example", "gan_20v", "--vout", "15"])
    chk.close(spec_from_args(args_mix).vout, 15.0, 1e-12, "explicit option overrides the example")

    from opl.cli import main

    rc_design = main(["design", "--quiet"])
    chk.true(rc_design in (0, 1), "design command returns a verdict code")
    chk.eq(rc_design, 0, "the default design passes the Dmax check")
    rc_all = main(["all", "--quiet"])
    chk.eq(rc_all, 1, "the default part set fails at least one check overall")
    rc_ok = main(["design", "--vout", "200", "--quiet"])
    chk.eq(rc_ok, 3, "an impossible design returns the error code 3")
    rc_bad = main(["safety", "--altitude", "9000", "--quiet"])
    chk.eq(rc_bad, 3, "an out-of-table altitude returns 3")
    rc_pass = main(["all", "--example", "gan_20v", "--quiet", "--cout", "4.7e-3",
                    "--cout-esr", "0.20", "--clearance", "6", "--creepage", "7"])
    chk.true(rc_pass in (0, 1), "the 65 W example runs")
    verdict = verdict_of(res, list(ALL_STAGES))
    chk.true("stress.cap_voltage" in verdict, "verdict names the failing bulk-capacitor rule")
    chk.true(any(v.startswith("stress.") for v in verdict), "verdict names stress items")
    chk.true(all(isinstance(v, str) for v in verdict), "verdict is a list of strings")
