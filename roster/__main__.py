"""
CLI:  python -m roster

For each day in cfg.DAYS, reads the wave program AND the operating window
from the input xlsx, builds the rotation, and writes a single output
workbook with one sheet per day.
"""
from __future__ import annotations

import sys

import config_v2 as cfg
from roster.rotation import build_rotation, staff_layout
from roster.wave_input import load_wave_program, load_open_window
from roster.render import render_xlsx


def main(argv: list[str]) -> int:
    print(f"Input: {cfg.WAVE_INPUT_XLSX}  ({cfg.WAVE_INPUT_SHEET})")

    slots_by_day: dict[str, list] = {}
    for day in cfg.DAYS:
        try:
            open_t, close_t = load_open_window(
                cfg.WAVE_INPUT_XLSX, cfg.WAVE_INPUT_SHEET, day
            )
        except Exception as e:
            print(f"  {day:10s}  SKIP  ({e})")
            continue

        program = load_wave_program(
            cfg.WAVE_INPUT_XLSX, cfg.WAVE_INPUT_SHEET, day
        )
        slots = build_rotation(open_t, close_t, program)
        op = sum(1 for s in slots if s.state == "OPERATIONAL")
        print(
            f"  {day:10s}  {open_t}–{close_t}  "
            f"{len(slots)} slots ({op} operational, "
            f"{len(program)} wave-hours in program)"
        )
        slots_by_day[day] = slots

    if not slots_by_day:
        print("No days produced any rotation; aborting.")
        return 1

    out = render_xlsx(slots_by_day, cfg.OUTPUT_XLSX)
    print(f"Wrote {out}  ({len(slots_by_day)} sheets)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
