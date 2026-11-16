"""Per-second FUEL table for each HUB, combining two sources.

- *_counted: balls the video counter saw entering the hub (hub_counter.py). Sees every
  hub, active or not, but undercounts dense volleys.
- *_scored: increase in the alliance score on the broadcast scorebug during that second
  (scorebug_clean.py). Exact for an ACTIVE hub (1 point per FUEL when there are no tower
  or foul points), blind to an inactive hub. Lags the real entry by the hub's processing time.

Hub active/inactive follows Table 6-3: the alliance that scored more FUEL in AUTO has its
hub inactive in SHIFTS 1 and 3.
"""
import csv
import json
import sys

PERIODS = [("AUTO", 0, 20), ("TRANSITION", 20, 30), ("SHIFT 1", 30, 55), ("SHIFT 2", 55, 80),
           ("SHIFT 3", 80, 105), ("SHIFT 4", 105, 130), ("END GAME", 130, 160)]


def period_of(match_t):
    for name, a, b in PERIODS:
        if a <= match_t < b:
            return name
    return "END GAME" if match_t >= 160 else "AUTO"


def hub_active(period, alliance, auto_winner):
    if period in ("AUTO", "TRANSITION", "END GAME"):
        return True
    off_first = alliance == auto_winner  # auto winner is inactive in SHIFT 1 and 3
    return (period in ("SHIFT 2", "SHIFT 4")) if off_first else (period in ("SHIFT 1", "SHIFT 3"))


def build(scorebug_rows, entries):
    by_t = {r["video_t"]: r for r in scorebug_rows}
    teleop_rows = [r for r in scorebug_rows if r["phase"] == "teleop"]
    auto_end = teleop_rows[0]  # scores when the teleop clock first shows 2:20 include the AUTO grace window
    auto_winner = "red" if (auto_end["red"] or 0) > (auto_end["blue"] or 0) else "blue"
    counted = {}
    for hub, evs in entries.items():
        for t, n in evs:
            counted.setdefault((int(t), hub), 0)
            counted[(int(t), hub)] += n
    first = int(scorebug_rows[0]["video_t"])
    last = int(scorebug_rows[-1]["video_t"])
    table = []
    for s in range(first, last):
        r0, r1 = by_t.get(float(s)), by_t.get(float(s + 1))
        if not r0 or not r1:
            continue
        # AUTO grace window: teleop clock frozen at 2:20 while auto fuel is still counted
        period = "AUTO" if (r0["phase"] == "teleop" and r0["clock"] == 140 and r0["video_t"] < auto_end["video_t"] + 4.5
                            and r0["blue"] <= auto_end["blue"]) else period_of(r0["match_t"])
        row = {"video_s": s, "clock": f"{r0['clock'] // 60}:{r0['clock'] % 60:02d}", "period": period}
        for a in ("blue", "red"):
            row[f"{a}_active"] = hub_active(period, a, auto_winner)
            row[f"{a}_counted"] = counted.get((s, a), 0)
            row[f"{a}_scored"] = (r1[a] or 0) - (r0[a] or 0)
        table.append(row)
    return table, auto_winner


if __name__ == "__main__":
    rows = json.load(open(sys.argv[1]))
    entries = json.load(open(sys.argv[2]))
    table, winner = build(rows, entries)
    with open(sys.argv[3], "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(f"auto winner: {winner}; wrote {len(table)} seconds to {sys.argv[3]}")
