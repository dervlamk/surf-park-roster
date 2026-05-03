"""
Person dataclass and default roster for the staffing solver.

Replaces cpsat/staff_data.py with a day-agnostic model:
  - available_days uses weekday names ("Monday".."Sunday") instead of the
    retired named-day keys ("mon_thu", "friday", …)
  - No role_pool enum; eligibility flags (reef_eligible, coach_eligible)
    are sufficient for the solver to determine valid assignments.
  - weekly_hours_min / weekly_hours_max drive CA law FT-trigger checks and
    the solver's objective (minimise total paid hours / headcount).

Dual-role employees:
  reef_eligible=True  AND  coach_eligible=True  →  can cover both reef-LG
  rotation slots AND advanced coaching slots (progressive/Malibu waves),
  eliminating a separate advanced-coach hire.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Contract = Literal["FT", "PT", "CASUAL"]


def _all_days() -> frozenset[str]:
    return frozenset({"Monday", "Tuesday", "Wednesday", "Thursday",
                      "Friday", "Saturday", "Sunday"})


def _weekdays() -> frozenset[str]:
    return frozenset({"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"})


def _weekend() -> frozenset[str]:
    return frozenset({"Saturday", "Sunday"})


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    reef_eligible: bool     # open-water / surf cert → can work RG/RF stations
    coach_eligible: bool    # WSI cert → can teach AC or BC lesson slots
    contract: Contract
    weekly_hours_min: float
    weekly_hours_max: float
    available_days: frozenset[str] = field(default_factory=_all_days)
    notes: str = ""

    def can_work(self, day: str) -> bool:
        return day in self.available_days

    def is_dual_role(self) -> bool:
        """Reef-eligible AND coach-eligible → covers LG + coaching without extra hire."""
        return self.reef_eligible and self.coach_eligible


# ── Default roster ────────────────────────────────────────────────────────────
# 28 positions matching the original operational plan.
# Names are placeholders until hiring is confirmed.
# Adjust headcounts / contracts here; re-run the solver for updated output.
ROSTER: tuple[Person, ...] = (
    # ── Shore Lifeguards (no surf cert required) ──────────────────────────────
    Person("SLG_FT1", "[Shore LG — FT 1]",  False, False, "FT",  38, 40, _all_days()),
    Person("SLG_FT2", "[Shore LG — FT 2]",  False, False, "FT",  38, 40, _all_days()),
    Person("SLG_PT1", "[Shore LG — PT 1]",  False, False, "PT",  20, 32, _all_days()),
    Person("SLG_PT2", "[Shore LG — PT 2]",  False, False, "PT",  20, 32, _all_days()),
    Person("SLG_PT3", "[Shore LG — PT 3]",  False, False, "PT",  16, 28, _all_days()),
    Person("SLG_PT4", "[Shore LG — PT 4]",  False, False, "PT",  16, 28, _weekdays()),
    Person("SLG_PT5", "[Shore LG — PT 5]",  False, False, "PT",  12, 24, _weekend()),
    Person("SLG_PT6", "[Shore LG — PT 6]",  False, False, "PT",  12, 24, _weekend()),

    # ── Reef Lifeguards (surf cert; can also fill advanced coach slot) ─────────
    # reef_only=True, coach_eligible=False → pure LG
    Person("RLG_FT1", "[Reef LG — FT 1]",   True,  False, "FT",  38, 40, _all_days()),
    Person("RLG_FT2", "[Reef LG — FT 2]",   True,  False, "FT",  38, 40, _all_days()),
    Person("RLG_PT1", "[Reef LG — PT 1]",   True,  False, "PT",  20, 32, _all_days()),
    Person("RLG_PT2", "[Reef LG — PT 2]",   True,  False, "PT",  20, 32, _all_days()),
    Person("RLG_PT3", "[Reef LG — PT 3]",   True,  False, "PT",  16, 28, _weekdays()),
    Person("RLG_PT4", "[Reef LG — PT 4]",   True,  False, "PT",  12, 24, _weekend()),

    # ── Dual-role: Reef LG + WSI Coach (covers both RG and AC slots) ──────────
    Person("DLG_FT1", "[Dual LG/Coach — FT 1]", True, True, "FT", 38, 40, _all_days()),
    Person("DLG_FT2", "[Dual LG/Coach — FT 2]", True, True, "FT", 38, 40, _all_days()),
    Person("DLG_PT1", "[Dual LG/Coach — PT 1]", True, True, "PT", 24, 32, _all_days()),
    Person("DLG_PT2", "[Dual LG/Coach — PT 2]", True, True, "PT", 24, 32, _all_days()),

    # ── Bay Coaches (WSI only; not required to be reef-eligible) ──────────────
    # Relocating from coast → need ≥ 24 h/week (hiring_guidelines.txt §3).
    Person("BCH_FT1", "[Bay Coach — FT 1]",  False, True,  "FT",  38, 40, _all_days()),
    Person("BCH_FT2", "[Bay Coach — FT 2]",  False, True,  "FT",  38, 40, _all_days()),
    Person("BCH_PT1", "[Bay Coach — PT 1]",  False, True,  "PT",  24, 32, _all_days()),
    Person("BCH_PT2", "[Bay Coach — PT 2]",  False, True,  "PT",  24, 32, _all_days()),
    Person("BCH_PT3", "[Bay Coach — PT 3]",  False, True,  "PT",  24, 32, _weekdays()),
    Person("BCH_PT4", "[Bay Coach — PT 4]",  False, True,  "PT",  16, 24, _weekend()),
    Person("BCH_PT5", "[Bay Coach — PT 5]",  False, True,  "PT",  16, 24, _weekend()),

    # ── Casual / on-call ──────────────────────────────────────────────────────
    Person("CAS_LG1", "[Casual LG 1]",       False, False, "CASUAL", 0, 16, _all_days()),
    Person("CAS_LG2", "[Casual LG 2]",       True,  False, "CASUAL", 0, 16, _all_days()),
    Person("CAS_BCH", "[Casual Coach]",       False, True,  "CASUAL", 0, 16, _weekend()),
)


def reef_eligible_pool() -> tuple[Person, ...]:
    return tuple(p for p in ROSTER if p.reef_eligible)


def coach_eligible_pool() -> tuple[Person, ...]:
    return tuple(p for p in ROSTER if p.coach_eligible)


def dual_role_pool() -> tuple[Person, ...]:
    return tuple(p for p in ROSTER if p.is_dual_role())


def available_on(day: str) -> tuple[Person, ...]:
    return tuple(p for p in ROSTER if p.can_work(day))


if __name__ == "__main__":
    print(f"Total roster:   {len(ROSTER)}")
    print(f"  reef-eligible: {len(reef_eligible_pool())}")
    print(f"  coach-eligible:{len(coach_eligible_pool())}")
    print(f"  dual-role:     {len(dual_role_pool())}")
