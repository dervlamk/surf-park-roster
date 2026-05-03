"""
Render staffing results as an xlsx workbook.

One sheet per day (shift plan + CA break notes) plus a "Weekly Summary"
sheet with headcount totals and dual-role savings across all days.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from solver.staffing import DayStaffingResult, ShiftBlock


_BOLD  = Font(bold=True)
_GRAY  = PatternFill("solid", fgColor="FFEEEEEE")
_BLUE  = PatternFill("solid", fgColor="FFE3F2FD")
_AMBER = PatternFill("solid", fgColor="FFFFF8E1")
_GREEN = PatternFill("solid", fgColor="FFE8F5E9")
_LILAC = PatternFill("solid", fgColor="FFF3E5F5")

_ROLE_FILL = {
    "Shore Guard":  _BLUE,
    "Reef Guard":   _AMBER,
    "Bay Coach":    _LILAC,
}


def _role_fill(role: str) -> PatternFill:
    for key, fill in _ROLE_FILL.items():
        if role.startswith(key):
            return fill
    return _GRAY


def _add_day_sheet(wb, result: DayStaffingResult) -> None:
    ws = wb.create_sheet(title=result.day)

    # ── Header ────────────────────────────────────────────────────────────────
    ws.append([f"{result.day}  •  {result.open_time} – {result.close_time}"])
    ws.cell(1, 1).font = Font(bold=True, size=13)

    ws.append([])  # spacer

    # ── Shift plan table ──────────────────────────────────────────────────────
    headers = ["Role", "Shift Start", "Shift End", "Workers", "Shift (hrs)", "CA Breaks"]
    ws.append(headers)
    for col, h in enumerate(headers, 1):
        c = ws.cell(ws.max_row, col)
        c.font = _BOLD
        c.fill = _GRAY

    for sb in result.shifts:
        ws.append([
            sb.role,
            sb.start,
            sb.end,
            sb.workers,
            sb.shift_hrs,
            sb.ca_note or "—",
        ])
        fill = _role_fill(sb.role)
        for col in range(1, 7):
            ws.cell(ws.max_row, col).fill = fill

    ws.append([])  # spacer

    # ── Headcount summary ─────────────────────────────────────────────────────
    ws.append(["HEADCOUNT SUMMARY"])
    ws.cell(ws.max_row, 1).font = _BOLD

    rows = [
        ("Shore Guard person-shifts",           result.shore_total),
        ("Reef Guard person-shifts",            result.reef_total),
        ("  of which: dual-role WSI required",  result.dual_role_total),
        ("Bay Coach person-shifts",             result.bay_coach_total),
        ("Adv. coaching via dual-role?",
         "Yes — no extra hire" if result.adv_coach_covered else "No — separate coach needed"),
        ("", ""),
        ("Min. unique persons (all PT)",        result.min_persons_all_pt),
        ("Min. unique persons (mix FT + PT)",   result.min_persons_with_ft),
        ("Adv. coach hires avoided (dual-role)", result.dual_role_saved),
    ]
    for label, value in rows:
        ws.append([label, value])
        if label.startswith("Min."):
            ws.cell(ws.max_row, 1).font = _BOLD
            ws.cell(ws.max_row, 2).font = _BOLD

    ws.append([])

    # ── Notes ─────────────────────────────────────────────────────────────────
    if result.notes:
        ws.append(["NOTES"])
        ws.cell(ws.max_row, 1).font = _BOLD
        for note in result.notes:
            ws.append(["", note])
            ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True)

    # ── Column widths ─────────────────────────────────────────────────────────
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 10
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 52


def _add_weekly_summary(wb, results: list[DayStaffingResult]) -> None:
    ws = wb.create_sheet(title="Weekly Summary", index=0)

    ws.append(["WEEKLY STAFFING SUMMARY"])
    ws.cell(1, 1).font = Font(bold=True, size=13)
    ws.append([])

    headers = [
        "Day", "Open", "Close",
        "Shore\nPerson-shifts", "Reef\nPerson-shifts", "Dual-role\n(WSI reef)",
        "Bay Coach\nPerson-shifts",
        "Min Persons\n(all PT)", "Min Persons\n(FT mix)",
        "AC Hires\nSaved",
    ]
    ws.append(headers)
    for col, h in enumerate(headers, 1):
        c = ws.cell(ws.max_row, col)
        c.font = _BOLD
        c.fill = _GRAY
        c.alignment = Alignment(wrap_text=True, horizontal="center")

    totals = [0] * 7
    for r in results:
        row = [
            r.day, r.open_time, r.close_time,
            r.shore_total, r.reef_total, r.dual_role_total,
            r.bay_coach_total,
            r.min_persons_all_pt, r.min_persons_with_ft,
            r.dual_role_saved,
        ]
        ws.append(row)
        for i, v in enumerate(row[3:], 0):
            if isinstance(v, int):
                totals[i] += v

    ws.append([])
    ws.append(["WEEK TOTALS", "", ""] + totals)
    for col in range(1, 11):
        ws.cell(ws.max_row, col).font = _BOLD

    # ── Coaching hire note ────────────────────────────────────────────────────
    ws.append([])
    ws.append(["KEY INSIGHT"])
    ws.cell(ws.max_row, 1).font = _BOLD
    ws.append([
        "",
        "Reef guards holding WSI certification cover advanced coaching (Malibu / "
        "Progressive Turns) without a separate hire. Bay coach slots can additionally "
        "be filled by LGs with WSI during lesson windows, reducing coach headcount further. "
        "Refer to each day's sheet for shift-level detail and CA break requirements."
    ])
    ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True)

    # ── Column widths ─────────────────────────────────────────────────────────
    widths = [14, 8, 8, 14, 14, 14, 14, 14, 14, 12]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[3].height = 30


def render_staffing_xlsx(
    results: list[DayStaffingResult],
    out_path: str | Path,
) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _add_weekly_summary(wb, results)
    for r in results:
        _add_day_sheet(wb, r)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
