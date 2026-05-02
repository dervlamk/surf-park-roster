"""
Post-solve verifier and infeasibility diagnosis tool.

PUBLIC API:
  audit(assignments)               — re-check all constraints; returns list[Violation]
  diagnose_infeasibility(day_key)  — when a day is INFEASIBLE, identify which
                                     constraint groups are causing the conflict
                                     and print plain-English remedies

DESIGN INTENT:
  audit() deliberately does NOT use ortools — it is pure Python so that any
  roster (from CP-SAT, manual edit, or imported xlsx) can be checked.
  The verifier is the executable specification: a roster is "valid" iff
  audit() returns an empty list.

  diagnose_infeasibility() DOES import ortools (via dsrt_solver.DayModel) but
  only when called explicitly after a solve failure.  It runs the per-day model
  10 times with one constraint group removed each time, then reports which
  groups are necessary for the infeasibility.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from cpsat.staff_data import ROSTER, by_id, Person
from cpsat.wave_data import beginner_slots
import sys

from cpsat.dsrt_solver import (
    Assignment, day_spec, slot_count, slot_to_wallclock, wallclock_to_slot,
    is_operating_slot, LG_STATIONS, REEF_CODES, COACH_CODES,
)


@dataclass(frozen=True)
class Violation:
    rule: str          # short id of the rule, e.g. "5.2-coverage"
    day: str
    slot: int          # -1 for whole-day rules
    detail: str

    def __str__(self) -> str:
        loc = f"{self.day}" + (f" slot {self.slot}" if self.slot >= 0 else "")
        return f"[{self.rule}] {loc}: {self.detail}"


def audit(assignments: Iterable[Assignment]) -> list[Violation]:
    by_day_slot: dict[tuple[str, int], list[Assignment]] = defaultdict(list)
    by_person_day: dict[tuple[str, str], list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_day_slot[(a.day_key, a.slot)].append(a)
        by_person_day[(a.person_id, a.day_key)].append(a)

    violations: list[Violation] = []
    violations += _check_coverage(by_day_slot)
    violations += _check_reef(by_day_slot)
    violations += _check_coach(by_day_slot)
    violations += _check_rotation_cadence(by_person_day)
    violations += _check_meal_breaks(by_person_day)
    violations += _check_rest_breaks(by_person_day)
    violations += _check_lessons(by_day_slot)
    violations += _check_back_to_back_lessons()
    violations += _check_weekly_hours(assignments)
    return violations


# ─── 5.2 coverage ──────────────────────────────────────────────────────────
def _check_coverage(by_day_slot) -> list[Violation]:
    out = []
    for (day, slot), assigns in by_day_slot.items():
        spec = day_spec(day)
        if not is_operating_slot(spec, slot):
            continue
        # required: each LG_STATION exactly once, plus SUP exactly once
        required = list(LG_STATIONS) + ["SUP"]
        counts = Counter(a.station for a in assigns)
        for r in required:
            if counts.get(r, 0) != 1:
                out.append(Violation(
                    rule="5.2-coverage", day=day, slot=slot,
                    detail=f"station {r} has {counts.get(r, 0)} bodies (need 1)"
                ))
    return out


# ─── 5.3 reef ──────────────────────────────────────────────────────────────
def _check_reef(by_day_slot) -> list[Violation]:
    out = []
    for (day, slot), assigns in by_day_slot.items():
        for a in assigns:
            if a.station in REEF_CODES and not by_id(a.person_id).reef_eligible:
                out.append(Violation(
                    rule="5.3-reef", day=day, slot=slot,
                    detail=f"{a.person_id} at {a.station} but not reef_eligible"
                ))
    return out


# ─── 5.4 coach ─────────────────────────────────────────────────────────────
def _check_coach(by_day_slot) -> list[Violation]:
    out = []
    for (day, slot), assigns in by_day_slot.items():
        for a in assigns:
            if a.station in COACH_CODES and not by_id(a.person_id).coach_eligible:
                out.append(Violation(
                    rule="5.4-coach", day=day, slot=slot,
                    detail=f"{a.person_id} at {a.station} but not WSI-certified"
                ))
    return out


# ─── 5.5 rotation cadence (no 2 consecutive at same LG station) ───────────
def _check_rotation_cadence(by_person_day) -> list[Violation]:
    out = []
    for (pid, day), assigns in by_person_day.items():
        sorted_a = sorted(assigns, key=lambda a: a.slot)
        for prev, cur in zip(sorted_a, sorted_a[1:]):
            if cur.slot != prev.slot + 1:
                continue
            if cur.station == prev.station and cur.station in LG_STATIONS:
                out.append(Violation(
                    rule="5.5-rotation", day=day, slot=cur.slot,
                    detail=f"{pid} stayed at {cur.station} for 2 consecutive slots"
                ))
    return out


# ─── 5.7 meal break by end of 5th hour ─────────────────────────────────────
def _check_meal_breaks(by_person_day) -> list[Violation]:
    out = []
    for (pid, day), assigns in by_person_day.items():
        working = [a for a in assigns if a.is_working()]
        if not working:
            continue
        slots = sorted(a.slot for a in working)
        if len(slots) <= 10:  # ≤ 5 hrs: no meal required
            continue
        # find shift start = first working slot
        start = slots[0]
        meals = [a.slot for a in working if a.station == "MEAL"]
        if len(meals) == 0:
            out.append(Violation(
                rule="5.7-meal-missing", day=day, slot=-1,
                detail=f"{pid} works {len(slots)} slots but no MEAL break"
            ))
            continue
        meal_slot = meals[0]
        if meal_slot - start > 10:
            spec = day_spec(day)
            out.append(Violation(
                rule="5.7-meal-late", day=day, slot=meal_slot,
                detail=(
                    f"{pid} meal at {slot_to_wallclock(spec, meal_slot)} is "
                    f"{(meal_slot - start) * 0.5:.1f} hrs into shift "
                    f"(must be < 5.0)"
                )
            ))
    return out


# ─── 5.8 rest breaks every ≤ 3.5 hrs ───────────────────────────────────────
def _check_rest_breaks(by_person_day) -> list[Violation]:
    out = []
    for (pid, day), assigns in by_person_day.items():
        working = sorted([a for a in assigns if a.is_working()], key=lambda a: a.slot)
        if len(working) < 8:  # < 4 hrs, no rest required
            continue
        rest_slots = [a.slot for a in working if a.station == "REST"]
        # require: every contiguous 7-slot window contains a REST or MEAL
        events = sorted(rest_slots + [a.slot for a in working if a.station == "MEAL"])
        if not events:
            out.append(Violation(
                rule="5.8-rest-missing", day=day, slot=-1,
                detail=f"{pid} works {len(working)} slots with no REST or MEAL"
            ))
            continue
        # gap from shift start to first break
        start = working[0].slot
        end = working[-1].slot
        bookended = [start - 1] + events + [end + 1]
        for prev, cur in zip(bookended, bookended[1:]):
            if cur - prev > 8:  # > 4 hrs since last break
                spec = day_spec(day)
                out.append(Violation(
                    rule="5.8-rest-gap", day=day, slot=cur,
                    detail=(
                        f"{pid} has {(cur - prev) * 0.5:.1f}-hr gap with no "
                        f"break ending at {slot_to_wallclock(spec, cur)}"
                    )
                ))
    return out


# ─── 5.10 lessons (6 coaches in water) ─────────────────────────────────────
def _check_lessons(by_day_slot) -> list[Violation]:
    out = []
    for day in ("mon_thu", "friday", "saturday", "sunday"):
        spec = day_spec(day)
        for w in beginner_slots(day):
            t = wallclock_to_slot(spec, w.wallclock)
            if not (0 <= t < slot_count(spec)):
                continue

            # Land at t-1: 6 LAND_LES
            if t - 1 >= 0:
                land = sum(1 for a in by_day_slot.get((day, t - 1), [])
                           if a.station == "LAND_LES")
                if land != 6:
                    out.append(Violation(
                        rule="5.10-land", day=day, slot=t - 1,
                        detail=f"land lesson before {w.wallclock}: {land} coaches (need 6)"
                    ))

            # Group at t and t+1: 6 GRP_LES each
            for tt in (t, t + 1):
                if 0 <= tt < slot_count(spec):
                    grp = sum(1 for a in by_day_slot.get((day, tt), [])
                              if a.station == "GRP_LES")
                    if grp != 6:
                        out.append(Violation(
                            rule="5.10-group", day=day, slot=tt,
                            detail=f"group lesson at {slot_to_wallclock(spec, tt)}: "
                                   f"{grp} coaches (need 6)"
                        ))

            # Continuity: same 6 coaches across land + water
            land_set = {a.person_id for a in by_day_slot.get((day, t - 1), [])
                        if a.station == "LAND_LES"}
            water_set = {a.person_id for a in by_day_slot.get((day, t), [])
                         if a.station == "GRP_LES"}
            if land_set and water_set and land_set != water_set:
                out.append(Violation(
                    rule="5.10-continuity", day=day, slot=t,
                    detail=f"land coaches {land_set} != water coaches {water_set}"
                ))
    return out


# ─── 5.10 no back-to-back beginner lessons ────────────────────────────────
def _check_back_to_back_lessons() -> list[Violation]:
    out = []
    for day in ("mon_thu", "friday", "saturday", "sunday"):
        spec = day_spec(day)
        slots = sorted(wallclock_to_slot(spec, w.wallclock)
                       for w in beginner_slots(day))
        for a, b in zip(slots, slots[1:]):
            if b - a <= 2:
                out.append(Violation(
                    rule="5.10-b2b", day=day, slot=b,
                    detail=f"beginner lessons at {a*0.5:.1f}h and {b*0.5:.1f}h "
                           f"are too close (need ≥ 2 slots apart)"
                ))
    return out


# ─── 5.13 weekly hours ─────────────────────────────────────────────────────
def _check_weekly_hours(assignments: Iterable[Assignment]) -> list[Violation]:
    """Mon-Thu day-key counts as 4 days. Sum total working slots * 0.5 = hours."""
    DAY_WEIGHT = {"mon_thu": 4, "friday": 1, "saturday": 1, "sunday": 1}
    hours: dict[str, float] = defaultdict(float)
    for a in assignments:
        if a.is_working():
            hours[a.person_id] += 0.5 * DAY_WEIGHT[a.day_key]

    out = []
    for p in ROSTER:
        h = hours[p.id]
        if h < p.weekly_hours_min:
            out.append(Violation(
                rule="5.13-hours-low", day="week", slot=-1,
                detail=f"{p.id} weekly={h:.1f}h < min {p.weekly_hours_min}h"
            ))
        if h > p.weekly_hours_max:
            out.append(Violation(
                rule="5.13-hours-high", day="week", slot=-1,
                detail=f"{p.id} weekly={h:.1f}h > max {p.weekly_hours_max}h"
            ))
    return out


# ─── Infeasibility diagnosis ──────────────────────────────────────────────────
_DIAG_GROUPS = [
    ("coverage",         "Station coverage (8 LGs + SUP every operating slot)"),
    ("reef_eligibility", "Reef eligibility (only certified staff at LR/RR stations)"),
    ("coach_eligibility","Coach eligibility (only WSI-certified staff can instruct)"),
    ("role_restrictions","Role restrictions (mgmt → SUP only; BR staff → BR only)"),
    ("rotation_cadence", "Rotation cadence (no 2 consecutive slots at same LG station)"),
    ("lesson_coverage",  "Lesson coverage (6 coaches required per beginner lesson)"),
    ("private_coaching", "Private coaching windows (weekday PRIV only after 17:00)"),
    ("contiguous_shift", "Contiguous shift (one continuous work block per day)"),
    ("breaks",           "Break rules (CA law: meal after 5 h, rest every 4 h)"),
    ("daily_caps",       "Daily hour cap (max 8.5 h shift)"),
]

_REMEDIES = {
    "coverage":          "Hire 1–2 more lifeguards to maintain minimum on-station coverage.",
    "reef_eligibility":  "Add reef certification to more staff, or hire a reef-certified LG.",
    "coach_eligibility": "Hire 1 more WSI-certified coach, or reduce lesson frequency.",
    "role_restrictions": "Review role assignments — a mgmt person may need a secondary LG role.",
    "rotation_cadence":  "Roster is too thin for rotation — hire 1–2 more LGs.",
    "lesson_coverage":   "Hire 1 more coach or reduce concurrent lesson slots from 6 to 4.",
    "private_coaching":  "Private coaching window too narrow — relax the 17:00 weekday cutoff.",
    "contiguous_shift":  "Staff may need split shifts — consider relaxing contiguous-shift rule.",
    "breaks":            "Too few staff to cover CA-law break rotations — hire 1–2 more LGs.",
    "daily_caps":        "Extend allowed shift length, or add a part-time shift overlap.",
}


def diagnose_infeasibility(day_key: str, timeout_per_test: int = 45) -> None:
    """
    Identify which constraint groups are necessary for infeasibility on day_key.

    First confirms the per-day model is actually infeasible (not just slow).
    Then, for each group, builds the model with that group removed and checks
    whether the result becomes feasible.  Groups whose removal unlocks feasibility
    are necessary members of the conflict — printed with a remedy suggestion.
    """
    from cpsat.dsrt_solver import DayModel, ROSTER
    from ortools.sat.python import cp_model

    print(f"\n{'─' * 60}")
    print(f"Infeasibility diagnosis: {day_key}")

    # ── Step 0: confirm the full per-day model is actually infeasible ─────────
    dm_full = DayModel(day_spec(day_key), ROSTER)
    dm_full.build(add_objective=False)
    solver0 = cp_model.CpSolver()
    solver0.parameters.max_time_in_seconds = timeout_per_test * 2
    solver0.parameters.num_search_workers = 4
    status0 = solver0.Solve(dm_full.model)
    if status0 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"  Day {day_key} is feasible — no conflict to diagnose.")
        print(f"{'─' * 60}")
        return
    if status0 != cp_model.INFEASIBLE:
        print(f"  Full model returned {solver0.StatusName(status0)} — "
              f"increase timeout_per_test to confirm infeasibility.")
        print(f"{'─' * 60}")
        return

    print(f"Confirmed INFEASIBLE. Testing {len(_DIAG_GROUPS)} constraint groups "
          f"({timeout_per_test}s each) …\n")

    necessary: list[str] = []
    inconclusive: list[str] = []

    for group_key, group_desc in _DIAG_GROUPS:
        dm = DayModel(day_spec(day_key), ROSTER)
        dm.build(add_objective=False, skip_groups=frozenset({group_key}))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_per_test
        solver.parameters.num_search_workers = 4
        status = solver.Solve(dm.model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            necessary.append(group_key)
            print(f"  [CONFLICT]  {group_desc}")
        elif status == cp_model.INFEASIBLE:
            print(f"  [ok]        {group_desc}")
        else:
            inconclusive.append(group_key)
            print(f"  [?UNKNOWN]  {group_desc}")

    print()
    if not necessary:
        print("No single constraint group is solely responsible for infeasibility.")
        if inconclusive:
            print(f"  ({len(inconclusive)} groups were UNKNOWN — try a longer timeout.)")
        else:
            print("  The conflict arises from an interaction of multiple groups.")
            print("  Try removing pairs of groups to narrow it down.")
    else:
        print(f"Constraint group(s) necessary for infeasibility on {day_key}:")
        for g in necessary:
            desc = next(d for k, d in _DIAG_GROUPS if k == g)
            print(f"  • {desc}")
            print(f"    → {_REMEDIES[g]}")
    print(f"{'─' * 60}")


# ─── CLI ─────────────────────────────────────────────────────────────────────
_ALL_DAY_KEYS = ("mon_thu", "friday", "saturday", "sunday")

if __name__ == "__main__":
    from cpsat.dsrt_solver import solve_week

    try:
        result = solve_week()
    except RuntimeError as e:
        print(f"\nSolver failed: {e}")
        print("Running per-day infeasibility diagnosis …")
        for dk in _ALL_DAY_KEYS:
            diagnose_infeasibility(dk)
        sys.exit(1)

    vs = audit(result)
    if not vs:
        print(f"PASS — {len(result)} assignments, no violations")
    else:
        print(f"FAIL — {len(vs)} violations across {len(result)} assignments:")
        for v in vs[:50]:
            print(f"  {v}")
        if len(vs) > 50:
            print(f"  ... and {len(vs) - 50} more")
