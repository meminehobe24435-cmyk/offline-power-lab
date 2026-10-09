# offline-power-lab

**Offline (mains-input) AC-DC switching power supply design & verification toolkit.**

It turns the eight calculations a power-supply engineer normally does "from
experience" - flyback main circuit, transformer, component stress and derating,
loop compensation, safety distances, EMC filter, loss budget, report - into a
**re-runnable calculation book** that a reviewer can check line by line.

Pure **Python 3 standard library**: no numpy, no third-party packages, no network
access, no EDA tool, Python 3.8+.

```
python test/test_all.py           # 965 checks passed
python main.py all --out results  # the full design book + 6 CSV files
python demo_corrected.py          # a part set that passes every check
```

---

## ⚠️ What this is NOT (read before trusting a number)

* **It is a design-calculation and verification tool, not a circuit simulator.**
  No SPICE, no time-domain waveforms, no switching-cycle simulation, no
  convergence, no device models. Every number comes from a closed-form formula
  printed at the top of the module that produced it.
* **No hardware exists.** There is no prototype, no sample, no bench
  measurement, no oscilloscope capture, no thermal chamber, no EMC chamber.
  **Every number in this repository is computed from formulas and public data
  and does not represent the measured performance of any real product.**
* The core table, the safety-distance tables and the material coefficients are
  **simplified subsets of common grades**. They cannot replace vendor datasheets
  or the text of the standards, and **no safety conclusion here can replace a
  safety agency's judgement**.
* The loop model is an **average (small-signal) model**: no sampling effect, no
  detail beyond the RHP zero. **Loop results must be verified on the bench.**
* **No EMC measurement or mitigation was performed, no safety certification was
  obtained, no temperature-rise or reliability testing was done.**
* Predictions are only as good as the parameters you feed into
  `opl.Components`; the defaults are screening values, not a bill of materials.

## Why this exists

An offline flyback is a chain of about eight coupled calculations, and in
practice links get skipped: the duty-cycle target is fine but nobody rechecks
the bulk capacitor at 264 VAC; the core passes the area-product method but the
winding does not fit the bobbin; the loop crosses over "at fsw/20" with a phase
margin nobody computed. Each step is simple; the chain is not. That is exactly
the kind of work that should be automated, printed with its formulas, and
re-checked by anyone who reads it.

So this project deliberately does four things:

1. **every formula and its unit is written above the code that uses it** (in a
   hardware project, units *are* the documentation);
2. **conservation laws are used as self-checks** - power balance closes to
   1e-9, `Is_avg*Vout_ref = Pin`, `Lp/Lbcm = (2-kr)/kr`, `ratio = actual/rated`;
3. **every check ends in an explicit verdict** - actual, rated, ratio, margin and
   PASS/FAIL - including the verdicts that say *FAIL*;
4. the public API (units, error codes, every signature) was written **before**
   the implementation, in `opl/__init__.py` and `opl/model.py`.

## Reference run (numbers produced by this code, not measured)

Input: universal mains **90-264 VAC**, output **5.0 V / 3.0 A**, **fsw = 65 kHz**,
efficiency target **80 %**, bridge drop 1.4 V, secondary rectifier drop 0.5 V,
Dmax target 0.45 (hard limit 0.50), CCM with a 0.40 ripple ratio.

| Quantity | Value | Unit |
|---|---|---|
| Bulk DC voltage min / max | 125.88 / 371.95 | V |
| Reflected voltage Vor | 102.992 | V |
| Turns ratio n = Np/Ns | 18.726 (continuous) / 18.214 (built) | - |
| Dmax / Dmin | 0.4500 / 0.2169 | - |
| Primary inductance Lp (boundary 1.3164 mH → CCM) | 5.2656 | mH |
| Primary peak / start current | 0.4138 / 0.2483 | A |
| RMS primary / secondary current | 0.2243 / 4.6445 | A |
| Secondary peak / average current | 7.7479 / 3.4091 | A |
| Area product required vs chosen core | 0.1247 vs 0.1457 (EE20, 1.17x) | cm^4 |
| Turns Np / Ns | 255 / 14 | - |
| Air gap (centre leg) | 0.4585 | mm |
| Bmax (target 0.28 T, saturation ~0.35 T at 100 °C) | 0.2782 | T |
| AC flux swing ΔB | 0.1086 | T |
| Wire | primary AWG29 x1, secondary AWG23 x5 | - |
| Window utilisation | 0.515 | - |
| Skin depth at 65 kHz / 100 °C | 0.297 | mm |

