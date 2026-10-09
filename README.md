# offline-power-lab

**Offline (mains-input) AC-DC switching power supply design & verification toolkit.**

Turns the steps a power-supply engineer normally does "by experience" - flyback
main circuit, transformer, component stress and derating, loop compensation,
safety distances, EMC filter, loss budget - into a **re-runnable calculation
sheet** that a reviewer can check line by line.

Pure **Python 3 standard library** (no numpy, no third-party packages, no
network access, no EDA tool required). Works on Python 3.8+.

> ## ⚠️ What this is NOT
>
> * **It is a design-calculation and verification tool, not a circuit
>   simulator.** No SPICE, no time-domain waveforms, no switching-cycle
>   simulation, no convergence, no device models. Every number comes from the
>   closed-form formulas printed at the top of each module.
> * **There is no hardware.** No prototype, no bench measurement, no scope
>   capture, no thermal chamber - **all numbers in this repository are computed
>   from formulas and public data, and none of them represent the measured
>   performance of any real product.**
> * The core table, the safety-distance tables and the device parameters are
>   **simplified subsets of common grades**. They cannot replace vendor
>   datasheets or the text of the standards, and **no safety conclusion here can
>   replace a safety agency's judgement**.
> * The loop model is an **average (small-signal) model**: no sampling effect,
>   no high-frequency detail beyond the RHP zero. **Loop results must be
>   verified on the bench.**
> * **No EMC measurement or mitigation was performed, no safety certification
>   was obtained, and no temperature-rise or reliability testing was done.**

---

## Why this exists

Offline flyback design is a chain of about eight coupled calculations, and in
practice each link is often skipped: the duty-cycle target is fine but nobody
rechecks the derating of the bulk capacitor at 264 VAC; the transformer fits the
AP method but not the bobbin; the loop crosses over at 1/20 of fsw with a phase
margin that was never computed. The steps are individually simple and
collectively easy to get wrong - exactly the kind of work that should be
automated and printed as a calculation book instead of being remembered.

This project implements that chain with:

* **every formula and its units written above the code that uses it** (this is a
  hardware project - units are the documentation),
* **conservation laws used as self-checks** (power balance, ampere-turn
  equality, `Lp/Lbcm = (2-kr)/kr`),
* **explicit pass/fail tables** with actual value, rating, ratio, margin and
  verdict - including the verdicts that say *fail*,
* **~300 assertions** in a dependency-free suite, of which a deliberate subset
  are **hand-computed textbook values** written into the test file as literals,
  so that a self-consistent but wrong formula cannot pass.

## Quick start

```bash
git clone https://github.com/meminehobe24435-cmyk/offline-power-lab.git
cd offline-power-lab

python test/test_all.py          # full self-check suite, prints "<N> checks passed"
python main.py design            # default example: 90-264 VAC -> 5 V / 3 A, 65 kHz
python main.py stress            # component stress + derating verdict table
python main.py all --out results # (once all stages land) report + CSVs
```

`make test` and `make demo` do the same thing on systems that have `make`.

## Status of this build stage

| Stage | Module | State |
|-------|--------|-------|
| Flyback main circuit (CCM + DCM) | `opl/flyback.py` | implemented |
| Transformer / inductor (AP method) | `opl/magnetics.py` | implemented |
| Stress + derating verdicts | `opl/stress.py` | implemented |
| Loop compensation (Type-II, TL431+opto) | `opl/loop.py` | next |
| Safety distances | `opl/safety.py` | next |
| EMC input filter | `opl/emi.py` | next |
| Loss / efficiency budget | `opl/budget.py` | next |
| Report (Markdown + CSV) and full CLI | `opl/report.py`, `opl/cli.py` | partial (text output today) |

The public API of **all** of these modules is already fixed and documented with
units in `opl/__init__.py` (the "header file" of the project was written before
any implementation).

## Worked example (real output, computed by this code)

Input: universal mains **90-264 VAC**, output **5.0 V / 3.0 A**, **fsw = 65 kHz**,
efficiency target **80 %**, bridge drop 1.4 V, secondary rectifier drop 0.5 V,
Dmax target 0.45 (limit 0.50), CCM ripple ratio 0.40.

| Quantity | Value |
|----------|-------|
| Bulk DC voltage min / max | 125.88 / 371.95 V |
| Reflected voltage Vor | 102.99 V |
| Turns ratio n = Np/Ns | 18.73 (continuous design; 255/14 = 18.21 after rounding) |
| Dmax / Dmin | 0.4500 / 0.2169 |
| Primary inductance Lp | 5.2656 mH (boundary 1.3164 mH -> CCM) |
| Primary peak / start current | 0.4138 / 0.2483 A |
| RMS primary / secondary | 0.2243 / 4.6445 A |
| Selected core | EE20, AP margin 1.17x |
| Turns Np / Ns | 255 / 14 |
| Air gap | 0.459 mm |
| Bmax / AC swing | 0.278 / 0.109 T (target 0.28 T) |
| Wire | primary AWG29 x1, secondary AWG23 x5 |
| Window utilisation | 0.52 |

