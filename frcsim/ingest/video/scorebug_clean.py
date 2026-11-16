"""Clean raw scorebug OCR readings into a match-time score timeline.

Rules used:
- The clock counts down 0:20 -> 0:00 in AUTO, then restarts at 2:20 for TELEOP.
- Alliance scores never decrease during a match; a reading lower than the last
  accepted value, or higher than the readings that follow it (an OCR spike), is rejected.
- Missing readings carry the last accepted value forward.
"""
import json
from statistics import median

AUTO_LEN, TELEOP_LEN = 20, 140


def match_time(rows):
    """Add phase and match_t (seconds since match start on the official clock)."""
    phase = "auto"
    prev = None
    for r in rows:
        c = r["clock"]
        if prev is not None and c is not None and c > prev + 5:
            phase = "teleop"  # clock jumped back up to 2:20
        r["phase"] = phase
        if c is None:
            r["match_t"] = None
        else:
            r["match_t"] = AUTO_LEN - c if phase == "auto" else AUTO_LEN + TELEOP_LEN - c
        if c is not None:
            prev = c
    return rows


def clean_series(values, lookahead=3):
    """Return (cleaned, rejected_count) for a non-decreasing score series."""
    out, last, rejected = [], None, 0
    for i, v in enumerate(values):
        ahead = [x for x in values[i + 1 : i + 1 + lookahead] if x is not None]
        ok = v is not None and (last is None or v >= last) and (not ahead or v <= median(ahead))
        if v is not None and not ok:
            rejected += 1
        if ok:
            last = v
        out.append(last)
    return out, rejected


def clean(rows):
    rows = match_time([dict(r) for r in rows])
    report = {}
    for side in ("blue", "red"):
        cleaned, rej = clean_series([r[side] for r in rows])
        report[side + "_rejected"] = rej
        report[side + "_missing"] = sum(r[side] is None for r in rows)
        for r, v in zip(rows, cleaned):
            r[side + "_raw"], r[side] = r[side], v
    return rows, report


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]
