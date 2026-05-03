"""
CLI:  python -m roster

Layer 1 — Rotation:
  Builds the duty-rotation schedule for every day in cfg.DAYS from the
  input xlsx and writes outputs/rotation_v0.xlsx.

Layer 2 — Staffing:
  Feeds each day's rotation into the CP-SAT shift-cover solver to find the
  minimum number of workers (by role type and shift window) needed to staff
  the day, then writes outputs/staffing_v0.xlsx with per-day and weekly views.
"""
from __future__ import annotations

import sys

import config_v2 as cfg
from roster.rotation import build_rotation
from roster.wave_input import load_wave_program, load_open_window
from roster.render import render_xlsx
from solver.staffing import solve_day_staffing
from solver.render_staffing import render_staffing_xlsx


def main(argv: list[str]) -> int:
    print(f"Input: {cfg.WAVE_INPUT_XLSX}  ({cfg.WAVE_INPUT_SHEET})")

    rotation_by_day: dict[str, list] = {}
    staffing_results = []

    for day in cfg.DAYS:
        # ── Load operating window + wave program from xlsx ─────────────────────
        try:
            open_t, close_t = load_open_window(
                cfg.WAVE_INPUT_XLSX, cfg.WAVE_INPUT_SHEET, day
            )
        except Exception as e:
            print(f"  {day:10s}  SKIP  ({e})")
            continue

        program = load_wave_program(cfg.WAVE_INPUT_XLSX, cfg.WAVE_INPUT_SHEET, day)

        # ── Layer 1: rotation ─────────────────────────────────────────────────
        slots = build_rotation(open_t, close_t, program)
        op = sum(1 for s in slots if s.state == "OPERATIONAL")
        print(
            f"  {day:10s}  {open_t}–{close_t}  "
            f"{len(slots)} slots ({op} operational, "
            f"{len(program)} wave-hours)"
        )
        rotation_by_day[day] = slots

        # ── Layer 2: staffing ─────────────────────────────────────────────────
        result = solve_day_staffing(day, open_t, close_t, slots)
        staffing_results.append(result)
        dual_note = f"dual_role={result.dual_role_total}(WSI)  " if result.dual_role_total else ""
        print(
            f"  {'':10s}  shore={result.shore_total}  reef={result.reef_total}  "
            f"{dual_note}bay_coach={result.bay_coach_total}"
            f"  min_persons={result.min_persons_all_pt} (PT) "
            f"/ {result.min_persons_with_ft} (FT mix)"
        )

    if not rotation_by_day:
        print("No days built; aborting.")
        return 1

    # ── Write rotation xlsx ───────────────────────────────────────────────────
    rot_out = render_xlsx(rotation_by_day, cfg.ROTATION_XLSX)
    print(f"\nRotation → {rot_out}  ({len(rotation_by_day)} sheets)")

    # ── Write staffing xlsx ───────────────────────────────────────────────────
    stf_out = render_staffing_xlsx(staffing_results, cfg.STAFFING_XLSX)
    print(f"Staffing → {stf_out}  ({len(staffing_results)} days + weekly summary)")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
