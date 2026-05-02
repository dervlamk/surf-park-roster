# config.py — operating parameters consumed by cpsat/dsrt_solver.py
#
# PLANNED CHANGE: the named day-key structure (mon_thu / friday / saturday /
# sunday) will be replaced with a DAY_TEMPLATES list parameterised by shift
# length (e.g. "12h", "14h") so the solver is not tied to specific calendar days.
# Until then, edit HOURS and SHIFTS here to change park operating hours.

# ── OUTPUT ────────────────────────────────────────────────────────────────────
OUTPUT_PATH = "DSRT_Operations_Package.xlsx"

# ── PARK NAME / VERSION ───────────────────────────────────────────────────────
PARK_NAME    = "DSRT SURF PARK"
VERSION      = "1.0"
WAVE_BASIS   = "April 2022 Wave Schedule"

# ── OPERATING HOURS ───────────────────────────────────────────────────────────
# Format: (hour_24, minute)
HOURS = {
    "mon_thu": {"park_open": (7, 0),  "park_close": (20, 30), "first_wave": (8, 0),  "last_wave_end": (20, 0),  "sessions": 12},
    "friday":  {"park_open": (7, 0),  "park_close": (21, 30), "first_wave": (8, 0),  "last_wave_end": (21, 0),  "sessions": 13},
    "saturday":{"park_open": (6, 0),  "park_close": (21, 30), "first_wave": (7, 0),  "last_wave_end": (21, 0),  "sessions": 14},
    "sunday":  {"park_open": (6, 0),  "park_close": (20, 30), "first_wave": (7, 0),  "last_wave_end": (20, 0),  "sessions": 13},
}

# ── SHIFT WINDOWS ─────────────────────────────────────────────────────────────
# Each entry: (start_hour_24, start_min, end_hour_24, end_min)
SHIFTS = {
    "mon_thu": {
        "A": (7,  0, 15, 30),   # 7:00am – 3:30pm
        "B": (12, 0, 20, 30),   # noon   – 8:30pm
    },
    "friday": {
        "A": (7,  0, 15, 30),
        "B": (13, 0, 21, 30),
    },
    "saturday": {
        "A": (6,  0, 14, 30),   # 6:00am – 2:30pm
        "B": (9,  0, 17, 30),   # 9:00am – 5:30pm
        "C": (13, 0, 21, 30),   # 1:00pm – 9:30pm
    },
    "sunday": {
        "A": (6,  0, 14, 30),
        "B": (12, 0, 20, 30),   # noon – 8:30pm
    },
}

# ── CALIFORNIA LABOR LAW BREAK RULES ─────────────────────────────────────────
BREAK_RULES = {
    "meal_duration_min":      30,    # unpaid
    "meal_trigger_hrs":        5,    # meal required if shift > this many hours
    "meal_deadline_hrs":       5,    # must occur by end of 5th hour
    "rest_duration_min":      10,    # paid
    "rest_interval_hrs":     3.5,    # one rest break per this many hours worked
    "second_meal_trigger_hrs": 10,   # second meal required if shift > 10 hrs
}

# ── ROTATION SEQUENCE ─────────────────────────────────────────────────────────
# Order that guards cycle through stations. Change order to alter rotation.
ROTATION_SEQ = ["CTR", "RR", "RS", "FLT", "LR", "LS", "FAR", "BR"]

# Starting position (index into ROTATION_SEQ) for each guard slot.
# Guard-1 and Guard-2 are reef-qualified; they start at RR and LR.
GUARD_START_POS = [1, 4, 0, 2, 3, 5, 6, 7]

# ── STAFFING NUMBERS ──────────────────────────────────────────────────────────
HEADCOUNT = {
    "total_full_time":      8,
    "total_part_time":     16,
    "total_casual":         4,
    "total_roster":        28,
    "peak_on_site":        15,   # Saturday group lesson day
    "normal_operations":   10,
    "minimum_safe":         9,   # below this, close a station
}

# ── PAY RATES (informational — shown in Staffing sheet) ──────────────────────
PAY = {
    "ops_manager":        "$65,000–$80,000/yr",
    "asst_supervisor":    "$55,000–$68,000/yr",
    "head_coach":         "$55,000–$68,000/yr",
    "senior_coach":       "$48,000–$60,000/yr",
    "coach_lg":           "$22–$28/hr",
    "junior_coach":       "$18–$22/hr",
    "senior_lg":          "$42,000–$52,000/yr",
    "lifeguard_pt":       "$18–$24/hr",
    "casual_lg":          "$18–$21/hr",
    "br_lead":            "$20–$26/hr",
    "br_attendant":       "$17–$21/hr",
}
