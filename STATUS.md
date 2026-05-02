# DSRT Surf Park Roster — Project Status

_Last updated: 2026-04-29_

---

## What this project is

A CP-SAT (constraint-programming) roster solver for Desert Surf Park.  It
replaces the original hand-coded Excel rotation logic (`excel_build.py`, now
deleted) with a declarative model: you write the _rules_, the solver finds a
valid roster.  If no valid roster exists, a built-in diagnosis tool identifies
which rules are in conflict.

---

## Current file structure

```
wave_schedule/
  config.py              Park hours, shift windows, CA labor law break rules
  STATUS.md              This file
  CLAUDE.md              AI assistant context / architecture notes
  README.md              Original project readme (pre-solver)
  requirements.txt       pip packages

  cpsat/
    __init__.py
    CPSAT_DESIGN.md      Full specification: variables, constraints, objective
    dsrt_solver.py       CP-SAT model — the core solver
    staff_data.py        ROSTER (Person dataclass + 30-person roster)
    wave_data.py         Wave calendar (lesson slots, wave types by day)
    verifier.py          Pure-Python audit of solver output + infeasibility diagnosis
```

`excel_build.py` and the `excel_build` shell wrapper have been deleted.
`render_excel.py` and `render_ics.py` are not yet written (next steps after
the solver passes all verifier checks).

---

## What works

- **Per-day models** (`solve_day(day_key)`) are FEASIBLE in ~90–150 s each for
  all four day-types (mon_thu, friday, saturday, sunday).
- **Constraint coverage**: all 10 named constraint groups are implemented and
  tested individually.
- **Infeasibility diagnosis** (`verifier.diagnose_infeasibility(day_key)`):
  when a per-day model is INFEASIBLE, the function systematically removes one
  constraint group at a time to identify which groups are causing the conflict
  and prints a plain-English remedy (e.g. "hire 1–2 more lifeguards").
- **Verifier** (`verifier.audit(assignments)`): pure-Python re-check of all
  constraints over solver output.  Acts as the executable specification —
  a roster is valid iff `audit()` returns an empty list.

---

## What doesn't work yet

### Joint weekly model times out

`solve_week()` builds all four day-types in a single shared CpModel so that
weekly hour constraints (e.g. FT staff must work exactly 40 h/week) are
enforced globally.  The solver returns UNKNOWN after 600–1200 s.

**Root cause:** FT staff have `weekly_hours_min == weekly_hours_max == 40`.
The hard equality constraint, combined with 9-person-per-slot coverage
requirements and CA break rules, creates tight cross-day coupling that the
solver cannot resolve within the time budget.

**What was tried:**
- Warm-start hints from per-day solves (applied ~50 k variable hints)
- Proportional daily caps so hints are close to the weekly target
- Removing the Maximize objective (feasibility-only solve)
- BR staff exempted from rotation cadence (fixes a separate infeasibility)
- Increasing time budget to 1800 s — still UNKNOWN

**What has NOT been tried yet:**
- Softening the FT weekly hour constraint to a range (e.g. 38–42 h)
- Two-level decomposition: small LP to decide hours-per-day, then per-day models
- Lagrangian relaxation of the weekly coupling

---

## Planned architectural changes

The inputs are being restructured away from hard-coded named day-keys toward
generic operating-day _templates_ parameterised by:

1. **Shift length** — e.g. 12-hour day, 14-hour day, rather than
   "mon_thu" / "friday" / "saturday" / "sunday"
2. **Headcount ratios** — configurable FT vs PT counts, rather than a fixed
   30-person roster with hard-coded role slots

### Impact on each file

| File | Change needed |
|------|---------------|
| `config.py` | Replace `HOURS`/`SHIFTS` dicts keyed by day-name with a `DAY_TEMPLATES` list keyed by template ID (e.g. `"12h"`, `"14h"`) |
| `staff_data.py` | Replace `available_day_keys` (which references specific day names) with `available_template_ids`; make FT/PT counts configurable parameters rather than hard-coded Person entries |
| `wave_data.py` | Replace per-day-key `CALENDAR` with per-template wave sequences; lesson slot times become offsets from wave-open rather than absolute wall-clock times |
| `dsrt_solver.py` | `DaySpec` and `day_spec()` will reference templates; `solve_week()` will iterate over template instances rather than hard-coded `DAY_KEYS`; `DAY_WEIGHT` will be supplied as a parameter |
| `verifier.py` | Audit logic is already generic; only the `_ALL_DAY_KEYS` constant in `__main__` needs updating |

### Weekly hours — key insight

The current solver struggle with exact 40-h FT constraints stems from the
day-key structure.  Under the new template approach, FT staff would have
a _range_ (e.g. 38–42 h), and the number of templates per week is a
configuration input rather than hard-coded as 4+1+1+1.  This removes the
tight cross-day equality that makes the joint model so hard to solve.

---

## Known bugs / constraints to revisit

1. **Private coaching windows** (mon_thu only): cutoff at 17:00 is hardcoded
   in `add_private_coaching_windows()`.  Under the template model this should
   become a configurable offset from first-wave.

2. **Lesson coach count** is hardcoded at 6 in `add_lesson_coverage()`.
   Make this a parameter in the day template.

3. **MAX_SHIFT** (8.5 h) is derived from the shift windows in `config.py` but
   not exposed as a tunable parameter.  Under the template model it should be
   `template.shift_hours * 2` slots.

4. **CASUAL staff** have `weekly_hours_min == 0`, so the solver may assign them
   zero hours even when coverage is tight.  Consider a minimum-activation
   constraint if casuals are expected to be scheduled.

---

## How to run

```bash
conda activate dsrt_roster   # Python 3.11, ortools 9.15, openpyxl

# Single day (fast, for debugging)
python -m cpsat.dsrt_solver solve mon_thu

# Full week + audit (currently times out on joint model)
python -m cpsat.verifier

# Diagnose infeasibility on a single day (standalone)
python -c "from cpsat.verifier import diagnose_infeasibility; diagnose_infeasibility('mon_thu')"
```
