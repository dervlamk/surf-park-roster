"""
DSRT Surf Park — CP-SAT roster solver.

INPUTS (edit these to change the schedule):
    cpsat/staff_data.py   ROSTER — Person objects with hours, roles, certs
    cpsat/wave_data.py    CALENDAR — wave types and lesson slots per day
    config.py             HOURS (park open/close), SHIFTS, BREAK_RULES

OUTPUT:
    list[Assignment] — (day_key, slot, wallclock, person_id, station)
    Consumed by verifier.audit() and eventually render_excel / render_ics.

PUBLIC API:
    solve_day(day_key)  — solves one day in its own CpModel (fast, for debugging)
    solve_week()        — solves all four day-types in a single shared CpModel
                          so that weekly hour constraints are enforced globally

CURRENT STATUS (as of 2026-04-29):
    Per-day models (solve_day) are FEASIBLE in ~90-150s each.
    The joint weekly model (solve_week) returns UNKNOWN after 600s+; the
    weekly hour constraints (especially FT min=max=40h) create cross-day
    coupling that makes the combined model very hard to solve in finite time.

    The planned fix is to restructure inputs away from named day-keys
    (mon_thu / friday / saturday / sunday) toward generic "operating day
    templates" parameterised by shift length (12h, 14h, etc.) and FT/PT
    headcount ratios.  See STATUS.md for the full change plan.

TIME UNITS:
    All time values inside the model use 30-minute slots.
    "slot 0" = park_open time; "slot T-1" = 30 min before park_close.
    working[p, t] = 1 means person p is on duty (not OFF) in slot t.
    Weekly hours are tracked as weighted slots: DAY_WEIGHT * daily_slots,
    where DAY_WEIGHT[mon_thu]=4 accounts for four calendar days.
"""
from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from ortools.sat.python import cp_model
except ImportError:
    print("ortools not installed. Run: pip install ortools", file=sys.stderr)
    raise

from cpsat.staff_data import Person, ROSTER
from cpsat.wave_data import beginner_slots, waves_for
import config as op_config


# ── stations / activities ────────────────────────────────────────────────────
# Every person is assigned exactly one code per 30-min slot.
# LG_STATIONS: the 8 in-water guard positions (CTR=centre, RR/LR=reef right/left,
#   RS/LS=right/left shore, FLT=float, FAR=far end, BR=board rental beach)
# ACTIVITIES: non-station duties and breaks
#   SUP=supervisor desk, PRIV_R/L=private coaching right/left bay,
#   GRP_LES/LAND_LES=group/land lesson, MEAL=unpaid break, REST=paid break, OFF=not working
LG_STATIONS = ("CTR", "RR", "RS", "FLT", "LR", "LS", "FAR", "BR")
ACTIVITIES  = ("SUP", "PRIV_R", "PRIV_L", "GRP_LES", "LAND_LES", "MEAL", "REST", "OFF")
ALL_CODES   = LG_STATIONS + ACTIVITIES
CODE_IDX    = {c: i for i, c in enumerate(ALL_CODES)}

REEF_CODES  = {"RR", "LR"}          # require reef_eligible=True
COACH_CODES = {"PRIV_R", "PRIV_L", "GRP_LES", "LAND_LES"}  # require coach_eligible=True
LG_SET      = set(LG_STATIONS)


# ── day-level config ─────────────────────────────────────────────────────────
# DaySpec is derived from config.py at solve time; it is NOT edited directly.
# FUTURE CHANGE: replace the named day-key system (mon_thu/friday/saturday/sunday)
# with a generic DayTemplate parameterised by shift_hours and headcount, so the
# solver can be driven by "12-hour day" vs "14-hour day" without hard-coded keys.
@dataclass(frozen=True)
class DaySpec:
    key: str                                       # e.g. "mon_thu"
    park_open: tuple[int, int]                     # (hour, minute) 24h
    park_close: tuple[int, int]
    first_wave: tuple[int, int]                    # first operating slot start
    last_wave_end: tuple[int, int]                 # last operating slot end
    shifts: dict[str, tuple[int, int, int, int]]   # name → (sh,sm,eh,em)


