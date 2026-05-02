"""
DSRT staff master roster — typed.

This is a pure-Python data file. Edit Person entries here; re-run the solver.
No business logic in this module — only data.

PLANNED CHANGE: the available_day_keys field (which references specific calendar
day names) will be replaced with available_template_ids once config.py switches
to the DAY_TEMPLATES structure.  FT/PT headcounts will also become configurable
parameters rather than hard-coded Person entries.

KEY FIELDS:
  role_pool       — "mgmt" | "coach" | "lg" | "br" | "casual"
                    Determines which stations the person can be assigned to.
  reef_eligible   — True only for staff with open-ocean (reef) certification.
  coach_eligible  — True only for WSI-certified surf instructors.
  weekly_hours_min/max — The solver treats these as hard bounds.
                    FT staff have min==max==40 (exact).  The joint weekly model
                    struggles with this equality; consider widening to a range
                    (e.g. 38–42) if the solver times out.  See STATUS.md.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


DayKey = Literal["mon_thu", "friday", "saturday", "sunday"]
RolePool = Literal["mgmt", "coach", "lg", "br", "casual"]
Contract = Literal["FT", "PT", "CASUAL"]

# Day-key expansion: mon_thu means the same template applies Mon, Tue, Wed, Thu
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_KEY_OF = {
    "mon": "mon_thu", "tue": "mon_thu", "wed": "mon_thu", "thu": "mon_thu",
    "fri": "friday", "sat": "saturday", "sun": "sunday",
}


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    role_pool: RolePool
    reef_eligible: bool
    coach_eligible: bool         # WSI cert + lifeguard cert
    contract: Contract
    weekly_hours_min: int
    weekly_hours_max: int
    available_day_keys: frozenset[DayKey] = field(
        default_factory=lambda: frozenset({"mon_thu", "friday", "saturday", "sunday"})
    )
    notes: str = ""

    def can_work(self, day_key: DayKey) -> bool:
        return day_key in self.available_day_keys


def _all_days() -> frozenset[DayKey]:
    return frozenset({"mon_thu", "friday", "saturday", "sunday"})


def _weekend_only() -> frozenset[DayKey]:
    return frozenset({"saturday", "sunday"})


# ─── MASTER ROSTER ──────────────────────────────────────────────────────────
# 28-person headcount per CLAUDE.md. Adjust freely; the solver will use whatever
# you put here. IDs must be unique. Names are placeholders until hiring.
ROSTER: tuple[Person, ...] = (
    # Management & supervision
    Person("OPS_MGR",   "[Operations Manager]",   "mgmt",  False, False, "FT", 40, 40,
           notes="Duty manager; covers SUP slot Mon-Fri days"),
    Person("ASST_SUP",  "[Assistant Supervisor]", "mgmt",  False, False, "FT", 40, 40,
           notes="Covers SUP slot when OPS_MGR off; flex 5-day week"),

    # Coaches (WSI + LG)
    Person("HEAD_COACH","[Head Surf Coach]",       "coach", True,  True,  "FT", 40, 40),
    Person("SR_COACH_1","[Sr. Coach A]",           "coach", True,  True,  "FT", 40, 40),
    Person("SR_COACH_2","[Sr. Coach B]",           "coach", True,  True,  "FT", 40, 40),
    Person("COACH_LG_1","[Coach/LG 1]",            "coach", True,  True,  "PT", 24, 32),
    Person("COACH_LG_2","[Coach/LG 2]",            "coach", True,  True,  "PT", 24, 32),
    Person("COACH_LG_3","[Coach/LG 3]",            "coach", False, True,  "PT", 16, 28),
    Person("COACH_LG_4","[Coach/LG 4]",            "coach", False, True,  "PT", 16, 28),
    Person("JR_COACH_1","[Jr. Coach 1]",           "coach", False, True,  "PT", 16, 24),
    Person("JR_COACH_2","[Jr. Coach 2]",           "coach", False, True,  "PT",  8, 20,
           available_day_keys=_weekend_only()),
    Person("JR_COACH_3","[Jr. Coach 3]",           "coach", False, True,  "PT",  8, 20,
           available_day_keys=_weekend_only()),

    # Lifeguards
    Person("SR_LG_1",   "[Sr. LG A]",              "lg",    True,  False, "FT", 40, 40),
    Person("SR_LG_2",   "[Sr. LG B]",              "lg",    True,  False, "FT", 40, 40),
    Person("SR_LG_3",   "[Sr. LG C]",              "lg",    True,  False, "FT", 40, 40),
    Person("LG_1",      "[LG 1]",                  "lg",    False, False, "PT", 24, 32),
    Person("LG_2",      "[LG 2]",                  "lg",    False, False, "PT", 24, 32),
    Person("LG_3",      "[LG 3]",                  "lg",    False, False, "PT", 20, 28),
    Person("LG_4",      "[LG 4]",                  "lg",    False, False, "PT", 20, 28),
    Person("LG_5",      "[LG 5]",                  "lg",    False, False, "PT", 16, 24),
    Person("LG_6",      "[LG 6]",                  "lg",    False, False, "PT", 16, 24),
    Person("LG_7",      "[LG 7]",                  "lg",    False, False, "PT", 12, 20,
           available_day_keys=_weekend_only()),
    Person("LG_8",      "[LG 8]",                  "lg",    False, False, "PT", 12, 20,
           available_day_keys=_weekend_only()),

    # Board rental
    Person("BR_LEAD",   "[BR Lead]",               "br",    False, False, "PT", 24, 36),
    Person("BR_1",      "[BR Staff 1]",            "br",    False, False, "PT", 16, 24),
    Person("BR_2",      "[BR Staff 2]",            "br",    False, False, "PT", 12, 20,
           available_day_keys=_weekend_only()),

    # Casual / on-call
    Person("CASUAL_LG_1","[Casual LG 1]",          "casual", False, False, "CASUAL", 0, 24),
    Person("CASUAL_LG_2","[Casual LG 2]",          "casual", False, False, "CASUAL", 0, 24),
    Person("CASUAL_LG_3","[Casual LG 3]",          "casual", True,  False, "CASUAL", 0, 24),
    Person("CASUAL_COACH","[Casual Coach]",         "casual", True,  True,  "CASUAL", 0, 24),
)


def by_id(pid: str) -> Person:
    for p in ROSTER:
        if p.id == pid:
            return p
    raise KeyError(pid)


def coaches() -> tuple[Person, ...]:
    return tuple(p for p in ROSTER if p.coach_eligible)


def reef_capable() -> tuple[Person, ...]:
    return tuple(p for p in ROSTER if p.reef_eligible)


def supervisors() -> tuple[Person, ...]:
    return tuple(p for p in ROSTER if p.role_pool == "mgmt")


if __name__ == "__main__":
    print(f"ROSTER size: {len(ROSTER)}")
    print(f"  coaches: {len(coaches())}")
    print(f"  reef-capable: {len(reef_capable())}")
    print(f"  supervisors: {len(supervisors())}")