### Component stress and derating, default (screening) part set

650 V MOSFET, 450 V bulk capacitor, 3 x 1.2 A output capacitors, Schottky
rectifier, 2.2 nF RCD clamp, leakage assumed at 1 % of Lp:

| Item | Actual | Rated | Ratio | Margin | Verdict |
|---|---|---|---|---|---|
| mosfet_vds | 538.96 V | 650 V | 0.829 | −3.6 % | **FAIL** |
| mosfet_id_pk | 0.414 A | 25 A | 0.017 | +97.9 % | PASS |
| mosfet_id_rms | 0.224 A | 6 A | 0.037 | +94.7 % | PASS |
| mosfet_power | 0.830 W | 1.50 W | 0.553 | +21.0 % | PASS |
| diode_vr | 24.86 V | 100 V | 0.249 | +68.9 % | PASS |
| diode_if_avg | 3.409 A | 10 A | 0.341 | +54.5 % | PASS |
| diode_power | 1.966 W | 1.00 W | 1.966 | −180.8 % | **FAIL** |
| cap_voltage | 371.95 V | 450 V | 0.827 | −3.3 % | **FAIL** |
| cap_ripple | 3.546 A | 3.60 A | 0.985 | −23.1 % | **FAIL** |
| cap_temp | 50.87 °C | 94.5 °C | 0.538 | +40.2 % | PASS |

Loop, safety, EMI and losses for the same run:

| Check | Result | Verdict |
|---|---|---|
| Loop crossover (analytic sketch vs sweep) | 347.3 Hz (332.0 Hz, error 4.42 %) | - |
| Phase margin / gain margin | 125.3 ° / 5.0 dB (target 45 ° / 10 dB) | **FAIL** (GM) |
| Safety: clearance required vs design | 3.00 vs 6.00 mm (reinforced, PD2, IIIa, 2000 m) | PASS |
| Safety: creepage required vs design | 6.40 vs 6.50 mm | PASS |
| Earth leakage (2 x 1 nF) vs class II limit | 0.166 vs 0.25 mA | PASS |
| DM insertion loss 40 dB from | 1.048 MHz (needs to be 150 kHz) | **FAIL** |
| CM insertion loss 40 dB from | 150 kHz | PASS |
| Total loss / predicted efficiency | 4.350 W / 77.52 % (target 80 %) | gap +2.48 pts |
| Dominant loss | rectifier 1.966 W (45.2 % of all losses) | - |

### The same design with a corrected part set (`python demo_corrected.py`)

800 V MOSFET, 4.7 nF clamp capacitor, 12 mΩ synchronous rectifier, 500 V bulk
capacitor, 940 µF / 0.20 Ω output bank (5 capacitors), input filter
1 µF X + 470 µH DM + 10 mH CM + 2 x 1 nF Y:

| Item | Actual | Rated | Ratio | Margin | Verdict |
|---|---|---|---|---|---|
| mosfet_vds | 518.74 V | 800 V | 0.648 | +18.9 % | PASS |
| mosfet_power | 0.830 W | 1.50 W | 0.553 | +21.0 % | PASS |
| diode_vr (SR) | 24.86 V | 60 V | 0.414 | +48.2 % | PASS |
| diode_power (SR) | 0.453 W | 1.00 W | 0.453 | +35.3 % | PASS |
| cap_voltage | 371.95 V | 500 V | 0.744 | +7.0 % | PASS |
| cap_ripple | 3.546 A | 6.00 A | 0.591 | +26.1 % | PASS |
| cap_temp | 62.6 °C | 94.5 °C | 0.662 | +26.4 % | PASS |