def day_spec(key: str) -> DaySpec:
    """Build a DaySpec from config.py for the given day key."""
    h = op_config.HOURS[key]
    return DaySpec(
        key=key,
        park_open=h["park_open"],
        park_close=h["park_close"],
        first_wave=h["first_wave"],
        last_wave_end=h["last_wave_end"],
        shifts=op_config.SHIFTS[key],
    )


def slot_count(spec: DaySpec) -> int:
    """Total 30-min slots from park_open to park_close."""
    open_min  = spec.park_open[0]  * 60 + spec.park_open[1]
    close_min = spec.park_close[0] * 60 + spec.park_close[1]
    return (close_min - open_min) // 30


def slot_to_wallclock(spec: DaySpec, slot: int) -> str:
    """Convert a slot index to HH:MM string."""
    base = spec.park_open[0] * 60 + spec.park_open[1] + slot * 30
    h, m = divmod(base, 60)
    return f"{h:02d}:{m:02d}"


def wallclock_to_slot(spec: DaySpec, hh_mm: str) -> int:
    """Convert a HH:MM string to a slot index (may be negative or ≥T if out of range)."""
    h, m = map(int, hh_mm.split(":"))
    base = spec.park_open[0] * 60 + spec.park_open[1]
    return ((h * 60 + m) - base) // 30


def is_operating_slot(spec: DaySpec, slot: int) -> bool:
    """True if this slot falls within the first_wave → last_wave_end window.
    Coverage constraints (8 LGs + SUP) only apply to operating slots."""
    fw  = spec.first_wave[0] * 60 + spec.first_wave[1]
    lw  = spec.last_wave_end[0] * 60 + spec.last_wave_end[1]
    open_min = spec.park_open[0] * 60 + spec.park_open[1]
    slot_min = open_min + slot * 30
    return fw <= slot_min < lw


# ── output type ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Assignment:
    day_key: str
    slot: int
    wallclock: str
    person_id: str
    station: str

    def is_working(self) -> bool:
        return self.station != "OFF"


