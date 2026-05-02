# DSRT Surf Park — Roster Optimization Design (CP-SAT)

This document specifies the constraint-programming model that should replace the
hand-coded rotation logic in `excel_build.py`. The goal is a system where:

1. The schedule is **proven** correct (every CA labor rule, every coverage rule,
   every lesson rule holds — verified, not asserted).
2. Inputs (staff, hours, waves) are pure data — changing them re-solves; no
   code edits.
3. The output supports both per-day grids (operations view) and per-person
   calendars (the staff view requested in original prompt #2).

The model is implemented with **Google OR-Tools CP-SAT**. Problem size is
small (≤30 staff × ≤32 30-min slots × ~14 station/activity codes × 7 days),
so CP-SAT will solve it in well under a minute even with fairness objectives.

---

## 1. Problem statement (plain English)

For each day of the week:

* Decide, for every 30-minute slot from park-open to park-close,
  which staff member is at which station or activity.
* "Stations" are the 7 LG posts plus Board Rental. "Activities" are
  Supervisor, Private Coaching (L/R reef), Group Lesson, Land Lesson,
  Meal break, Rest break, and Off.
* Honor every constraint the operator stated (the 22 requirements).
* Minimize headcount and total paid hours.

The verifier runs after the solver and re-checks every constraint over the
solver's output table. A roster is only delivered to operations if both
the solver returns FEASIBLE and the verifier returns no violations.

---

## 2. Why CP-SAT, not the current procedural approach

The current `excel_build.py` hand-codes one rotation function per shift per
day. That style fails when:

* Two requirements interact (e.g., "rotate every 30 min" + "BR is the
  shaded relief slot" + "reef guards must be surfers" all bear on the
  same cell).
* A magic number drifts (the off-by-one bugs that caused Friday and Sunday
  Shift B to drop out, and Mon–Thu lesson coaches to fire an hour late).
* Inputs change. Adding a guard, moving a wave, or extending Friday's
  hours currently requires editing 3+ functions.

A constraint solver inverts that: the human writes the *rules*, and the
solver finds an assignment that satisfies them. If no assignment exists,
the solver reports which constraints are unsatisfiable — telling you
exactly where the operating model is over-constrained.

---

## 3. Sets and indices

| Symbol | Meaning |
|---|---|
| `D` | Day key: `mon_thu`, `friday`, `saturday`, `sunday` |
| `T_d` | Ordered list of 30-min slots from `park_open[d]` to `park_close[d]`; `|T_mon_thu| = 27`, `T_fri = 29`, `T_sat = 31`, `T_sun = 29` |
| `P` | Set of staff (people on the master roster) |
| `S` | Stations + activities: `CTR, RR, RS, FLT, LR, LS, FAR, BR, SUP, PRIV_R, PRIV_L, GRP_LES, LAND_LES, MEAL, REST, OFF` |
| `S_lg` | LG stations: `CTR, RR, RS, FLT, LR, LS, FAR, BR` |
| `S_reef` | Reef stations requiring surfer-qualified guard: `RR, LR` |
| `S_coach` | Activities requiring coach (WSI) cert: `PRIV_R, PRIV_L, GRP_LES, LAND_LES` |
| `W_d` | Wave-slot color per `t ∈ T_d`: `yellow, purple, white, none` (none = pre-open / post-close) |

### Per-person attributes

```python
@dataclass
class Person:
    id: str
    name: str
    role_pool: Literal["mgmt","coach","lg","br","casual"]
    reef_eligible: bool          # surfer-qualified
    coach_eligible: bool         # WSI cert
    contract: Literal["FT","PT","CASUAL"]
    weekly_hours_min: int        # FT=40, PT=16-32, CASUAL=0
    weekly_hours_max: int        # FT=40, PT=32, CASUAL=24
    available_days: set[str]     # subset of D
```

---

## 4. Decision variables

```python
x[p, d, t, s] ∈ {0, 1}    # person p is at station/activity s during slot t of day d
```

This is one Boolean per (person, day, slot, activity) tuple. With ~30 staff,
~7 days, ~30 slots, 16 codes that is ~100k Booleans — trivial for CP-SAT.

Auxiliary variables (defined for convenience, all Boolean):
```python
working[p, d, t]  ≡  ∑_{s ≠ OFF} x[p, d, t, s]
on_shift[p, d]    ≡  ∃ t : working[p, d, t]
shift_start[p, d] ∈ T_d  if on_shift[p,d] else ⊥
shift_end[p, d]   ∈ T_d  if on_shift[p,d] else ⊥
```

---

## 5. Hard constraints (mapped to your 22 original requirements)

> The number in `[#N]` is the requirement from the original prompt.

### 5.1 Single-assignment

```
∀p,d,t :  ∑_s x[p,d,t,s] = 1
```
A person is in exactly one station or activity (including OFF) every slot.

### 5.2 Station coverage during operations [#4, #7, #11]

For each `t ∈ T_d` where the park is open:
```
∑_p x[p,d,t,CTR] = 1
∑_p x[p,d,t,RR]  = 1
∑_p x[p,d,t,RS]  = 1
∑_p x[p,d,t,LR]  = 1
∑_p x[p,d,t,LS]  = 1
∑_p x[p,d,t,FAR] = 1
∑_p x[p,d,t,FLT] = 1
∑_p x[p,d,t,BR]  = 1
∑_p x[p,d,t,SUP] = 1
```

Pre-open (e.g., Mon-Thu 7:00–7:30 AM, before first wave at 8) and
post-close (after last wave + 30 min): only `SUP, BR` and a setup/cleanup
crew are required; relax LG-station coverage to ≥0 those slots.

### 5.3 Reef stations require surfer [#10]

```
∀p, ∀d,t,s ∈ S_reef :  x[p,d,t,s] = 0  if not p.reef_eligible
```

### 5.4 Coach activities require WSI [#1, #6, #12]

```
∀p, ∀d,t,s ∈ S_coach :  x[p,d,t,s] = 0  if not p.coach_eligible
```

### 5.5 Rotation cadence ≥ 30 min, ≤ 30 min ideal [#8]

The slot grid is 30 min, so "≥30 min" is automatic. To enforce *exactly*
30-min rotation (no static post), add for every LG station `s ∈ S_lg`:
```
∀p,d,t :  x[p,d,t,s] + x[p,d,t+1,s] ≤ 1
```
Soft variant: penalize 2-consecutive-same-station to allow occasional
hold-overs.

### 5.6 BR is in the LG rotation cycle [#9]

Don't pin BR to a single attendant during waves. Add a fairness constraint:
each guard on a shift gets at least one BR slot per ~4 hours.
```
∀p,d : if on_shift[p,d] then  ∑_{t ∈ shift[p,d]} x[p,d,t,BR] ≥ floor(shift_len/8)
```

### 5.7 California labor law — meal break [#3]

For each person-day where shift length > 5 hours:
```
∑_{t ∈ shift[p,d]} x[p,d,t,MEAL] = 1
```
And the meal slot must occur strictly before the end of the 5th hour:
```
if x[p,d,t,MEAL] = 1 then  t - shift_start[p,d] < 10 slots  (= 5 hrs)
```
For shifts > 10 hours: require a second MEAL.

Avoid waivers (per #3): never set MEAL = 0 when shift > 5 hrs, even
when shift = 6 hrs and waiver would be legal.

### 5.8 California labor law — rest breaks [#3]

For each person-day where shift > 3.5 hrs:
```
∑_{t ∈ shift[p,d]} x[p,d,t,REST] = ceil(shift_len_hrs / 4)
```
Standard 8.5-hr shift → 2 rest breaks. Spacing: each REST must be in a
different ~3.5-hr quadrant of the shift. (Modeled as: REST counts in
`[start, start+7]`, `[start+7, end]` each ≥ 1.)

### 5.9 Shift duration & contiguity

A person works a contiguous block per day:
```
working[p,d,t] = 1, working[p,d,t+1] = 0  =>  ∀t' > t+1 : working[p,d,t'] = 0
```
(Implemented in CP-SAT with `AddImplication` chains, or cleaner with a
single `interval_var` per person-day plus `NoOverlap`.)

Standard FT shifts run 8 to 8.5 hours (16–17 slots). PT 4–8 hours.

### 5.10 Lesson windows [#12, #14, #15, #18]

For each `t ∈ T_d` flagged as a Beginner Lesson slot in `W_d`:

* **Land lesson** at `t-1` (the prior 30-min slot): exactly 6 coaches at LAND_LES.
  ```
  ∑_p x[p,d,t-1,LAND_LES] = 6
  ```
* **Group lesson** at `t` and `t+1` (the wave hour): exactly 6 coaches at GRP_LES.
  ```
  ∑_p x[p,d,t,GRP_LES]   = 6
  ∑_p x[p,d,t+1,GRP_LES] = 6
  ```
* **Same coaches across the lesson** (continuity): if `x[p,d,t-1,LAND_LES]=1`
  then `x[p,d,t,GRP_LES]=1` (the coach who taught land also teaches water).
* **No back-to-back beginner lessons** (#18): if a beginner lesson runs at
  `t`, there is no beginner-lesson `t' ∈ {t+1, t+2}`.

For purple slots (Progressive Turns, Malibu, Barrel Hour) with >10 pax:
```
∑_p x[p,d,t,GRP_LES] ≥ 1   (extra coach in water)
```

### 5.11 Private coaching [#6, #16]

* **Mon–Thu**: Private coaching only available `t ≥ 17:00`. Forbid PRIV_*
  outside that window.
* **Fri–Sun**: Private coaching available all wave hours.
* When private coaching is offered: exactly 1 coach at PRIV_R, exactly 1
  at PRIV_L. Also gated by request — model this as ≤1 each (allow 0 if
  no booking) and let the renderer mark "available" vs "booked".
* Private coach also runs a 30-min land segment before each wave (#12):
  if `x[p,d,t,PRIV_R]=1` then for the 30 min before the lesson the same
  coach is assigned LAND_LES (or a "PRIV_LAND" sub-code).

### 5.12 Coach-cap per wave

For each `t`, in-water coaches ≤ 8 (lifeguards + 6 lesson coaches + 2
private). Practical bound; prevents the solver from over-committing.

### 5.13 Weekly hour caps

```
∀p :  ∑_{d,t} working[p,d,t] × 0.5 ∈ [weekly_hours_min[p], weekly_hours_max[p]]
```

### 5.14 Disjoint shift windows

A person can only work one shift per day (one contiguous block). Enforced
by 5.9.

### 5.15 Day availability

```
if d ∉ available_days[p] then  ∀t,s : x[p,d,t,s ≠ OFF] = 0
```

---

## 6. Soft constraints / objective

CP-SAT minimizes a weighted sum:

```
minimize
    α · Σ working[p,d,t]                       # total paid slots (= cost)
  + β · Σ headcount_per_day                    # bodies actually scheduled
  + γ · Σ |station_time[p,s] - mean(s)|        # per-station fairness
  + δ · Σ holdover_penalty                     # discourage same-station 2-in-a-row
  + ε · Σ early_meal_bonus_inverse             # prefer meals at the natural hour, not the latest legal moment
```

Suggested weights: α = 100, β = 50, γ = 5, δ = 2, ε = 1. Tune after a
first solve.

---

## 7. Architecture

```
wave_schedule/
  cpsat/
    CPSAT_DESIGN.md          ← this document
    config.py                ← imports from existing config.py + adds solver knobs
    staff_data.py            ← Person dataclass + sample roster
    wave_data.py             ← parsed reference calendar; WaveSlot dataclass
    dsrt_solver.py           ← model.build() → CP-SAT model; solver.solve() → tidy table
    verifier.py              ← post-solve audit; returns Violation list
    render_excel.py          ← writes per-day grid + per-person tabs (replaces excel_build.py)
    render_ics.py            ← exports per-person calendar as .ics for phone import
    cli.py                   ← `python -m cpsat.cli solve`, `… verify`, `… render`
  excel_build.py             ← retained for now; deprecated once cpsat verified
  config.py                  ← unchanged; cpsat/config.py extends it
```

The pipeline:

```
inputs (staff_data + wave_data + config) ─→ dsrt_solver.solve()
                                              │
                                              ▼
                                     tidy DataFrame
                                  (person, day, slot, station)
                                              │
                                              ▼
                                       verifier.audit()
                                              │
                                              ▼
                                  render_excel + render_ics
```

Tidy-DataFrame schema:

```python
columns = ["day", "slot_idx", "wallclock", "person_id", "person_name",
           "station", "wave_color", "shift_label"]
```

This is the single source of truth. Both renderers consume it. The
verifier consumes it. Diff-friendly, easy to test.

---

## 8. Acceptance tests (must pass before deployment)

`tests/test_*.py` should include:

1. **Coverage** — for every operating slot, every required station has
   exactly 1 person.
2. **Reef** — every cell with station ∈ {RR,LR} has a reef-eligible person.
3. **Coach** — every PRIV_*, GRP_LES, LAND_LES cell has a WSI-certified person.
4. **Meal-by-5th-hour** — every person-day with shift > 5 hrs has a MEAL
   that starts before slot `shift_start + 10`.
5. **Rest-cadence** — every person-day with shift > 3.5 hrs has rest
   breaks no more than 7 slots apart.
6. **Lesson 6-coach** — every yellow-flagged wave slot has 6 LAND_LES at
   `t-1` and 6 GRP_LES at `t,t+1`, all the same 6 people.
7. **No back-to-back beginners** — no two yellow-lesson slots within 2
   slots.
8. **No 2-slot static** — no person at the same LG station in 2 consecutive
   slots (configurable; can be relaxed to 3 with penalty).
9. **Weekly hours** — each FT person hits 40 ± 1 hr/wk; PT within
   contracted band.
10. **Reproducibility** — re-running the solver with the same seed yields
    the same roster (set `random_seed` in CP-SAT params).

---

## 9. Day-specific notes

* **Mon–Thu**: 2-shift day (A 7:00–15:30, B 12:00–20:30). Beginner lesson
  4pm. Private coaching ≥17:00 only.
* **Friday**: A 7:00–15:30, B 13:00–21:30. Private coaching all day, two
  coach posts (PRIV_R + PRIV_L). Beginner lesson 4pm.
* **Saturday**: 3-shift day (A 6:00–14:30, B 9:00–17:30, C 13:00–21:30).
  Beginner lesson 10am AND 4pm. Bay lesson at 9am (Progressive Turns).
* **Sunday**: A 6:00–14:30, B 12:00–20:30. Beginner lesson 10am AND 4pm.
* **Barrel Hour 18:00–20:00 every day**: no group lessons; advanced waves
  only; spectator-friendly. Private coaching still allowed.

---

## 10. Migration plan

1. **Day 1** — create `cpsat/` skeleton (this design doc + dsrt_solver.py
   stub). Park: 7am–8:30pm. Solve a single Mon–Thu day with hardcoded
   sample staff. Print tidy table.
2. **Day 2** — add verifier; wire all 10 acceptance tests; loop until all pass.
3. **Day 3** — add the other 3 day types. Solve each; verify each.
4. **Day 4** — add render_excel.py producing a workbook with the same
   sheet structure as today (so operators see no UI change).
5. **Day 5** — add render_ics.py; staff get calendar invites.
6. **Day 6** — switch `excel_build.py` to a thin alias that calls cpsat.
   Retire the rotation functions.

If the solver returns INFEASIBLE on any day, the verifier should print
the smallest unsatisfiable subset of constraints (CP-SAT supports
`AddAssumption` for this) so the operator can decide which rule to
relax (typically: hire one more PT LG, or remove a lesson slot).

---

## 11. What to ask Claude Code to do next

Hand it this design doc plus the four scaffold files in `cpsat/`. The
prompt should be:

> Read `cpsat/CPSAT_DESIGN.md`. Sections 4, 5, 6, and 7 specify the model.
> The scaffold in `cpsat/dsrt_solver.py` implements Mon–Thu correctly but
> leaves Friday, Saturday, Sunday as TODO. Extend it so all four days
> solve and all 10 acceptance tests in `cpsat/verifier.py` pass.
> Do not edit `excel_build.py` yet — render_excel.py will replace it
> after the solver is verified.

That gives Claude Code a concrete spec, a working starting point, and a
clear stop condition (the tests).
