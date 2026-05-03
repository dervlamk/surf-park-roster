"""
Minimum staffing solver — Layer 2.

Consumes list[Slot] from roster/rotation.py and finds the fewest
shift-workers needed to cover every 30-min slot, subject to:
  - Maximum shift length (LG_MAX_SHIFT_HRS from config)
  - California labor law break requirements
  - Exactly 30-minute handover overlap between consecutive same-role shifts
  - 2 fixed Advanced Coach shifts covering the entire LG operational window

Advanced Coaches are separate headcount from Lifeguards.  A dual-role
person (reef-eligible + WSI) may cover an AC shift ADJACENT to — never
concurrent with — their LG shift.

The solver works per-day.  Output is DayStaffingResult, rendered by
solver/render_staffing.py into outputs/staffing_v0.xlsx.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from roster.rotation import Slot
import config_v2 as cfg


# ── Demand extraction ─────────────────────────────────────────────────────────

def _demand_vectors(slots: list[Slot]) -> dict[str, list[int]]:
    n = len(slots)
    d: dict[str, list[int]] = {
        "shore":     [0] * n,
        "reef":      [0] * n,
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
            elif sid.startswith("BC"):
                d["bay_coach"][t] += 1
    return d


# ── Shift window generation ───────────────────────────────────────────────────

def _shift_windows(demand: list[int], max_slots: int) -> list[tuple[int, int]]:
    """
    Generate feasible (start, end) windows where:
      - start and end are at 30-min granularity (1-slot steps)
      - 2 ≤ length ≤ max_slots (1-hour floor, configurable ceiling)
      - At least one demand[t] > 0 within the window
    Starting from the first active demand slot avoids phantom shifts
    beginning before the LG arrival time.
    """
    active = [t for t, v in enumerate(demand) if v > 0]
    if not active:
        return []
    first, last = active[0], active[-1]

    windows = set()
    for start in range(first, last + 1):           # any 30-min boundary
        for length in range(2, max_slots + 1):     # 1-slot (30-min) increments
            end = start + length
            if end > len(demand):
                break
            if any(demand[t] > 0 for t in range(start, end)):
                windows.add((start, end))
    return sorted(windows)


# ── CA break helpers ──────────────────────────────────────────────────────────

def _break_note(shift_slots: int) -> str | None:
    hours = shift_slots * 0.5
    br = cfg.BREAK_RULES
    if hours > br["meal_trigger_hrs"]:
        rest_count = math.floor(hours / br["rest_interval_hrs"])
        return (
            f"{hours:.1f}h → 1×{br['meal_duration_min']}-min meal (unpaid) "
            f"+ {rest_count}×{br['rest_duration_min']}-min rest (paid)"
        )
    if hours >= br["rest_interval_hrs"]:
        rest_count = math.floor(hours / br["rest_interval_hrs"])
        return f"{hours:.1f}h → {rest_count}×{br['rest_duration_min']}-min paid rest"
    return None


# ── Per-role CP-SAT shift-cover ───────────────────────────────────────────────

def _solve_cover(
    demand: list[int],
    windows: list[tuple[int, int]],
    label: str,
    timeout: int = 30,
) -> dict[tuple[int, int], int]:
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
    start: str          # "HH:MM" display
    end: str            # "HH:MM" display (exclusive = start of next slot after last covered)
    workers: int
    shift_hrs: float
    ca_note: str | None
    _start_slot: int = field(default=0, repr=False)
    _end_slot: int   = field(default=0, repr=False)


@dataclass
class PersonTypeBreakdown:
    """One row in the FT/PT breakdown table."""
    role: str
    shift_start: str
    shift_end: str
    shift_hrs: float
    n_workers: int
    is_ft_eligible: bool   # shift_hrs >= cfg.FT_SHIFT_THRESHOLD


@dataclass
class DayStaffingResult:
    day: str
    park_open_time: str      # from xlsx — park gates open
    park_close_time: str     # from xlsx — park gates close
    lg_start_time: str       # LG arrival (30 min before first wave)
    lg_end_time: str         # last wave end = when LG shifts stop
    shifts: list[ShiftBlock]
    shore_total: int
    reef_total: int
    ac_total: int            # always 2 (1 coach per shift × 2 shifts)
    bay_coach_total: int
    person_breakdown: list[PersonTypeBreakdown]
    min_persons_all_pt: int
    ft_eligible_workers: int
    pt_only_workers: int
    notes: list[str] = field(default_factory=list)


# ── Handover post-processing ──────────────────────────────────────────────────

def _apply_handover(blocks: list[ShiftBlock], slot_to_hhmm) -> None:
    """
    Enforce exactly 30-min handover between consecutive same-role shifts:
      shift_1.end = shift_2.start + 30 min

    If the solver produces more overlap (efficiency-driven), the outgoing
    shift is trimmed.  If shifts are exactly adjacent, the outgoing shift
    is extended by one slot.  Coverage is maintained in both cases because
    shift_2 always covers from shift_2.start onwards.
    """
    by_role: dict[str, list[ShiftBlock]] = {}
    for b in blocks:
        by_role.setdefault(b.role, []).append(b)

    for role_blocks in by_role.values():
        role_blocks.sort(key=lambda b: b._start_slot)
        for i in range(len(role_blocks) - 1):
            b1 = role_blocks[i]
            b2 = role_blocks[i + 1]
            handover_end = b2._start_slot + 1   # shift 1 ends exactly 1 slot past shift 2 start
            if b1._end_slot != handover_end:
                b1._end_slot = handover_end
                b1.end = slot_to_hhmm(handover_end)
                b1.shift_hrs = (handover_end - b1._start_slot) * 0.5
                b1.ca_note = _break_note(handover_end - b1._start_slot)


# ── Advanced coach fixed schedule ─────────────────────────────────────────────

def _ac_shifts(first_slot: int, last_slot: int, slot_to_hhmm) -> list[ShiftBlock]:
    """
    Two AC coach shifts covering [first_slot, last_slot] with 30-min handover.
    Split at the window midpoint, aligned to the nearest 1-hour boundary.
    """
    window = last_slot + 1 - first_slot
    mid = first_slot + window // 2
    # Align to 1-hour boundary: keep same parity as first_slot so the
    # boundary lands on a :00 or :30 mark consistently.
    if (mid - first_slot) % 2 != 0:
        mid += 1

    # Shift 1: [first_slot, mid+1)  — extended 1 slot past midpoint for handover
    s1_start, s1_end = first_slot, mid + 1
    # Shift 2: [mid, last_slot+1)
    s2_start, s2_end = mid, last_slot + 1

    def _block(s, e):
        return ShiftBlock(
            role="Advanced Coach",
            start=slot_to_hhmm(s),
            end=slot_to_hhmm(e),
            workers=1,
            shift_hrs=(e - s) * 0.5,
            ca_note=_break_note(e - s),
            _start_slot=s,
            _end_slot=e,
        )

    return [_block(s1_start, s1_end), _block(s2_start, s2_end)]


# ── Main solver entry point ───────────────────────────────────────────────────

def solve_day_staffing(
    day: str,
    open_time: str,
    close_time: str,
    slots: list[Slot],
) -> DayStaffingResult:
    max_slots = int(cfg.LG_MAX_SHIFT_HRS * 2)   # 7.5h → 15 slots
    T = len(slots)

    def slot_to_hhmm(t: int) -> str:
        return slots[t].wallclock if 0 <= t < T else close_time

    demand = _demand_vectors(slots)

    lg_slots = [t for t in range(T) if demand["shore"][t] + demand["reef"][t] > 0]
    if not lg_slots:
        return DayStaffingResult(
            day=day, park_open_time=open_time, park_close_time=close_time,
            lg_start_time=open_time, lg_end_time=close_time,
            shifts=[], shore_total=0, reef_total=0, ac_total=0,
            bay_coach_total=0, person_breakdown=[],
            min_persons_all_pt=0, ft_eligible_workers=0, pt_only_workers=0,
        )

    first_lg, last_lg = lg_slots[0], lg_slots[-1]
    lg_start_time = slot_to_hhmm(first_lg)
    lg_end_time   = slot_to_hhmm(last_lg + 1)

    shifts_out: list[ShiftBlock] = []

    # ── Shore ─────────────────────────────────────────────────────────────────
    shore_wins = _shift_windows(demand["shore"], max_slots)
    shore_soln = _solve_cover(demand["shore"], shore_wins, "shore")
    shore_total = 0
    for (s, e), w in shore_soln.items():
        shifts_out.append(ShiftBlock(
            role="Shore Guard", start=slot_to_hhmm(s), end=slot_to_hhmm(e),
            workers=w, shift_hrs=(e - s) * 0.5, ca_note=_break_note(e - s),
            _start_slot=s, _end_slot=e,
        ))
        shore_total += w

    # ── Reef ──────────────────────────────────────────────────────────────────
    reef_wins = _shift_windows(demand["reef"], max_slots)
    reef_soln = _solve_cover(demand["reef"], reef_wins, "reef")
    reef_total = 0
    for (s, e), w in reef_soln.items():
        shifts_out.append(ShiftBlock(
            role="Reef Guard", start=slot_to_hhmm(s), end=slot_to_hhmm(e),
            workers=w, shift_hrs=(e - s) * 0.5, ca_note=_break_note(e - s),
            _start_slot=s, _end_slot=e,
        ))
        reef_total += w

    # ── 30-min handover: enforce exactly shift_1.end = shift_2.start + 30 min
    _apply_handover(shifts_out, slot_to_hhmm)

    # ── Advanced Coach: 2 fixed shifts covering full LG window ────────────────
    ac_shifts = _ac_shifts(first_lg, last_lg, slot_to_hhmm)
    shifts_out.extend(ac_shifts)
    ac_total = 2

    # ── Bay coach ─────────────────────────────────────────────────────────────
    bay_wins = _shift_windows(demand["bay_coach"], max_slots)
    bay_soln = _solve_cover(demand["bay_coach"], bay_wins, "bay")
    bay_total = 0
    for (s, e), w in bay_soln.items():
        shifts_out.append(ShiftBlock(
            role="Bay Coach", start=slot_to_hhmm(s), end=slot_to_hhmm(e),
            workers=w, shift_hrs=(e - s) * 0.5, ca_note=_break_note(e - s),
            _start_slot=s, _end_slot=e,
        ))
        bay_total += w

    # ── Person-type breakdown ─────────────────────────────────────────────────
    ft_thresh = cfg.FT_SHIFT_THRESHOLD
    breakdown: list[PersonTypeBreakdown] = []
    for sb in shifts_out:
        breakdown.append(PersonTypeBreakdown(
            role=sb.role,
            shift_start=sb.start,
            shift_end=sb.end,
            shift_hrs=sb.shift_hrs,
            n_workers=sb.workers,
            is_ft_eligible=sb.shift_hrs >= ft_thresh,
        ))

    total_workers = shore_total + reef_total + ac_total + bay_total
    ft_workers    = sum(b.n_workers for b in breakdown if b.is_ft_eligible)
    pt_workers    = total_workers - ft_workers

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes: list[str] = [
        f"Park opens {open_time} · LG shifts start {lg_start_time} "
        f"(30 min before first wave) · Waves end / LG shifts stop {lg_end_time} · "
        f"Park closes {close_time}.",

        "Consecutive same-role shifts share a 30-min handover: the outgoing "
        "worker's shift ends 30 min after the incoming worker's shift starts.",

        "2 Advanced Coach shifts are fixed and cover the full LG window. "
        "Dual-role staff (reef-eligible + WSI) may fill an AC shift adjacent to "
        "— never concurrent with — their LG shift, reducing unique-person count.",
    ]
    for sb in shifts_out:
        if sb.ca_note:
            notes.append(f"{sb.role} {sb.start}–{sb.end}: {sb.ca_note}")

    return DayStaffingResult(
        day=day,
        park_open_time=open_time,
        park_close_time=close_time,
        lg_start_time=lg_start_time,
        lg_end_time=lg_end_time,
        shifts=sorted(shifts_out, key=lambda s: (s.role, s.start)),
        shore_total=shore_total,
        reef_total=reef_total,
        ac_total=ac_total,
        bay_coach_total=bay_total,
        person_breakdown=breakdown,
        min_persons_all_pt=total_workers,
        ft_eligible_workers=ft_workers,
        pt_only_workers=pt_workers,
        notes=notes,
    )