# ── per-day model ────────────────────────────────────────────────────────────
class DayModel:
    """
    Encapsulates all CP-SAT variables and constraints for one operating day.

    VARIABLE LAYOUT (per person p, per slot t):
        x[(p.id, t, code)]  — BoolVar, 1 iff person p is at station/activity
                               'code' during slot t.  Exactly one code is 1
                               per (person, slot) — see add_single_assignment().
        working[(p.id, t)]  — BoolVar, 1 iff person is NOT at "OFF".
                               Derived: working == 1 - x[p, t, "OFF"].

    SHARED MODEL:
        Pass shared_model=<existing CpModel> when building the joint weekly
        model in solve_week().  All variable names are prefixed with spec.key
        to keep them unique across days.  When shared_model is None (the
        default), a private CpModel is created — used for solve_day() and
        for the infeasibility diagnosis tests in verifier.py.
    """

    def __init__(
        self,
        spec: DaySpec,
        roster: Sequence[Person],
        shared_model: cp_model.CpModel | None = None,
    ):
        self.spec = spec
        self.day  = spec.key
        self.roster = [p for p in roster if p.can_work(spec.key)]
        self.T = slot_count(spec)
        self._owns_model = shared_model is None
        self.model = shared_model if shared_model is not None else cp_model.CpModel()
        d = self.day  # prefix for variable names → unique in shared model

        self.x: dict[tuple[str, int, str], cp_model.IntVar] = {}
        for p in self.roster:
            for t in range(self.T):
                for c in ALL_CODES:
                    self.x[(p.id, t, c)] = self.model.NewBoolVar(
                        f"{d}.x[{p.id},{t},{c}]"
                    )

        self.working: dict[tuple[str, int], cp_model.IntVar] = {}
        for p in self.roster:
            for t in range(self.T):
                w = self.model.NewBoolVar(f"{d}.w[{p.id},{t}]")
                self.working[(p.id, t)] = w
                self.model.Add(w + self.x[(p.id, t, "OFF")] == 1)

    # ── 5.1 single assignment ────────────────────────────────────────────────
    def add_single_assignment(self):
        """Each person is at exactly one station/activity per slot (partition constraint)."""
        for p in self.roster:
            for t in range(self.T):
                self.model.Add(
                    sum(self.x[(p.id, t, c)] for c in ALL_CODES) == 1
                )

    # ── 5.2 station coverage ─────────────────────────────────────────────────
    def add_station_coverage(self):
        """During operating hours, exactly 1 person must be at each of the 8 LG
        stations and exactly 1 at SUP.  Non-operating slots (pre-open/post-close)
        have no coverage requirement.
        NOTE: this is the tightest constraint — with a thin roster it directly
        limits how many people can be on MEAL/REST at any one time."""
        for t in range(self.T):
            if not is_operating_slot(self.spec, t):
                continue
            for s in LG_STATIONS:
                self.model.Add(
                    sum(self.x[(p.id, t, s)] for p in self.roster) == 1
                )
            self.model.Add(
                sum(self.x[(p.id, t, "SUP")] for p in self.roster) == 1
            )

    # ── 5.3 reef eligibility ─────────────────────────────────────────────────
    def add_reef_eligibility(self):
        """RR and LR stations require Person.reef_eligible=True (open-ocean cert)."""
        for p in self.roster:
            if p.reef_eligible:
                continue
            for t in range(self.T):
                for s in REEF_CODES:
                    self.model.Add(self.x[(p.id, t, s)] == 0)

    # ── 5.4 coach eligibility ────────────────────────────────────────────────
    def add_coach_eligibility(self):
        """Coaching activities require Person.coach_eligible=True (WSI + LG cert)."""
        for p in self.roster:
            if p.coach_eligible:
                continue
            for t in range(self.T):
                for s in COACH_CODES:
                    self.model.Add(self.x[(p.id, t, s)] == 0)

    # ── 5.6 role restrictions ────────────────────────────────────────────────
    def add_role_restrictions(self):
        """mgmt (OPS_MGR, ASST_SUP) may only be at SUP, MEAL, REST, or OFF.
        BR staff (BR_LEAD, BR_1, BR_2) may only be at BR, MEAL, REST, or OFF.
        These are role-contract constraints, not scheduling preferences."""
        for p in self.roster:
            if p.role_pool == "mgmt":
                for t in range(self.T):
                    for s in LG_STATIONS:
                        self.model.Add(self.x[(p.id, t, s)] == 0)
                    for s in COACH_CODES:
                        self.model.Add(self.x[(p.id, t, s)] == 0)
            elif p.role_pool == "br":
                for t in range(self.T):
                    for s in LG_STATIONS:
                        if s != "BR":
                            self.model.Add(self.x[(p.id, t, s)] == 0)
                    self.model.Add(self.x[(p.id, t, "SUP")] == 0)
                    for s in COACH_CODES:
                        self.model.Add(self.x[(p.id, t, s)] == 0)

    # ── 5.5 30-min rotation (no holdover at same LG station) ─────────────────
    def add_rotation_cadence(self):
        """No LG may stay at the same station for two consecutive slots.
        BR and mgmt are exempt: they are permanently assigned to one position
        (BR beach desk / SUP desk) and do not rotate through guard positions.
        Without this exemption, BR staff cannot accumulate enough working hours
        to meet their weekly minimum — their break slots would need to fill
        every alternate slot, making the model infeasible."""
        for p in self.roster:
            if p.role_pool in ("br", "mgmt"):
                continue
            for t in range(self.T - 1):
                for s in LG_STATIONS:
                    self.model.Add(
                        self.x[(p.id, t, s)] + self.x[(p.id, t + 1, s)] <= 1
                    )

    # ── 5.7 + 5.8 meal & rest breaks ─────────────────────────────────────────
    def add_breaks(self):
        """California Labor Code break requirements.
        MEAL (30 min unpaid): required if total working slots > 10 (> 5 h).
          Must occur within the first 10 working slots (i.e. by end of 5th hour).
        REST (10 min paid, counts as a working slot): 1 rest per ~4 h worked.
          1 REST if ≥ 7 slots (3.5 h); 2 REST if ≥ 13 slots (6.5 h).
        Reification pattern: 'works_long', 'works_8h', 'works_4h' are auxiliary
        BoolVars that are True iff the person crosses the relevant threshold.
        OnlyEnforceIf chains propagate the correct break counts conditionally."""
        d = self.day
        for p in self.roster:
            total_work = sum(self.working[(p.id, t)] for t in range(self.T))
            meal_count = sum(self.x[(p.id, t, "MEAL")] for t in range(self.T))
            rest_count = sum(self.x[(p.id, t, "REST")] for t in range(self.T))

            # Meal required iff shift > 5 hrs (> 10 slots)
            works_long = self.model.NewBoolVar(f"{d}.long[{p.id}]")
            self.model.Add(total_work >= 11).OnlyEnforceIf(works_long)
            self.model.Add(total_work <= 10).OnlyEnforceIf(works_long.Not())
            self.model.Add(meal_count == 1).OnlyEnforceIf(works_long)
            self.model.Add(meal_count == 0).OnlyEnforceIf(works_long.Not())

            # Rest: 2 if ≥ 13 slots (6.5 h), 1 if ≥ 7 slots (3.5 h), else 0
            works_8h = self.model.NewBoolVar(f"{d}.r8[{p.id}]")
            self.model.Add(total_work >= 13).OnlyEnforceIf(works_8h)
            self.model.Add(total_work <= 12).OnlyEnforceIf(works_8h.Not())
            works_4h = self.model.NewBoolVar(f"{d}.r4[{p.id}]")
            self.model.Add(total_work >= 7).OnlyEnforceIf(works_4h)
            self.model.Add(total_work <= 6).OnlyEnforceIf(works_4h.Not())
            self.model.Add(rest_count == 2).OnlyEnforceIf(works_8h)
            self.model.Add(rest_count == 1).OnlyEnforceIf(
                [works_8h.Not(), works_4h]
            )
            self.model.Add(rest_count == 0).OnlyEnforceIf(
                [works_8h.Not(), works_4h.Not()]
            )

            # 5.7 meal deadline: MEAL must fall within first 10 working slots.
            # Enforced per slot: if MEAL at slot t, at most 10 working slots
            # precede it (so meal_slot - shift_start <= 10).
            for t in range(self.T):
                if t == 0:
                    continue  # no slots before slot 0
                pre_work = sum(self.working[(p.id, t2)] for t2 in range(t))
                self.model.Add(pre_work <= 10).OnlyEnforceIf(
                    self.x[(p.id, t, "MEAL")]
                )

            # 5.8 rest cadence: in any 8-consecutive-slot window where both
            # endpoints are working, at least one MEAL or REST must appear.
            # This prevents gaps > 8 slots (= > 4 h) between breaks, matching
            # the verifier's bookend check.
            for t in range(self.T - 7):
                break_in_window = sum(
                    self.x[(p.id, t2, "MEAL")] + self.x[(p.id, t2, "REST")]
                    for t2 in range(t, t + 8)
                )
                self.model.Add(break_in_window >= 1).OnlyEnforceIf(
                    [self.working[(p.id, t)], self.working[(p.id, t + 7)]]
                )

    # ── 5.9 contiguous shift block ───────────────────────────────────────────
    def add_contiguous_shift(self):
        d = self.day
        for p in self.roster:
            transitions = []
            for t in range(self.T - 1):
                tr = self.model.NewBoolVar(f"{d}.tr[{p.id},{t}]")
                # tr = 1  iff  working[t]=0 and working[t+1]=1  (start of shift)
                self.model.Add(
                    self.working[(p.id, t + 1)] - self.working[(p.id, t)] == 1
                ).OnlyEnforceIf(tr)
                self.model.Add(
                    self.working[(p.id, t + 1)] - self.working[(p.id, t)] != 1
                ).OnlyEnforceIf(tr.Not())
                transitions.append(tr)
            # at most one 0→1 transition per day
            self.model.Add(sum(transitions) <= 1)

    # ── 5.10 beginner lessons (6 coaches in water) ───────────────────────────
    def add_lesson_coverage(self):
        coaches = [p for p in self.roster if p.coach_eligible]
        for w in beginner_slots(self.day):
            t = wallclock_to_slot(self.spec, w.wallclock)
            if not (0 <= t < self.T):
                continue
            # land at t-1
            if t - 1 >= 0:
                self.model.Add(
                    sum(self.x[(p.id, t - 1, "LAND_LES")] for p in coaches) == 6
                )
            # group at t and t+1
            self.model.Add(
                sum(self.x[(p.id, t, "GRP_LES")] for p in coaches) == 6
            )
            if t + 1 < self.T:
                self.model.Add(
                    sum(self.x[(p.id, t + 1, "GRP_LES")] for p in coaches) == 6
                )
            # continuity: land coaches follow into water
            if t - 1 >= 0:
                for p in coaches:
                    self.model.AddImplication(
                        self.x[(p.id, t - 1, "LAND_LES")],
                        self.x[(p.id, t,     "GRP_LES")],
                    )

        # defensive: raise if wave calendar itself has back-to-back beginner slots
        bslots = sorted(
            wallclock_to_slot(self.spec, w.wallclock)
            for w in beginner_slots(self.day)
        )
        for t1, t2 in zip(bslots, bslots[1:]):
            if 0 < t2 - t1 <= 2:
                raise ValueError(
                    f"{self.day}: beginner lessons too close: "
                    f"{slot_to_wallclock(self.spec, t1)} and "
                    f"{slot_to_wallclock(self.spec, t2)}"
                )

    # ── 5.11 private coaching windows ────────────────────────────────────────
    def add_private_coaching_windows(self):
        if self.day == "mon_thu":
            # Private coaching only after 17:00 on weekdays
            cutoff = wallclock_to_slot(self.spec, "17:00")
            for p in self.roster:
                for t in range(self.T):
                    if t < cutoff:
                        self.model.Add(self.x[(p.id, t, "PRIV_R")] == 0)
                        self.model.Add(self.x[(p.id, t, "PRIV_L")] == 0)
        # Fri/Sat/Sun: private coaching allowed all wave hours (no extra restriction)

        # At most 1 coach per side per slot on all days
        for t in range(self.T):
            self.model.Add(
                sum(self.x[(p.id, t, "PRIV_R")] for p in self.roster) <= 1
            )
            self.model.Add(
                sum(self.x[(p.id, t, "PRIV_L")] for p in self.roster) <= 1
            )

    # ── per-day hour cap (upper bound only; weekly floor handled jointly) ─────
    def add_daily_hour_caps(self, override_caps: dict[str, int] | None = None):
        max_slots = max(
            ((eh * 60 + em) - (sh * 60 + sm)) // 30
            for sh, sm, eh, em in self.spec.shifts.values()
        )
        for p in self.roster:
            cap = override_caps[p.id] if override_caps and p.id in override_caps else max_slots
            self.model.Add(
                sum(self.working[(p.id, t)] for t in range(self.T)) <= cap
            )

    # ── objective (only used when this model owns the CpModel) ───────────────
    def add_objective(self, *, maximize: bool = False):
        total_paid = sum(
            self.working[(p.id, t)]
            for p in self.roster
            for t in range(self.T)
        )
        if maximize:
            self.model.Maximize(total_paid)
        else:
            self.model.Minimize(total_paid)

    # ── assemble ─────────────────────────────────────────────────────────────
    def build(
        self,
        *,
        add_objective: bool = True,
        maximize: bool = False,
        daily_cap_override: dict[str, int] | None = None,
        skip_groups: frozenset[str] = frozenset(),
    ):
        """
        skip_groups: constraint group names to omit.  Used by diagnose_infeasibility
        to find which groups are necessary for infeasibility.  Valid names:
          coverage, reef_eligibility, coach_eligibility, role_restrictions,
          rotation_cadence, lesson_coverage, private_coaching,
          contiguous_shift, breaks, daily_caps
        """
        self.add_single_assignment()
        if "coverage"         not in skip_groups: self.add_station_coverage()
        if "reef_eligibility" not in skip_groups: self.add_reef_eligibility()
        if "coach_eligibility"not in skip_groups: self.add_coach_eligibility()
        if "role_restrictions"not in skip_groups: self.add_role_restrictions()
        if "rotation_cadence" not in skip_groups: self.add_rotation_cadence()
        if "lesson_coverage"  not in skip_groups: self.add_lesson_coverage()
        if "private_coaching" not in skip_groups: self.add_private_coaching_windows()
        if "contiguous_shift" not in skip_groups: self.add_contiguous_shift()
        if "breaks"           not in skip_groups: self.add_breaks()
        if "daily_caps"       not in skip_groups: self.add_daily_hour_caps(override_caps=daily_cap_override)
        if add_objective and self._owns_model:
            self.add_objective(maximize=maximize)