| Check | Result | Verdict |
|---|---|---|
| Derating table | 9 / 9 items pass | PASS |
| Loop: crossover / PM / GM | 245.6 Hz (analytic 244.7, error 0.38 %) / 114.6 ° / not limited | PASS |
| Safety: clearance 3.00 vs 6.00 mm, creepage 6.40 vs 6.50 mm, leakage 0.166 mA | - | PASS |
| EMC filter: DM and CM 40 dB from 150 kHz, leakage 0.166 mA | - | PASS |
| Total loss / predicted efficiency | 3.055 W / **83.08 %** (target 80 %) | −3.08 pts (better) |
| Dominant loss | RCD clamp 0.982 W (32.1 %) | - |
| Output capacitor life estimate | 94 484 h at 62.6 °C core (105 °C / 5000 h part) | - |

Every number above comes from `python main.py all --out results` and
`python demo_corrected.py`, both of which are run in CI on every push.

## Tests

```
$ python test/test_all.py
test_core: 292/292 checks passed
test_loop: 89/89 checks passed
test_safety_emi: 121/121 checks passed
test_budget_report: 140/140 checks passed
test_edge: 323/323 checks passed

965 checks passed
```

No pytest, no unittest: `test/oplcheck.py` is a 100-line counter with source-line
reporting, so the suite runs anywhere Python does and returns a non-zero exit
code when anything fails.

The suite mixes three kinds of assertion on purpose:

1. **hand-computed textbook values written as literals** - e.g. for the run
   above, `Dmax = 0.4500`, `Vor = 102.992 V`, `Lp = 5.2656 mH`,
   `Ipk = 0.413756 A`, `Lp/Lbcm = (2−kr)/kr = 4`, skin depth
   `66.1/sqrt(f) = 0.2593 mm` at 20 °C, an air gap of `1.2066 mm` for
   `Lp = 1 mH / Np = 100 / Ae = 1 cm²`, `Pv(100 kHz, 0.1 T) = 154.19 mW/cm³`,
   reinforced creepage `2 x 2.5 = 5.0 mm`, class II leakage limit `0.25 mA`.
   These catch the failure mode a self-consistent suite never sees: **a wrong
   formula that only checks itself**;
2. **conservation laws and identities** at 1e-9 (power balance, ampere-turn
   balance, `Lp/Lbcm = (2−kr)/kr`, `IL` roll-off of 40 dB/decade, `ratio =
   actual/rated`, `Σ loss shares = 100 %`);
3. **boundary and illegal inputs** - 18 extreme-but-legal specifications
   (85 V only, 230 V only, 20 kHz, 500 kHz, 1.2 V output, 48 V output, deep DCM,
   AUTO mode, 0.70 Dmax …) where the invariants must still hold, plus a negative
   case for **every** documented error code and **both directions of every
   derating rule** (a corrected part set that must pass and an undersized one
   that must fail).

## Real problems the tests found

**1. The derivative of the reflected voltage.** *Symptom:* 13 of the first 290
assertions failed while the code was right. *Root cause:* my own hand values
(`Vor = 102.9925 V`, `Lp = 5.2659 mH`, `Dmin = 0.2168475`) were slightly wrong -
I had mis-divided `Vin·D/(1−D)` and used rounded intermediates. *Fix:* recompute
every anchor from the textbook formulas in a separate one-liner before pinning
it, keep hand values at a 1e-4 relative tolerance and reserve 1e-9 for the
identities. It is a small lesson with a large consequence: a test suite is only
as independent as the arithmetic behind its expectations.

**2. Core selection was driven by the winding fit, not by the area product.**
*Symptom:* the selected core came out as EE25 with an AP margin of 3.38x, and the
primary winding had a current density of 0.89 A/mm² instead of the assumed
4 A/mm². *Root cause:* `pick_wire` picked the **thickest** strand allowed by the
skin-depth limit (2δ = 0.594 mm) instead of the thinnest wire that carries the
current, and the selection loop `for cand in reversed(AWG_TABLE)` assigned
without breaking, so the last (thickest) match won. *Fix:* filter the AWG table
by the skin limit and take the **minimum** diameter that meets the required
copper area, then iterate to the next core while the *achieved* fill factor
exceeds the fit limit. The primary became AWG29, `Ku` dropped from 0.64 to 0.52,
and the core moved EE25 → EE20 - a smaller and cheaper transformer from the same
formulas. *Pitfall for the reader:* the area-product method sizes the window for
the primary winding only; the secondary copper is not in that number, so a fit
check is mandatory, not optional.

