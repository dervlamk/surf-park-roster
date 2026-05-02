"""
Wave calendar — sourced from DSRT_Surf_Proposal_April-2022.xlsx.

WAVE COLORS (used by downstream rendering; not consumed by the solver directly):
  Yellow  — beginner-eligible wave
  Purple  — specialty wave (Progressive Turns / Malibu / Barrel Hour)
             extra coach beneficial if >10 pax
  White   — advanced/intermediate only; no beginner lesson
  None    — pre-open / post-close (no wave running)

LESSON FLAGS (consumed by the solver):
  beginner_lesson=True  — solver schedules 6 coaches here (LAND_LES + GRP_LES)
  bay_lesson=True       — concurrent bay lesson (informational; not yet modelled)

This is the authoritative wave grid. The solver consumes beginner_slots() and
waves_for(); do not re-encode wave times inside dsrt_solver.py.

PLANNED CHANGE: when config.py moves to DAY_TEMPLATES, the wallclock times in
this file should become offsets from wave_open (first wave) so they are
template-agnostic rather than tied to specific start times.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


WaveColor = Literal["yellow", "purple", "white", "none"]
DayKey = Literal["mon_thu", "friday", "saturday", "sunday"]


@dataclass(frozen=True)
class WaveSlot:
    day_key: DayKey
    wallclock: str        # "HH:MM"
    wave_type: str        # e.g. "Intermediate Turns"
    color: WaveColor
    beginner_lesson: bool # set True for slots where you actively schedule a beginner lesson
    bay_lesson: bool      # set True for Progressive Turns slots (concurrent bay lesson)


# ─── REFERENCE CALENDAR (April 2022) ───────────────────────────────────────
# Hour-of-day → (wave_type, color) per (Mon-Thu, Fri, Sat, Sun)
# Source: DSRT_Surf_Proposal_April-2022.xlsx, columns B–H
#
# A more elaborate version would key by (day_key, hour). We keep it flat
# here for easy editing.

CALENDAR: tuple[WaveSlot, ...] = (
    # ─── Monday–Thursday ────────────────────────────────────────────────────
    WaveSlot("mon_thu", "08:00", "Intermediate Turns",     "yellow", False, False),
    WaveSlot("mon_thu", "09:00", "Advanced Turns",         "white",  False, False),
    WaveSlot("mon_thu", "10:00", "Intermediate Turns+",    "yellow", False, False),
    WaveSlot("mon_thu", "11:00", "Advanced Turns+",        "white",  False, False),
    WaveSlot("mon_thu", "12:00", "Intermediate Challenger","white",  False, False),
    WaveSlot("mon_thu", "13:00", "Advanced Challenger",    "white",  False, False),
    WaveSlot("mon_thu", "14:00", "Intermediate Turns",     "yellow", False, False),
    WaveSlot("mon_thu", "15:00", "Advanced Challenger",    "white",  False, False),
    WaveSlot("mon_thu", "16:00", "Intermediate Turns+",    "yellow", True,  False),  # ← beginner lesson here
    WaveSlot("mon_thu", "17:00", "Intermediate Challenger","white",  False, False),
    WaveSlot("mon_thu", "18:00", "Barrel Hour",            "purple", False, False),
    WaveSlot("mon_thu", "19:00", "Barrel Hour",            "purple", False, False),

    # ─── Friday ─────────────────────────────────────────────────────────────
    WaveSlot("friday", "08:00", "Intermediate Turns+",     "yellow", False, False),
    WaveSlot("friday", "09:00", "Advanced Turns",          "white",  False, False),
    WaveSlot("friday", "10:00", "Intermediate Turns+",     "yellow", False, False),
    WaveSlot("friday", "11:00", "Progressive Turns",       "purple", False, True),
    WaveSlot("friday", "12:00", "Advanced Turns+",         "white",  False, False),
    WaveSlot("friday", "13:00", "Intermediate Challenger", "white",  False, False),
    WaveSlot("friday", "14:00", "Malibu",                  "purple", False, False),
    WaveSlot("friday", "15:00", "Pro Challenger",          "white",  False, False),
    WaveSlot("friday", "16:00", "Intermediate Turns+",     "yellow", True,  False),  # ← beginner lesson
    WaveSlot("friday", "17:00", "Intermediate Turns+",     "yellow", False, False),
    WaveSlot("friday", "18:00", "Barrel Hour",             "purple", False, False),
    WaveSlot("friday", "19:00", "Barrel Hour",             "purple", False, False),
    WaveSlot("friday", "20:00", "Intermediate Challenger", "white",  False, False),

    # ─── Saturday ───────────────────────────────────────────────────────────
    WaveSlot("saturday", "07:00", "Intermediate Challenger","white",  False, False),
    WaveSlot("saturday", "08:00", "Advanced Turns+",        "white",  False, False),
    WaveSlot("saturday", "09:00", "Progressive Turns",      "purple", False, True),
    WaveSlot("saturday", "10:00", "Intermediate Turns+",    "yellow", True,  False),  # ← AM beginner lesson
    WaveSlot("saturday", "11:00", "Malibu",                 "purple", False, False),
    WaveSlot("saturday", "12:00", "Intermediate Challenger","white",  False, False),
    WaveSlot("saturday", "13:00", "Advanced Turns",         "white",  False, False),
    WaveSlot("saturday", "14:00", "Progressive Turns",      "purple", False, True),
    WaveSlot("saturday", "15:00", "Intermediate Challenger","white",  False, False),
    WaveSlot("saturday", "16:00", "Intermediate Turns+",    "yellow", True,  False),  # ← PM beginner lesson
    WaveSlot("saturday", "17:00", "Advanced Challenger",    "white",  False, False),
    WaveSlot("saturday", "18:00", "Barrel Hour",            "purple", False, False),
    WaveSlot("saturday", "19:00", "Barrel Hour",            "purple", False, False),
    WaveSlot("saturday", "20:00", "Pro Challenger",         "white",  False, False),

    # ─── Sunday ─────────────────────────────────────────────────────────────
    WaveSlot("sunday", "07:00", "Intermediate Turns+",     "yellow", False, False),
    WaveSlot("sunday", "08:00", "Pro Challenger",          "white",  False, False),
    WaveSlot("sunday", "09:00", "Progressive Turns",       "purple", False, True),
    WaveSlot("sunday", "10:00", "Intermediate Turns+",     "yellow", True,  False),  # ← AM beginner lesson
    WaveSlot("sunday", "11:00", "Malibu",                  "purple", False, False),
    WaveSlot("sunday", "12:00", "Intermediate Challenger", "white",  False, False),
    WaveSlot("sunday", "13:00", "Advanced Turns",          "white",  False, False),
    WaveSlot("sunday", "14:00", "Progressive Turns",       "purple", False, True),
    WaveSlot("sunday", "15:00", "Advanced Turns+",         "white",  False, False),
    WaveSlot("sunday", "16:00", "Intermediate Turns+",     "yellow", True,  False),  # ← PM beginner lesson
    WaveSlot("sunday", "17:00", "Advanced Challenger",     "white",  False, False),
    WaveSlot("sunday", "18:00", "Barrel Hour",             "purple", False, False),
    WaveSlot("sunday", "19:00", "Barrel Hour",             "purple", False, False),
)


def waves_for(day_key: DayKey) -> tuple[WaveSlot, ...]:
    return tuple(w for w in CALENDAR if w.day_key == day_key)


def beginner_slots(day_key: DayKey) -> tuple[WaveSlot, ...]:
    return tuple(w for w in CALENDAR if w.day_key == day_key and w.beginner_lesson)


def bay_slots(day_key: DayKey) -> tuple[WaveSlot, ...]:
    return tuple(w for w in CALENDAR if w.day_key == day_key and w.bay_lesson)


def purple_slots(day_key: DayKey) -> tuple[WaveSlot, ...]:
    return tuple(w for w in CALENDAR if w.day_key == day_key and w.color == "purple")


if __name__ == "__main__":
    for d in ("mon_thu", "friday", "saturday", "sunday"):
        ws = waves_for(d)
        bs = beginner_slots(d)
        ps = purple_slots(d)
        print(f"{d}: {len(ws)} waves, {len(bs)} beginner lessons, {len(ps)} purple slots")
        for b in bs:
            print(f"   beginner @ {b.wallclock}: {b.wave_type}")
