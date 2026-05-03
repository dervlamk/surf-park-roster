# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CP-SAT (Google OR-Tools) roster solver for DSRT Surf Park. The solver replaces the deleted hand-coded Excel rotation logic (`excel_build.py`) with a declarative model: rules are written as constraints, the solver finds a valid roster, and a pure-Python verifier re-checks every constraint over the output.

`cpsat/CPSAT_DESIGN.md` is the authoritative spec (sets, variables, all constraint groups, soft objective). `STATUS.md` tracks current solver health and planned migration. **Read both before making non-trivial changes** — the design doc maps each constraint to a numbered requirement (`5.1`–`5.15`), and section IDs are referenced in code comments and `Violation.rule` strings.

## Environment & commands

The project expects a conda env named `dsrt_roster` (Python 3.11, ortools, openpyxl). `requirements.txt` only pins openpyxl; ortools must be installed separately (`pip install ortools`).

```bash
conda activate dsrt_roster

# Single day — fast (~90–150s), use for debugging
python -m cpsat.dsrt_solver solve mon_thu      # or: friday | saturday | sunday

# Full week solve + audit (currently times out — see "Known issue" below)
python -m cpsat.verifier

# Diagnose infeasibility on one day (runs the model 10× with one constraint group skipped each time)
python -c "from cpsat.verifier import diagnose_infeasibility; diagnose_infeasibility('mon_thu')"

# Sanity-check the roster data file
python -m cpsat.staff_data
python -m cpsat.wave_data
```

There is no test suite — `verifier.audit()` IS the executable specification. A roster is valid iff `audit()` returns `[]`.

## Architecture

```
inputs (config.py + cpsat/staff_data.py + cpsat/wave_data.py)
        │
        ▼
cpsat/dsrt_solver.py    DayModel builds CP-SAT vars + constraints; solve_day() / solve_week()
        │
        ▼
list[Assignment]        (day_key, slot, wallclock, person_id, station)
        │
        ▼
cpsat/verifier.py       audit() pure-Python re-check; diagnose_infeasibility() conflict finder
```

`render_excel.py` and `render_ics.py` are listed in CPSAT_DESIGN.md §7 but not yet written — they're the next deliverable after `solve_week()` becomes reliable.

### Variable layout in the solver

`DayModel` (in `cpsat/dsrt_solver.py`) creates one Boolean per `(person, slot, code)` tuple, where `code ∈ ALL_CODES = LG_STATIONS + ACTIVITIES`. Auxiliary `working[(p.id, t)]` is `1 - x[(p.id, t, "OFF")]`. Variable names are prefixed with the day key (e.g. `mon_thu.x[OPS_MGR,0,CTR]`) so a single shared `CpModel` can hold all four day-types simultaneously — that's how `solve_week()` enforces weekly hour constraints jointly.

Each constraint group is a separate method on `DayModel` (`add_station_coverage`, `add_breaks`, `add_lesson_coverage`, …). `build(skip_groups=...)` lets `diagnose_infeasibility` toggle groups individually. **When adding a new constraint, register it in both `build()` AND in `_DIAG_GROUPS`/`_REMEDIES` in `verifier.py`** so the diagnosis tool stays accurate.

### Day-key system (and why it's planned for replacement)

The codebase uses four hard-coded day-keys: `mon_thu`, `friday`, `saturday`, `sunday`. `mon_thu` represents one schedule applied four times per week, which is encoded as `DAY_WEIGHT = {"mon_thu": 4, ...}` in both `dsrt_solver.solve_week()` and `verifier._check_weekly_hours()`. **These two weight dicts must stay in sync.**

The named-key structure is being replaced with generic operating-day templates (parameterised by shift length and headcount ratios) — see STATUS.md "Planned architectural changes" for the full migration plan and which fields in each file change. Don't add new code that hardcodes the named keys further; prefer iterating over `op_config.HOURS.keys()`.

### Time grid

All times in the model are 30-min slot indices, where `slot 0 = park_open`. Use `slot_to_wallclock(spec, t)` and `wallclock_to_slot(spec, "HH:MM")` to convert; never hand-roll the arithmetic. `is_operating_slot()` gates coverage constraints to the wave window (between `first_wave` and `last_wave_end`), so pre-open setup and post-close cleanup don't require 8 LGs.

## Known issue: joint weekly solve times out

`solve_week()` is structured as a 3-phase warm-start (per-day solve → hints → joint feasibility solve), but currently returns UNKNOWN after 600–1200s. Root cause: FT staff have `weekly_hours_min == weekly_hours_max == 40` (hard equality), creating tight cross-day coupling. Things already tried are listed in STATUS.md "What was tried"; the planned fix is to widen FT to a range (38–42) once the day-template migration lands. Do not waste time on warm-start tuning — the fix is structural.

## Editing inputs

- **Operating hours / shift windows / break rules**: `config.py` (`HOURS`, `SHIFTS`, `BREAK_RULES`)
- **Staff roster** (add/remove people, change FT/PT hours, certifications, day availability): `cpsat/staff_data.py` — pure data, no logic
- **Wave calendar** (which slots are beginner-lesson, which are purple/Barrel Hour): `cpsat/wave_data.py` — `beginner_slots()` is the only thing the solver consumes
- **Constraints**: `cpsat/dsrt_solver.py` `DayModel.add_*` methods, mapped to design-doc section numbers
- **Audit checks**: `cpsat/verifier.py` `_check_*` functions — must mirror the solver's constraints; if you add/relax a solver constraint, update the matching check.

## Station / activity codes

Defined in `dsrt_solver.py`. Quick reference (full descriptions in README.md):

- **LG_STATIONS**: `CTR RR RS FLT LR LS FAR BR` — the 8 in-water positions; `RR`/`LR` are reef stations requiring `reef_eligible=True`.
- **ACTIVITIES**: `SUP PRIV_R PRIV_L GRP_LES LAND_LES MEAL REST OFF` — `PRIV_*`/`GRP_LES`/`LAND_LES` require `coach_eligible=True` (WSI cert).
- **Role pools** (`Person.role_pool`) gate codes further: `mgmt` → SUP only; `br` → BR only.

## Excel package context

The repo's original artifact is `DSRT_Operations_Package.xlsx` (a 10-sheet operational workbook described in detail in `README.md`). The CP-SAT solver's eventual `render_excel.py` is intended to regenerate sheets 4–8 (rotation template + four duty rosters) from solver output, leaving sheets 1–3, 9, 10 as static reference content.
