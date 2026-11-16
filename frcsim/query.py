"""Answer "how many balls did each alliance score between t=a and t=b?" from a Timeline.

Two sources exist for every second of the match (see the README):

* scorebug points  - exact for an ACTIVE hub, but they also include tower/foul points, so
                     they are only trusted before END GAME, and they say nothing about a
                     hub that is inactive.
* video count      - sees every hub, but undercounts dense volleys.

The best estimate per second and alliance therefore is:

* hub active and not END GAME -> the scorebug points,
* otherwise                   -> the video count, scaled by `calibration`, the match-wide
                                 ratio scorebug points / video count measured on the
                                 seconds where the scorebug is trusted.

The scorebug shows a ball a second or two after it entered the hub, so the scorebug points
are first moved back by `lag` seconds, found per match by lining the scorebug up with the
video count. Without this, points would land in the wrong period near its boundaries.

All times are seconds since the start of AUTO (the official match clock; 0 to 160).
"""
import json
import math
from pathlib import Path

import numpy as np

from .ingest.video.fuel_per_second import hub_active, period_of
from .schema import Timeline

ALLIANCES = ("blue", "red")
MAX_LAG = 5            # seconds searched when aligning the scorebug with the video count
MAX_CALIBRATION = 3.0  # a sanity cap: a wild ratio means the video count is not usable


def load(path):
    return Timeline.model_validate(json.loads(Path(path).read_text()))


def _trusted(period, active):
    return active and period != "END GAME"


def _best_lag(counted, scored):
    """Seconds by which `scored` trails `counted` (best correlation, 0..MAX_LAG; 0 if unclear)."""
    best, best_r = 0, 0.0
    for lag in range(MAX_LAG + 1):
        x, y = counted[: len(counted) - lag], scored[lag:]
        if len(x) < 2 or x.std() == 0 or y.std() == 0:
            continue
        r = float(np.corrcoef(x, y)[0, 1])
        if r > best_r:
            best, best_r = lag, r
    return best


def analyze(timeline):
    """Per-second table plus the two numbers that tie the sources together.

    Returns {"seconds": [...], "calibration": float, "lag": int}. Each second holds
    t, period and, per alliance: scored, counted, active, trusted, estimate.
    """
    n = int(timeline.duration)  # events at or after the end (e.g. the last scorebug reading) fall in the last second
    raw = {a: {"scored": np.zeros(n), "counted": np.zeros(n)} for a in ALLIANCES}
    active = {a: [hub_active(period_of(s), a, timeline.auto_winner) for s in range(n)] for a in ALLIANCES}
    for e in timeline.events:
        if e.alliance not in ALLIANCES or e.kind not in ("fuel_scored", "fuel_entry"):
            continue
        s = min(n - 1, max(0, int(e.t)))
        raw[e.alliance]["scored" if e.kind == "fuel_scored" else "counted"][s] += e.count or 0
        if e.hub_active is not None:
            active[e.alliance][s] = e.hub_active

    # the lag is a property of the scorebug, so both alliances vote together
    lag = _best_lag(np.concatenate([raw[a]["counted"] for a in ALLIANCES]),
                    np.concatenate([raw[a]["scored"] for a in ALLIANCES]))
    secs = []
    for s in range(n):
        row = {"t": s, "period": period_of(s)}
        for a in ALLIANCES:
            row[a] = {"scored": int(raw[a]["scored"][s + lag]) if s + lag < n else 0,
                      "counted": int(raw[a]["counted"][s]), "active": active[a][s]}
            row[a]["trusted"] = _trusted(row["period"], row[a]["active"])
        secs.append(row)

    # one factor for both alliances: the video counter's blind spots do not depend on the colour
    pairs = [(s[a]["scored"], s[a]["counted"]) for s in secs for a in ALLIANCES if s[a]["trusted"]]
    sco, cnt = sum(p[0] for p in pairs), sum(p[1] for p in pairs)
    factor = min(MAX_CALIBRATION, max(1.0, sco / cnt)) if cnt else 1.0

    for s in secs:
        for a in ALLIANCES:
            c = s[a]
            c["estimate"] = float(c["scored"]) if c["trusted"] else c["counted"] * factor
    return {"seconds": secs, "calibration": round(factor, 2), "lag": lag}


def count_range(analysis, start, end):
    """Totals for the whole seconds s with start <= s < end."""
    lo, hi = max(0, math.floor(start)), math.ceil(end)
    sel = [s for s in analysis["seconds"] if lo <= s["t"] < hi]
    out = {"start": lo, "end": hi, "calibration": analysis["calibration"], "lag": analysis["lag"]}
    for a in ALLIANCES:
        out[a] = {
            "estimate": round(sum(s[a]["estimate"] for s in sel)),
            "scored": sum(s[a]["scored"] for s in sel),
            "counted": sum(s[a]["counted"] for s in sel),
            "seconds": len(sel),
            "active_seconds": sum(1 for s in sel if s[a]["active"]),
            "video_only_seconds": sum(1 for s in sel if not s[a]["trusted"]),
        }
    return out
