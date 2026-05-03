# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Two-layer roster solver for DSRT Surf Park:
- **Layer 1** (`roster/`): builds the duty-rotation schedule (which LG/coach is at which station each 30-min slot) from an input xlsx wave calendar
- **Layer 2** (`solver/`): finds the minimum number of persons to hire, accounting for CA labor law breaks and dual-role optimization (reef LGs with WSI cert cover advanced coaching without a separate hire)

## Environment & commands

Conda env `dsrt_roster` (Python 3.11, ortools, openpyxl). Install via `conda env create -f environment.yml`.

```bash
conda activate dsrt_roster

# Run both layers for all 7 days → outputs/rotation_v0.xlsx + outputs/staffing_v0.xlsx
python -m roster
```

There is no test suite. Run `python -m roster` and inspect the xlsx outputs.

## Architecture

```
parameters/spec_surf_park_roster_v0.xlsx  (wave calendar + open/close times per day)
        │
        ▼
roster/wave_input.py    load_open_window() / load_wave_program()  — reads xlsx
        │
        ▼
roster/rotation.py      build_rotation() → list[Slot]  — constructive, deterministic
        │
        ▼
roster/render.py        render_xlsx() → outputs/rotation_v0.xlsx  (one sheet per day)
        │
        ▼
solver/staffing.py      solve_day_staffing() → DayStaffingResult  — CP-SAT shift-cover
        │
        ▼
solver/render_staffing.py  render_staffing_xlsx() → outputs/staffing_v0.xlsx
```

`config_v2.py` holds rotation constants (station pools, wave-type mappings, shift length bounds, CA break rules). Operating hours and wave programs come entirely from the xlsx — nothing in config_v2.py encodes specific days.

## Layer 1 — Rotation

`build_rotation(open_time, close_time, program)` takes:
- `open_time` / `close_time`: `"HH:MM"` strings from the xlsx "Open Time" row
- `program`: `dict[int, HourProgram]` from `load_wave_program()`

Produces a `list[Slot]` on a 30-min grid with three states: `PREP` → `OPERATIONAL` → `POST_CLOSE`.

Employee start-time correction (`_normalize_starts`): each staff column gets its first real-duty slot set to "Prep", and all earlier slots set to "OFF", so no one is shown on the clock before their first actual assignment.

## Layer 2 — Staffing (CP-SAT shift-cover)

`solve_day_staffing()` extracts four demand vectors from the rotation (shore / reef / adv_coach / bay_coach), then solves a shift-cover integer program for each role independently via OR-Tools CP-SAT.

**Dual-role optimization**: checks whether existing baseline reef coverage already satisfies `reef_demand[t] + ac_demand[t]` at every slot. If yes → no extra hire; `dual_role_cnt = ac_peak` (those many existing reef workers just need WSI cert). If no → re-solves with combined demand; the extra workers are the dual-role hires.

Shift windows are aligned to 1-hour boundaries; minimum shift = `LG_BASE_SHIFT_HRS` (4.5 h), maximum = `LG_MAX_SHIFT_HRS` (8.5 h).

## Editing inputs

- **Operating hours / break rules / rotation pools**: `config_v2.py`
- **Staff roster** (persons, certs, contracts, availability): `solver/staff.py`
- **Wave calendar**: `parameters/spec_surf_park_roster_v0.xlsx` sheet `OPENING SCHEDULE FINAL 1.0`
- **Rotation logic**: `roster/rotation.py` `build_rotation()`
- **Staffing constraints**: `solver/staffing.py` `solve_day_staffing()`
