"""
Minimum staffing solver — Layer 2.

Consumes list[Slot] from roster/rotation.py (the demand schedule) and finds
the fewest shift-workers needed to cover every 30-min slot, subject to:
  - A minimum shift length (LG_BASE_SHIFT_HRS from config)
  - California labor law break requirements
  - Cert constraints (reef_eligible for RG slots, coach_eligible for coach slots)
  - Dual-role optimisation: reef LGs with WSI coach cert cover AC slots for free

The solver works per-day (not jointly across the week).  Weekly hour totals
are checked as a post-step sum in __main__.py.

OUTPUT
  StaffingResult per day → rendered by solver/render_staffing.py into
  outputs/staffing_v0.xlsx with one sheet per day + a weekly summary.

ROLE TYPES
  shore      SG* + SF* prefix slots  (no surf cert needed)
  reef_only  RG* + RF* slots where no AC duty exists simultaneously
  reef_dual  RG* + RF* slots that also satisfy AC demand (needs WSI)
  bay_coach  BC* slots (WSI needed; can also be filled by LGs with WSI)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from collections import defaultdict

from ortools.sat.python import cp_model

from roster.rotation import Slot

import config_v2 as cfg


# ── Demand extraction ─────────────────────────────────────────────────────────

def _demand_vectors(slots: list[Slot]) -> dict[str, list[int]]:
    """
    For each role category return a list[int] of length len(slots) where
    entry t is the number of that-role workers needed at slot t.

    Workers are counted as "needed" whenever their assignment is not OFF.
    """
    n = len(slots)
    d: dict[str, list[int]] = {
        "shore":     [0] * n,
        "reef":      [0] * n,
        "adv_coach": [0] * n,
        "bay_coach": [0] * n,
    }
    for t, s in enumerate(slots):
        for sid, label in s.assignments.items():
            if label == "OFF":
                continue
            if sid.startswith(("SG", "SF")):
                d["shore"][t] += 1
            elif sid.startswith(("RG", "RF")):
                d["reef"][t] += 1
            elif sid.startswith("AC"):
                d["adv_coach"][t] += 1
            elif sid.startswith("BC"):
                d["bay_coach"][t] += 1
    return d


# ── Shift window generation ───────────────────────────────────────────────────

def _shift_windows(
    demand: list[int],
    base_slots: int,
    max_slots: int,
) -> list[tuple[int, int]]:
    """
    Generate feasible shift windows (start_slot, end_slot) where:
      - demand[t] > 0 for at least one t within the window
      - base_slots ≤ window_length ≤ max_slots
      - Windows are aligned to whole-hour boundaries (every 2 slots)

    Returns a de-duped sorted list of (start, end) tuples.
    """
    active = [t for t, v in enumerate(demand) if v > 0]
    if not active:
        return []
    first, last = active[0], active[-1]

    windows = set()
    for start in range(max(0, first - 1), last + 1, 2):   # step by 1 hour
        for length in range(base_slots, max_slots + 1, 2): # step by 1 hour
            end = start + length
            if end > len(demand):
                break
            # Only include windows that overlap at least one active slot.
            if any(demand[t] > 0 for t in range(start, end)):
                windows.add((start, end))
    return sorted(windows)


# ── CA break helpers ──────────────────────────────────────────────────────────

def _break_note(shift_slots: int) -> str | None:
    """Return a CA-law break note for a given shift length (in 30-min slots)."""
    hours = shift_slots * 0.5
    br = cfg.BREAK_RULES
    if hours > br["meal_trigger_hrs"]:
        rest_count = math.floor(hours / br["rest_interval_hrs"])
        return (
            f"{hours:.1f}h shift → 1 × {br['meal_duration_min']}-min unpaid meal "
            f"+ {rest_count} × {br['rest_duration_min']}-min paid rest"
        )
    if hours >= br["rest_interval_hrs"]:
        rest_count = math.floor(hours / br["rest_interval_hrs"])
        return f"{hours:.1f}h shift → {rest_count} × {br['rest_duration_min']}-min paid rest"
    return None


# ── Per-role CP-SAT shift-cover ───────────────────────────────────────────────

def _solve_cover(
    demand: list[int],
    windows: list[tuple[int, int]],
    label: str,
    timeout: int = 30,
) -> dict[tuple[int, int], int]:
    """
    Minimum-workers shift-cover for one role category.

    Returns {(start, end): n_workers} for windows with n_workers > 0.
    """
    if not windows or max(demand) == 0:
        return {}

    model = cp_model.CpModel()
    peak = max(demand)
    n = {w: model.NewIntVar(0, peak, f"{label}_{w[0]}_{w[1]}") for w in windows}

    for t, req in enumerate(demand):
        if req == 0:
            continue
        covering = [n[w] for w in windows if w[0] <= t < w[1]]
        if covering:
            model.Add(sum(covering) >= req)

    model.Minimize(sum(n.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {}
    return {w: solver.Value(n[w]) for w in windows if solver.Value(n[w]) > 0}


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class ShiftBlock:
    role: str
    start: str   # "HH:MM"
    end: str     # "HH:MM" exclusive
    workers: int
    shift_hrs: float
    ca_note: str | None


@dataclass
class DayStaffingResult:
    day: str
    open_time: str
    close_time: str
    shifts: list[ShiftBlock]
    # Headcount summaries
    shore_total: int        # total shore-LG person-shifts
    reef_total: int         # total reef-LG person-shifts (pure + dual)
    dual_role_total: int    # reef workers that also cover AC slots (subset of reef_total)
    bay_coach_total: int    # bay-coach person-shifts
    adv_coach_covered: bool # True = AC demand fully met by dual-role reef workers
    # Minimum unique persons (lower bounds)
    min_persons_all_pt: int     # every worker does exactly one shift
    min_persons_with_ft: int    # FT workers do two adjacent shifts (rough estimate)
    # Savings
    dual_role_saved: int    # advanced-coach hires avoided by dual-role reef workers
    notes: list[str] = field(default_factory=list)


# ── Main solver entry point ───────────────────────────────────────────────────

def solve_day_staffing(
    day: str,
    open_time: str,
    close_time: str,
    slots: list[Slot],
) -> DayStaffingResult:
    """
    Compute the minimum staffing plan for one operating day.

    Approach:
      1. Extract demand vectors (shore / reef / adv_coach / bay_coach) from slots.
      2. Solve shore and reef coverage independently via shift-cover CP-SAT.
      3. Determine how many reef workers need WSI cert to cover AC demand
         without additional hires (dual-role optimisation).
      4. Solve bay-coach coverage independently.
      5. Post-process: CA break notes, headcount bounds, savings report.
    """
    base_slots = int(cfg.LG_BASE_SHIFT_HRS * 2)  # 4.5 h → 9 slots
    max_slots  = int(cfg.LG_MAX_SHIFT_HRS  * 2)  # 8.5 h → 17 slots
    T = len(slots)

    demand = _demand_vectors(slots)

    def slot_to_hhmm(t: int) -> str:
        return slots[t].wallclock if 0 <= t < T else slots[-1].wallclock

    shifts_out: list[ShiftBlock] = []

    # ── Shore coverage ────────────────────────────────────────────────────────
    shore_wins = _shift_windows(demand["shore"], base_slots, max_slots)
    shore_soln = _solve_cover(demand["shore"], shore_wins, "shore")
    shore_total = 0
    for (s, e), w in shore_soln.items():
        length = e - s
        shifts_out.append(ShiftBlock(
            role="Shore Guard",
            start=slot_to_hhmm(s),
            end=slot_to_hhmm(min(e, T - 1)),
            workers=w,
            shift_hrs=length * 0.5,
            ca_note=_break_note(length),
        ))
        shore_total += w

    # ── Reef + dual-role (AC) coverage ───────────────────────────────────────
    # Solve reef coverage ignoring AC to get the baseline reef assignment.
    reef_wins = _shift_windows(demand["reef"], base_slots, max_slots)
    reef_soln = _solve_cover(demand["reef"], reef_wins, "reef")

    # Build a per-slot coverage map from the baseline reef solution so we can
    # check whether existing reef workers already satisfy AC demand.
    reef_coverage_at = [0] * T
    for (s, e), w in reef_soln.items():
        for t in range(s, e):
            reef_coverage_at[t] += w

    ac_peak = max(demand["adv_coach"]) if demand["adv_coach"] else 0

    # For each slot with AC demand: can existing reef workers cover reef + AC?
    # If reef_coverage_at[t] >= reef_demand[t] + ac_demand[t] for all t,
    # then no extra hires are needed — we just need ac_peak of those reef
    # workers to hold WSI certification (dual-role).
    needs_extra_hire = any(
        reef_coverage_at[t] < demand["reef"][t] + demand["adv_coach"][t]
        for t in range(T)
        if demand["adv_coach"][t] > 0
    )

    if needs_extra_hire:
        # Solve again with the combined demand to find extra workers needed.
        combined_demand = [
            demand["reef"][t] + demand["adv_coach"][t] for t in range(T)
        ]
        combined_soln = _solve_cover(combined_demand, reef_wins, "reef_combined")
        dual_role_cnt = sum(
            combined_soln.get(w, 0) - reef_soln.get(w, 0)
            for w in set(combined_soln) | set(reef_soln)
        )
        use_soln = combined_soln
    else:
        # Existing reef coverage suffices; number of those workers needing WSI
        # equals the peak concurrent AC demand.
        dual_role_cnt = ac_peak
        use_soln = reef_soln

    reef_total = 0
    for (s, e), w in use_soln.items():
        length = e - s
        shifts_out.append(ShiftBlock(
            role="Reef Guard" + (" (incl. dual-role WSI)" if needs_extra_hire else ""),
            start=slot_to_hhmm(s),
            end=slot_to_hhmm(min(e, T - 1)),
            workers=w,
            shift_hrs=length * 0.5,
            ca_note=_break_note(length),
        ))
        reef_total += w

    adv_coach_covered = ac_peak == 0 or not needs_extra_hire

    # ── Bay coach coverage ────────────────────────────────────────────────────
    bay_wins  = _shift_windows(demand["bay_coach"], base_slots, max_slots)
    bay_soln  = _solve_cover(demand["bay_coach"], bay_wins, "bay")
    bay_total = 0
    for (s, e), w in bay_soln.items():
        length = e - s
        shifts_out.append(ShiftBlock(
            role="Bay Coach",
            start=slot_to_hhmm(s),
            end=slot_to_hhmm(min(e, T - 1)),
            workers=w,
            shift_hrs=length * 0.5,
            ca_note=_break_note(length),
        ))
        bay_total += w

    # ── Headcount bounds ──────────────────────────────────────────────────────
    total_person_shifts = shore_total + reef_total + bay_total
    min_persons_all_pt  = total_person_shifts   # one shift each
    # FT workers can cover two adjacent shifts (≤ LG_MAX_SHIFT_HRS total).
    # Rough estimate: half the workers could be FT covering two shifts.
    min_persons_with_ft = math.ceil(total_person_shifts * 0.6)

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes: list[str] = []
    if dual_role_cnt > 0:
        notes.append(
            f"{dual_role_cnt} reef guard(s) per relevant shift must hold WSI "
            f"certification to cover advanced coaching — no extra hire needed."
        )
    if bay_total > 0:
        notes.append(
            f"Bay coach slots can be filled by LGs with WSI if their LG shift "
            f"and the lesson window overlap — reduces headcount further."
        )
    for sb in shifts_out:
        if sb.ca_note:
            notes.append(f"{sb.role} {sb.start}–{sb.end}: {sb.ca_note}")

    dual_role_saved = dual_role_cnt   # AC hires avoided

    return DayStaffingResult(
        day=day,
        open_time=open_time,
        close_time=close_time,
        shifts=sorted(shifts_out, key=lambda s: (s.role, s.start)),
        shore_total=shore_total,
        reef_total=reef_total,
        dual_role_total=dual_role_cnt,
        bay_coach_total=bay_total,
        adv_coach_covered=adv_coach_covered,
        min_persons_all_pt=min_persons_all_pt,
        min_persons_with_ft=min_persons_with_ft,
        dual_role_saved=dual_role_saved,
        notes=notes,
    )