Component stress and derating for the default part set (650 V MOSFET, 450 V bulk
capacitor, 3 x 1.2 A output capacitors, Schottky rectifier):

| Item | Actual | Rated | Ratio | Margin | Verdict |
|------|--------|-------|-------|--------|---------|
| mosfet_vds | 539.0 V | 650 V | 0.829 | -3.6 % | **FAIL** |
| mosfet_id_rms | 0.224 A | 6 A | 0.037 | +94.7 % | PASS |
| mosfet_power | 0.830 W | 1.5 W | 0.553 | +21.0 % | PASS |
| diode_vr | 24.86 V | 100 V | 0.249 | +68.9 % | PASS |
| diode_if_avg | 3.409 A | 10 A | 0.341 | +54.5 % | PASS |
| diode_power | 1.966 W | 1.0 W | 1.966 | -180.8 % | **FAIL** |
| cap_voltage | 371.95 V | 450 V | 0.827 | -3.3 % | **FAIL** |
| cap_ripple | 3.546 A | 3.6 A | 0.985 | -23.1 % | **FAIL** |
| cap_temp | 62.6 degC | 94.5 degC | 0.662 | +26.4 % | PASS |

These four failures are **real findings, not bugs** - they are what the tool is
for:

* the 650 V MOSFET is used at 82.9 % of its rating once the leakage spike
  (64 V from Llk = 1 % of Lp with a 2.2 nF clamp capacitor) is added;
* a 450 V bulk capacitor at 371.95 V **cannot** satisfy an 80 % derating rule -
  industry practice is to relax the rule to 85-90 % for bulk capacitors, or to
  use a 500 V part;
* the output capacitor ripple current of a CCM flyback at D = 0.45 is brutal
  (3.55 A RMS) and three 1.2 A capacitors are not enough;
* a Schottky rectifier dissipates 1.97 W at 3.4 A average - use a synchronous
  rectifier (0.45 W with 12 mOhm) or a much bigger diode.

With an 800 V / 500 V part set, 5 output capacitors and a synchronous rectifier
every item passes - that "corrected" run is part of the test suite, so the
passing case is asserted too and not just claimed.

## Tests

```bash
python test/test_all.py
```

```
test_core: 291/291 checks passed

291 checks passed
```

The suite mixes three kinds of assertion on purpose:

1. **hand-computed textbook values written as literals** (e.g. `Dmax` for a
   forced Vor, `Lp`/`Ipk` for a given operating point, skin depth
   `66.1/sqrt(f)` at 20 degC, gap `1.2066 mm` for `Lp = 1 mH / Np = 100 /
   Ae = 1 cm^2`), so that a wrong-but-self-consistent formula is caught;
2. **conservation laws** (power balance closes to 1e-9, `Is_avg*Vout_ref = Pin`,
   `Lp/Lbcm = (2-kr)/kr`, diode/SR loss identities, `ratio = actual/rated`);
3. **boundary and illegal inputs** - every documented error code, plus both the
   passing and the failing direction of every derating rule.

## Repository layout

```
opl/__init__.py    public API, units, error codes, quick start  <- the "header"
opl/errors.py      error codes + input validation helpers
opl/model.py       every data structure, every field documented with its unit
opl/flyback.py     main circuit: Vor, n, Dmax/Dmin, Lp, Ipk, RMS (CCM and DCM)
opl/magnetics.py   AP core selection, turns, gap, Bmax, skin depth, wire
opl/stress.py      MOSFET / rectifier / capacitor / clamp stress + derating table
test/test_all.py   dependency-free runner, prints "<N> checks passed"
test/test_core.py  the checks for the three implemented modules
main.py            CLI entry point
```

## Boundaries (read before trusting a number)

* Design calculation only. Not a simulator, not a PCB tool, no parasitics, no
  thermal FEM, no Monte-Carlo or tolerance analysis (yet).
* No hardware was built. **No number here is a measurement.**
* `CORE_TABLE` holds typical published geometry for common E/EE cores (Ae, Aw,
  le, Ve) plus a typical bobbin MLT, rounded to three significant digits and
  meant for selection and sanity checking only.
* The Steinmetz coefficients in `MATERIALS` are one representative 3C90-class
  fit, valid roughly over 20-200 kHz and 50-200 mT, with **±40 % uncertainty**:
  replace them with your vendor's `Pv` data before making a thermal decision.
* Wire AC resistance uses the skin-effect-only approximation
  `Fr = 1 + (d/delta)^4/48` and therefore **ignores proximity effect**: it is a
  lower bound.
* Device parameters (Rds(on) temperature slope, Coss, Qg, tr/tf, capacitor ESR,
  thermal resistances) are the caller's inputs from `opl.Components`; the
  defaults are plausible screening values, not a specific part.

## License

MIT - see `LICENSE`.