# ── extract assignments from a solved model ──────────────────────────────────
def _extract(
    solver: cp_model.CpSolver,
    day_models: dict[str, DayModel],
) -> list[Assignment]:
    out: list[Assignment] = []
    for dk, dm in day_models.items():
        spec = day_spec(dk)
        for p in dm.roster:
            for t in range(dm.T):
                for c in ALL_CODES:
                    if solver.Value(dm.x[(p.id, t, c)]) == 1:
                        out.append(
                            Assignment(
                                day_key=dk,
                                slot=t,
                                wallclock=slot_to_wallclock(spec, t),
                                person_id=p.id,
                                station=c,
                            )
                        )
                        break
    return out


# ── single-day solve (for CLI / debugging) ───────────────────────────────────
def solve_day(day_key: str, *, max_seconds: int = 60) -> list[Assignment]:
    spec = day_spec(day_key)
    dm = DayModel(spec, ROSTER)
    dm.build(add_objective=True)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.random_seed = 42
    status = solver.Solve(dm.model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"Solver returned {solver.StatusName(status)} for {day_key}."
        )

    return _extract(solver, {day_key: dm})


# ── joint weekly solve ───────────────────────────────────────────────────────
def solve_week(*, max_seconds: int = 1200) -> list[Assignment]:
    """
    Solve all four day-types in one shared CpModel so weekly hour constraints
    are enforced globally.

    WHY JOINT: sequential per-day solves fail because whoever is solved last
    runs out of weekly hour budget.  The joint model lets CP-SAT balance all
    days simultaneously.

    KNOWN CHALLENGE: the joint model returns UNKNOWN after 600-1200s.
    Root cause: FT staff have min==max==40h (hard equality), which creates
    tight cross-day coupling.  The 3-phase warm-start mitigates but does not
    fully solve this.  The planned architectural change (parameterise by shift
    length rather than named day-keys, and widen FT weekly hour bands) should
    make this tractable.  See STATUS.md.

    PHASE STRUCTURE:
      Phase 1: solve each day independently with proportional daily caps to
               produce warm-start hints that are close to the weekly target.
      Phase 2: build the joint model with all four days in one CpModel +
               hard weekly hour constraints.
      Phase 3: solve the joint model (feasibility only, no objective).
    """
    DAY_KEYS   = ("mon_thu", "friday", "saturday", "sunday")
    DAY_WEIGHT = {"mon_thu": 4, "friday": 1, "saturday": 1, "sunday": 1}

    # ── Phase 1: per-day warm-start with proportional daily caps ─────────────
    # Solve each day independently to collect assignment hints.
    # Caps are set proportionally to each person's weekly budget so that the
    # hints are already close to what the joint model needs — rather than the
    # uncapped maximize solutions that overshoot the weekly hour limits.
    per_day_budget = max(90, min(150, max_seconds // 6))
    # raw hints: (dk, pid, t, code) → 0 or 1
    raw_hints: dict[tuple, int] = {}
    print("Phase 1: warm-start solves …", flush=True)
    for dk in DAY_KEYS:
        # Proportional cap: each person's weekly max / total day-weight across all
        # days they work.  floor() keeps hints slightly under the weekly target so
        # the joint solver only needs to add slots, not remove them.
        prop_caps: dict[str, int] = {}
        for p in ROSTER:
            if not p.can_work(dk):
                continue
            total_w = sum(DAY_WEIGHT[d] for d in DAY_KEYS if p.can_work(d))
            if total_w == 0:
                continue
            max_slots_day = max(
                ((eh * 60 + em) - (sh * 60 + sm)) // 30
                for sh, sm, eh, em in day_spec(dk).shifts.values()
            )
            prop_caps[p.id] = min(
                max_slots_day,
                max(0, p.weekly_hours_max * 2 // total_w),
            )
        dm_warm = DayModel(day_spec(dk), ROSTER)
        dm_warm.build(add_objective=True, maximize=True, daily_cap_override=prop_caps)
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = per_day_budget
        s.parameters.num_search_workers  = 4
        s.parameters.random_seed         = 42
        status = s.Solve(dm_warm.model)
        print(f"  {dk}: {s.StatusName(status)} in {s.WallTime():.1f}s", flush=True)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            for p in dm_warm.roster:
                for t in range(dm_warm.T):
                    for c in ALL_CODES:
                        raw_hints[(dk, p.id, t, c)] = s.Value(dm_warm.x[(p.id, t, c)])

    # ── Phase 2: joint model with weekly constraints ──────────────────────────
    print("Phase 2: building joint model …", flush=True)
    shared = cp_model.CpModel()
    day_models: dict[str, DayModel] = {}
    for dk in DAY_KEYS:
        dm = DayModel(day_spec(dk), ROSTER, shared_model=shared)
        dm.build(add_objective=False)
        day_models[dk] = dm

    # Weekly hour constraints (hard)
    for p in ROSTER:
        total_w = shared.NewIntVar(0, p.weekly_hours_max * 2, f"wk[{p.id}]")
        shared.Add(
            total_w == sum(
                DAY_WEIGHT[dk] * sum(
                    day_models[dk].working[(p.id, t)]
                    for t in range(day_models[dk].T)
                )
                for dk in DAY_KEYS
                if p.can_work(dk)
            )
        )
        shared.Add(total_w >= p.weekly_hours_min * 2)
        shared.Add(total_w <= p.weekly_hours_max * 2)

    # No objective — pure feasibility.  The maximize objective was fighting the
    # weekly hour max constraints and making the joint solve much harder.

    # Apply warm-start hints to joint model variables
    n_hints = 0
    for dk, dm in day_models.items():
        for p in dm.roster:
            for t in range(dm.T):
                for c in ALL_CODES:
                    key = (dk, p.id, t, c)
                    if key in raw_hints:
                        shared.AddHint(dm.x[(p.id, t, c)], raw_hints[key])
                        n_hints += 1
    print(f"  {n_hints} hints applied", flush=True)

    joint_budget = max(300, max_seconds - len(DAY_KEYS) * per_day_budget)
    print(f"Phase 3: joint solve (budget={joint_budget}s) …", flush=True)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = joint_budget
    solver.parameters.num_search_workers  = 8
    solver.parameters.linearization_level = 0
    solver.parameters.random_seed         = 42
    status = solver.Solve(shared)
    print(f"  {solver.StatusName(status)} in {solver.WallTime():.1f}s", flush=True)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"Solver returned {solver.StatusName(status)} for week. "
            "Model is likely infeasible — check staffing numbers and constraints."
        )

    return _extract(solver, day_models)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("solve", "verify"):
        print("usage: python -m cpsat.dsrt_solver solve [day_key]")
        print("       python -m cpsat.dsrt_solver verify")
        return 1

    if argv[1] == "solve":
        day = argv[2] if len(argv) > 2 else "mon_thu"
        result = solve_day(day)
        print(f"Solved {day}: {len(result)} assignments")
        for a in sorted(result, key=lambda a: (a.slot, a.person_id)):
            if a.is_working():
                print(f"  {a.wallclock}  {a.person_id:<16} {a.station}")
        return 0

    if argv[1] == "verify":
        from cpsat.verifier import audit
        result = solve_week()
        violations = audit(result)
        if not violations:
            print("PASS — all constraints verified.")
            return 0
        print(f"FAIL — {len(violations)} violation(s):")
        for v in violations:
            print(f"  {v}")
        return 2

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
