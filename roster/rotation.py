"""
Build the duty-rotation table for one operating day.

Output is a list[Slot] where each Slot is a 30-min row carrying every
staff member's station for that slot.  No optimization, no breaks, no
hour totals — this is the constructive scaffold the verifier and
rendering layers consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config_v2 as cfg
from roster.wave_input import HourProgram, load_wave_program


# ── State labels for non-operating slots ────────────────────────────────────
PRE_OPEN     = "PRE-OPEN"     # before park gates open
PREP         = "PREP"         # park open, waves not yet running
OPERATIONAL  = "OPERATIONAL"  # waves running
POST_CLOSE   = "POST-CLOSE"   # waves done, park closing


# ── Per-slot data ────────────────────────────────────────────────────────────
@dataclass
class Slot:
    wallclock: str            # "HH:MM"
    state: str                # PRE_OPEN | PREP | OPERATIONAL | POST_CLOSE
    reef_wave: str | None     # current-hour reef wave, if operational
    bay_wave: str | None      # current-hour bay wave, if operational
    assignments: dict[str, str] = field(default_factory=dict)
    # assignments maps staff_id ("SG1", "RG2", "BC4", …) → station label.


# ── Staff ID layout (deterministic) ──────────────────────────────────────────
def staff_layout() -> dict[str, list[str]]:
    """Stable column order, used by both rotation and rendering."""
    shore_ids   = [f"SG{i+1}" for i in range(len(cfg.SHORE_ROTATION))]
    shore_float = [f"SF{i+1}" for i in range(cfg.SHORE_FLOATERS)]
    reef_ids    = [f"RG{i+1}" for i in range(len(cfg.REEF_ROTATION))]
    reef_float  = [f"RF{i+1}" for i in range(cfg.REEF_FLOATERS)]
    adv_ids     = [f"AC{i+1}" for i in range(cfg.ADV_COACH_POOL)]
    bay_ids     = [f"BC{i+1}" for i in range(cfg.BAY_COACH_POOL)]
    return {
        "Shore Guards":     shore_ids + shore_float,
        "Reef Guards":      reef_ids + reef_float,
        "Advanced Coaches": adv_ids,
        "Bay Coaches":      bay_ids,
    }


# ── Time helpers ─────────────────────────────────────────────────────────────
def _hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _min_to_hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


# ── Build ────────────────────────────────────────────────────────────────────
def build_rotation(
    open_time: str,
    close_time: str,
    program: dict[int, HourProgram],
) -> list[Slot]:
    """
    Construct the duty roster slot-by-slot.

    All three inputs are required.  ``open_time`` / ``close_time`` are
    "HH:MM" strings sourced from the input xlsx (see load_open_window).
    ``program`` is the per-hour wave map for the same day-column.

    Operating-window rules (parameters/operational_overview.txt §13–14):
      first_wave = open_time + 60 min
      last_wave  = close_time - 60 min  (last wave's hour starts 1h before close)
      operational window = [first_wave, last_wave + 60min)
      PREP slots       = [open_time, first_wave)
      POST_CLOSE slots = [last_wave + 60min, close_time)
    """
    open_min  = _hhmm_to_min(open_time)
    close_min = _hhmm_to_min(close_time)
    if close_min <= open_min:
        raise ValueError(f"close_time {close_time} must be after open_time {open_time}")
    first_wave_min = open_min + 60
    last_wave_min  = close_min - 60          # last wave's HOUR starts here
    op_end_min     = last_wave_min + 60      # operating ends 60 min after last wave starts

    layout = staff_layout()

    slots: list[Slot] = []
    t = open_min
    while t < close_min:
        wc = _min_to_hhmm(t)
        if t < first_wave_min:
            state = PREP
        elif t < op_end_min:
            state = OPERATIONAL
        else:
            state = POST_CLOSE

        cur_hour = t // 60
        prog = program.get(cur_hour) if state == OPERATIONAL else None
        reef = prog.reef_wave if prog else None
        bay  = prog.bay_wave  if prog else None

        slot = Slot(wallclock=wc, state=state, reef_wave=reef, bay_wave=bay)

        # Lifeguards: rotate each whole hour starting from first_wave.
        if state == OPERATIONAL:
            offset = (t - first_wave_min) // 60
        else:
            offset = 0

        # Shore rotation (3 stations + N floaters)
        for i, sid in enumerate([f"SG{i+1}" for i in range(len(cfg.SHORE_ROTATION))]):
            if state == OPERATIONAL:
                slot.assignments[sid] = cfg.SHORE_ROTATION[(offset + i) % len(cfg.SHORE_ROTATION)]
            elif state == PREP:
                slot.assignments[sid] = "Prep"
            else:
                slot.assignments[sid] = "OFF"
        for i in range(cfg.SHORE_FLOATERS):
            sid = f"SF{i+1}"
            slot.assignments[sid] = "Floater" if state == OPERATIONAL else (
                "Prep" if state == PREP else "OFF"
            )

        # Reef rotation (4 stations + N floaters)
        for i, sid in enumerate([f"RG{i+1}" for i in range(len(cfg.REEF_ROTATION))]):
            if state == OPERATIONAL:
                slot.assignments[sid] = cfg.REEF_ROTATION[(offset + i) % len(cfg.REEF_ROTATION)]
            elif state == PREP:
                slot.assignments[sid] = "Prep"
            else:
                slot.assignments[sid] = "OFF"
        for i in range(cfg.REEF_FLOATERS):
            sid = f"RF{i+1}"
            slot.assignments[sid] = "Floater" if state == OPERATIONAL else (
                "Prep" if state == PREP else "OFF"
            )

        # Coaches: default OFF, set below per wave-type rules.
        for i in range(cfg.ADV_COACH_POOL):
            slot.assignments[f"AC{i+1}"] = "OFF"
        for i in range(cfg.BAY_COACH_POOL):
            slot.assignments[f"BC{i+1}"] = "OFF"

        # Advanced coach: 1 per lagoon when reef wave is Progressive/Malibu.
        if state == OPERATIONAL and reef in cfg.PROGRESSIVE_REEF_WAVES:
            for i in range(cfg.ADV_COACH_POOL):
                slot.assignments[f"AC{i+1}"] = "Reef Coach"

        # Bay coaches: 6 in water during a Beginner Lesson hour
        # (handled in a 2nd pass below for the land-lesson 30-min lead-in).
        if state == OPERATIONAL and bay == cfg.BEGINNER_BAY_LABEL:
            for i in range(cfg.BAY_COACH_POOL):
                slot.assignments[f"BC{i+1}"] = "Bay Lesson"

        slots.append(slot)
        t += 30

    # ── 2nd pass: insert Land Lesson 30 min before each Beginner Lesson hour
    # (wave_type_rules.txt §7–§8: 30-min land + 60-min water = 90-min total).
    for j, s in enumerate(slots):
        # Beginner Lesson appears at the :00 slot of an operating hour.
        if (
            s.state == OPERATIONAL
            and s.bay_wave == cfg.BEGINNER_BAY_LABEL
            and s.wallclock.endswith(":00")
            and j > 0
        ):
            prev = slots[j - 1]
            for i in range(cfg.BAY_COACH_POOL):
                if prev.assignments[f"BC{i+1}"] == "OFF":
                    prev.assignments[f"BC{i+1}"] = "Land Lesson"

    # ── 3rd pass: per-employee start time
    # Every employee's shift begins exactly 30 min before their first real
    # duty (wave / lesson / coaching slot).  All earlier slots become OFF;
    # the slot 30 min before becomes "Prep".
    # Per parameters/lifeguard_rules.txt §11 and wave_type_rules.txt §15.
    _normalize_starts(slots)

    return slots


def _is_real_duty(label: str | None) -> bool:
    """A 'real duty' is anything other than off-duty / pre-shift prep."""
    return label not in (None, "", "OFF", "Prep")


def _normalize_starts(slots: list[Slot]) -> None:
    """For each staff id, set [0..first_duty-2] = OFF and slot first_duty-1 = Prep."""
    if not slots:
        return
    staff_ids = list(slots[0].assignments.keys())
    for sid in staff_ids:
        first = next(
            (i for i, s in enumerate(slots)
             if _is_real_duty(s.assignments.get(sid))),
            None,
        )
        if first is None:
            # Never on duty this day — clear any leftover "Prep".
            for s in slots:
                if s.assignments.get(sid) == "Prep":
                    s.assignments[sid] = "OFF"
            continue
        for i in range(first):
            slots[i].assignments[sid] = "Prep" if i == first - 1 else "OFF"


if __name__ == "__main__":
    # Smoke test: print the Monday rotation as plain text.
    from roster.wave_input import load_open_window

    day = "Monday"
    o, c = load_open_window(cfg.WAVE_INPUT_XLSX, cfg.WAVE_INPUT_SHEET, day)
    prog = load_wave_program(cfg.WAVE_INPUT_XLSX, cfg.WAVE_INPUT_SHEET, day)
    sl = build_rotation(o, c, prog)
    layout = staff_layout()
    flat_ids = [sid for ids in layout.values() for sid in ids]

    header = (
        f"{day} ({o}–{c})\n"
        "time   state         reef                        bay                         | "
        + " ".join(f"{sid:>4}" for sid in flat_ids)
    )
    print(header)
    for s in sl:
        reef = (s.reef_wave or "")[:26]
        bay  = (s.bay_wave  or "")[:26]
        cells = " ".join(f"{s.assignments.get(sid, '')[:4]:>4}" for sid in flat_ids)
        print(f"{s.wallclock}  {s.state:<12}  {reef:<26}  {bay:<26}  | {cells}")