**3. A "successful" loop design that was actually a 10° phase margin.**
*Symptom:* the auto-designed compensator reported `fc = 328 Hz, PM = 143°`, but
the real loop bandwidth was 1.27 kHz and the phase margin there was 10°.
*Root cause:* `kc` was solved so that `|T(fc)| = 1`, and with a high-Q output
filter (Q = 3.14, f0 = 1.04 kHz) the loop gain dips through 0 dB in a flat
"notch" at fc and rises again over the resonance; the phase at the notch is
−37°, which looks wonderful and means nothing. *Fix:* (a) define the crossover
as the **first falling 0 dB crossing** and use the same definition everywhere,
(b) place the compensator zero **at** the crossover so the slope there is a clean
−20 dB/dec, (c) report every additional 0 dB crossing as a conditional-stability
warning, and (d) take the **worst** gain margin over all −180° crossings. The
tool now refuses to look better than it is: the default 40 mΩ output bank gives
GM = 5.0 dB and the run is marked **FAIL**, which is the correct answer for a
Q = 3.14 filter.

**4. The analytic-vs-numeric crossover comparison was meaningless.**
*Symptom:* the asymptotic Bode sketch disagreed with the exact sweep by 90-300 %.
*Root cause:* three separate mistakes - the sketch anchored its magnitude at
10 Hz and accumulated corner-rounding error along the way; it drew a plain
−2 slope for the double pole and therefore never saw the +Q resonant peak; and it
returned the *last* 0 dB crossing while the numeric search returned the *first*.
*Fix:* exact magnitudes at the breakpoints with the textbook slopes in between,
a `(f0/Q, +1)` / `(f0, −3)` anchor pair for a resonant double pole, the same
crossing definition on both sides, and a few exact Newton refinements. The
reconciliation error is now 0.01-4.4 % across the tested designs, which makes it
a usable check instead of decoration.

**5. The capacitor thermal model poured the whole bank into one capacitor.**
*Symptom:* the corrected design failed the `cap_temp` rule at 141 °C.
*Root cause:* the ESR loss of the *entire* output bank was multiplied by the
thermal resistance of *one* capacitor. *Fix:* divide the loss by the number of
parallel capacitors (`T_core = Tambient + (P_esr/n)·Rth_1cap`) - the heat is
shared, and so is the ripple current. The corrected design now sits at 62.6 °C
with an estimated 94 kh of life, and the check is meaningful again.

**6. Negative air gap instead of more turns.**
*Symptom:* extreme specifications (high Lp, low current) failed with
`negative gap` and eventually `OPL-E-NOCORE`.
*Root cause:* the turn count was sized only for the flux-density target, but an
ungapped core tops out at `L_max = µ0·Np²·Ae·µr/le`; if the design inductance is
higher, the required gap is negative, which is not manufacturable. *Fix:* clamp
`Np >= sqrt(Lp·le/(µ0·Ae·µr))` and re-solve the operating point (which also
lowers Bmax). Found by the boundary suite, not by the happy path.

**7. Two "screen ratings" that made derating verdicts meaningless.**
*Symptom:* `mosfet_power` and `diode_power` were compared against numbers the
tool invented (`0.5·Vds·Id`, `0.5·If·Vf`), which is exactly the kind of fake
rating a derating table must never contain. *Fix:* `Components` gained explicit
`mosfet_power_rated` and `diode_power_rated` fields (W) that come from the
caller's own thermal budget, so a FAIL now means something.

## Pitfalls ("踩过的坑")

1. **Windows text mode eats files.** One stray `0x1A` (Ctrl-Z) in a file read in
   text mode truncates the rest of it silently, and the default code page is not
   UTF-8. Every write in this project passes `encoding="utf-8"`, every CSV adds
   `newline=""`, and the test suite asserts that no `0x1A` byte reaches a file.
2. **A pipe turns a red build green.** `python test/test_all.py | head` kills the
   runner with SIGPIPE, and `cmd | tee` masks the exit code unless `pipefail` is
   on. Every CI step here redirects to a file, prints the file, and exits with
   the saved status.
3. **`make.exe` has no shell.** `mkdir -p` does not exist on Windows `make`, so
   all output directories are created by Python (`os.makedirs` inside
   `write_outputs`) and no Makefile target needs a subdirectory first.
