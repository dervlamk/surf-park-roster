"""
config_v2.py — minimal day-agnostic roster config.

This is the v2 / MVP config that replaces the named-day-key system in the
original config.py.  A "day" is now defined by a column in OPENING SCHEDULE
FINAL 1.0 — both the wave program AND the operating window (open / close)
come from that column, so changing the input xlsx changes the schedule
without touching this file.

The MVP draft (see roster/) does NOT model:
  - California labor law breaks
  - Shift lengths or employee headcount caps
  - Weekly hour totals

It DOES model, per parameters/lifeguard_rules.txt and wave_type_rules.txt:
  - 30-min slot grid from open_time to close_time
  - First wave 1h after open; last wave 1h before close (close = last_wave + 30min)
  - Shore-guard rotation: FA → LS → RS, advancing hourly, plus 1 floater
  - Reef-guard rotation: Rental → Tower → LR → RR, advancing hourly, plus 1 floater
  - Coach allocation derived from wave type at each operating hour
"""
from __future__ import annotations

# ── Days to build ────────────────────────────────────────────────────────────
# One rotation sheet is produced per entry.  Each name must match a column
# header in row 6 of the OPENING SCHEDULE FINAL 1.0 sheet.  The per-day
# operating window (open time / close time) is read from the "Open Time"
# summary row of that same sheet — see roster/wave_input.load_open_window().
DAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
)

# ── Input / output paths ──────────────────────────────────────────────────────
WAVE_INPUT_XLSX  = "parameters/spec_surf_park_roster_v0.xlsx"
WAVE_INPUT_SHEET = "OPENING SCHEDULE FINAL 1.0"
OUTPUT_XLSX      = "outputs/rotation_v0.xlsx"

# ── Rotation order (positions cycle in this sequence) ────────────────────────
# Per parameters/lifeguard_rules.txt §3 and §5.
SHORE_ROTATION = ("First Aid", "Left Shore", "Right Shore")
REEF_ROTATION  = ("Rental", "Tower", "Left Reef", "Right Reef")

# ── Headcount per shift (fixed for MVP — no optimization) ────────────────────
# Shore guards = len(SHORE_ROTATION) + 1 floater
# Reef guards  = len(REEF_ROTATION) + 1 floater
# Coaches: a pool large enough for the busiest slot — beginner lessons
# need 6 bay coaches; progressive waves add 1 advanced reef coach per
# lagoon side (modelled here as up to 2).
SHORE_FLOATERS = 1
REEF_FLOATERS  = 1
BAY_COACH_POOL = 6   # for Beginner Lesson (3 per lagoon side, 2 sides)
ADV_COACH_POOL = 2   # for Progressive / Malibu (1 per lagoon side)

# ── Wave-type → coach-rule mapping ───────────────────────────────────────────
# Per wave_type_rules.txt §5–§6 and operational_overview.txt §6:
#   Beginner Lesson in BAY column ⇒ 6 bay coaches (30-min land lesson + 60-min water).
#   Progressive reef wave (Malibu, Progressive Turns) ⇒ 1 advanced coach per
#     lagoon side IF >10 bookings (we always provision in MVP).
PROGRESSIVE_REEF_WAVES = frozenset({"Malibu", "Progressive Turns"})
BEGINNER_BAY_LABEL     = "Beginner Lesson"
