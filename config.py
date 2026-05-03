"""
config_v2.py — day-agnostic roster and staffing config.

A "day" is defined by its column in OPENING SCHEDULE FINAL 1.0; both the
wave program and the operating window (open/close) are read from that sheet.
No calendar day names are hard-coded here.
"""
from __future__ import annotations

# ── Days to process ───────────────────────────────────────────────────────────
DAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
)

# ── Input / output paths ──────────────────────────────────────────────────────
WAVE_INPUT_XLSX  = "parameters/spec_surf_park_roster_v0.xlsx"
WAVE_INPUT_SHEET = "OPENING SCHEDULE FINAL 1.0"
ROTATION_XLSX    = "outputs/rotation_v0.xlsx"
STAFFING_XLSX    = "outputs/staffing_v0.xlsx"

# ── Rotation order ────────────────────────────────────────────────────────────
# Per parameters/lifeguard_rules.txt §3 and §5.
SHORE_ROTATION = ("First Aid", "Left Shore", "Right Shore")
REEF_ROTATION  = ("Rental", "Tower", "Left Reef", "Right Reef")
SHORE_FLOATERS = 1
REEF_FLOATERS  = 1

# ── Coach pool sizes (upper bound; solver finds the minimum needed) ───────────
BAY_COACH_POOL = 6   # 3 per lagoon side × 2 sides
ADV_COACH_POOL = 2   # 1 per lagoon side

# ── Wave-type → coach-requirement mapping ─────────────────────────────────────
PROGRESSIVE_REEF_WAVES = frozenset({"Malibu", "Progressive Turns"})
BEGINNER_BAY_LABEL     = "Beginner Lesson"

# ── Shift structure ───────────────────────────────────────────────────────────
# Per parameters/lifeguard_rules.txt §12-13:
#   base 4.5 h shifts; mid-shifts extended before opening/closing shifts.
LG_BASE_SHIFT_HRS = 4.5    # minimum shift length (lifeguard)
LG_MAX_SHIFT_HRS  = 8.5    # absolute upper bound for a single shift
SHIFT_OVERLAP_MIN = 30     # incoming shift arrives 30 min before prior shift ends

# ── California labor law break rules ─────────────────────────────────────────
# Per parameters/california_labor_laws.txt.
BREAK_RULES = {
    "meal_trigger_hrs":      5,    # meal required for shifts > 5 h
    "meal_duration_min":    30,    # unpaid
    "meal_deadline_hrs":     5,    # must start before end of 5th working hour
    "rest_interval_hrs":   3.5,    # one 10-min paid rest per this many hours
    "rest_duration_min":    10,    # paid; cannot be combined with meal
    "meal_waiver_max_hrs":   6,    # waiver allowed at 6 h but avoid (§6)
    "ft_trigger_hrs_week":  30,    # ≥ 30 h/week for 90 days → must offer FT
    "ft_hours_week":        40,    # standard FT weekly hours
}

# ── Hiring preferences ────────────────────────────────────────────────────────
# Per parameters/hiring_guidelines.txt.
HIRING = {
    "prefer_pt":          True,   # part-time preferred
    "coach_min_hrs_week": 24,     # minimum to justify relocation (§3)
    "casual_max_hrs_day": 8,      # on-call ceiling
}