4. **`git push` looks like it failed when it did not.** Over PowerShell, git
   writes progress to stderr and the pipeline reports `NativeCommandError` with a
   non-zero exit code even on a successful push. Check the branch line
   (`* [new branch] main -> main`), not the exit code.
5. **Hand-computed expectations need their own independent check.** See problem 1:
   pinning a wrong literal is indistinguishable from finding a bug. Recompute the
   anchor with a separate expression before writing it into the test, and keep
   hand values at 1e-4 while the identities stay at 1e-9.
6. **`reversed(list)` + assignment instead of `break` = last match wins.** That
   one silent mistake chose the thickest wire instead of the thinnest (problem 2)
   and moved the design to a bigger core. When scanning a sorted table for an
   extreme, filter first and take `min()`/`max()` explicitly.
7. **`__all__` drifts away from reality.** Adding `bridge_loss_w` to the
   implementation but not to the export list broke an import in a test module.
   CI now asserts that every name declared in `opl.__all__` actually exists.
8. **The leakage assumption dominates the predicted efficiency.** With
   `Llk = 1 % of Lp` and a 2.2 nF clamp capacitor the RCD clamp burns 0.76 W
   (17.6 % of all losses); with a 4.7 nF clamp it burns 0.98 W but the Vds spike
   drops by 30 V. Both numbers move with one parameter that nobody measures -
   so it is a parameter, not a constant, and the report says so.
9. **`inf` is not a bug.** `gain_margin_db = inf` means "the phase never reaches
   −180° inside the swept range", i.e. the gain margin is not the limiting
   factor - not that the calculation broke. It is documented on the field.

## Repository layout

```
opl/__init__.py     public API, units, error codes, quick start   <- the "header"
opl/errors.py       stable error codes + input validation helpers
opl/model.py        every data structure, every field documented with its unit
opl/flyback.py      main circuit: Vor, n, Dmax/Dmin, Lp, Ipk, RMS (CCM and DCM)
opl/magnetics.py    AP core selection, turns, gap, Bmax, skin depth, wire
opl/stress.py       MOSFET / rectifier / capacitor / clamp stress + derating table
opl/loop.py         average small-signal model, Type-II design, Bode analysis
opl/safety.py       clearance / creepage look-up, altitude, earth leakage
opl/emi.py          CM/DM insertion loss, X/Y capacitor and CM-choke selection
opl/budget.py       itemised loss budget, Steinmetz core loss, efficiency
opl/report.py       Markdown design book + CSV writers (UTF-8)
opl/pipeline.py     stage orchestration, example specifications
opl/cli.py          argument parser and text sheet
main.py             CLI entry point
demo_corrected.py   the passing reference run quoted above
test/               965 dependency-free checks
.github/workflows/  CI: ubuntu + macos, Python 3.10 + 3.12, plus a strict job
```

## Boundaries of the tables and the models

* `CORE_TABLE` lists typical published geometry (Ae, Aw, le, Ve) plus a typical
  bobbin mean-turn-length for nine common E/EE cores, rounded to three
  significant digits, for **selection and sanity checking only**.
* `MATERIALS` has **one** representative 3C90-class Steinmetz fit
  (`Pv = 17.3·f^1.53·B^2.11` with `f` in kHz, `B` in T, `Pv` in mW/cm³, anchored
  near 100 °C), valid roughly for 20-200 kHz and 50-200 mT with **±40 %**
  uncertainty. Replace it with your vendor's `Pv` curves before any thermal
  decision.
* Wire AC resistance uses the skin-effect-only approximation
  `Fr = 1 + (d/δ)^4/48` and **ignores proximity effect**, so copper loss is a
  lower bound.
* The safety tables are a rounded subset of the IEC 60950-1 / GB 4943.1-style
  bands (50-1000 Vrms, pollution degree 1-3, material groups I/II and IIIa/IIIb,
  2000-7000 m), with `reinforced = 2 x basic`. The standards derive reinforced
  distances from their own tables and are not always exactly a factor of two.
* The EMC section cannot tell you what attenuation a product **needs**: there is
  no noise spectrum in this tool. The required attenuation is an input and the
  answer is "at which frequency does this filter reach it".
* No tolerance, Monte-Carlo, worst-case-over-temperature or ageing analysis (yet).

## License

MIT - see `LICENSE`.
