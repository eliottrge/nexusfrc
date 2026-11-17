"""Robot tracks, shots, contacts and per-robot stats, from the stored detections.

Input: samples/<id>/robot_detections.json (frcsim/ingest/video/robots.py, the slow part),
the scorebug timeline (for match time), the per-second ball estimates (frcsim/query.py) and
the layout calibration (frcsim/field.py). All of this is cheap, so it is recomputed every
time a match is opened: changing a number in settings.py, the calibration, or which team
a robot is, takes effect on the next page load.

What is an estimate (and is labelled so in the UI):
* positions: a homography from one fixed camera, about +-0.5 m; robots hidden behind
  people or structures keep their last position and are drawn as "not seen".
* identity: robots are kept in 3 slots per alliance by nearest position; the team in each
  slot is a guess until a user sets it (robot_labels.json).
* shots: a robot inside its alliance zone and slower than SHOOT_MAX_SPEED is "shooting".
* balls in per robot: each second's alliance ball estimate is shared between the robots of
  that alliance that were shooting SHOT_FLIGHT s earlier. No source counts balls per robot.
* contacts: two robot centres closer than CONTACT_DIST for CONTACT_MIN s.
"""
import json
import math
from itertools import permutations
from pathlib import Path

from . import field, settings
from .ingest.video.fuel_per_second import PERIODS, period_of

ALLIANCES = ("blue", "red")
SLOTS = [f"{a}{i}" for a in ALLIANCES for i in (1, 2, 3)]
FAR = 1e9


# ---------------------------------------------------------------- time
def match_clock(clean_rows):
    """f(video_t) -> match time (s since AUTO start), interpolated between scorebug samples."""
    pts = [(r["video_t"], float(r["match_t"])) for r in clean_rows if r.get("match_t") is not None]

    def f(t):
        if not pts:
            return None
        if t <= pts[0][0]:
            return pts[0][1] - (pts[0][0] - t)
        for (ta, ma), (tb, mb) in zip(pts, pts[1:]):
            if ta <= t <= tb:
                # the clock stands still between AUTO and TELEOP: keep the earlier value there
                return ma + (t - ta) * (mb - ma) / (tb - ta) if mb - ma <= (tb - ta) + 1 else ma
        return pts[-1][1] + (t - pts[-1][0])
    return f


# ---------------------------------------------------------------- tracking
def _alliance(red, blue):
    if max(red, blue) < 0.015:
        return None
    return "red" if red > blue else "blue"


def _assign(slots, dets, gap_cost):
    """Best matching of detections to slots. slots: [(pos or None, max_jump)], dets: [pos].
    Returns {slot index: det index}. Uninitialised slots take any detection at gap_cost."""
    best, best_cost = {}, FAR
    n = len(slots)
    idx = list(range(len(dets))) + [None] * n
    for perm in set(permutations(idx, n)):
        cost, pairs = 0.0, {}
        for si, di in enumerate(perm):
            if di is None:
                continue
            pos, jump = slots[si]
            d = gap_cost if pos is None else field.distance(pos, dets[di])
            if pos is not None and d > jump:
                cost = FAR
                break
            cost += d - 10  # reward every match so that more matches always win
            pairs[si] = di
        if cost < best_cost:
            best, best_cost = pairs, cost
    return best


def track(samples, mapper, clock):
    """-> times [match_t], pos {slot: [(x, y, seen)]} with one entry per sample."""
    state = {s: {"pos": None, "t": None} for s in SLOTS}
    times, pos = [], {s: [] for s in SLOTS}
    for smp in samples:
        t = clock(smp["video_t"])
        if t is None:
            continue
        dets = {"blue": [], "red": [], None: []}
        for x0, y0, x1, y1, conf, red, blue in smp["robots"]:
            p = mapper.robot_position((x0, y0, x1, y1))
            if mapper.on_field(*p):  # small calibration errors: pull points just outside back onto the field
                p = (min(max(p[0], 0.0), settings.FIELD_LENGTH), min(max(p[1], 0.0), settings.FIELD_WIDTH))
                dets[_alliance(red, blue)].append(p)
        seen = {}
        for a in ALLIANCES:
            names = [f"{a}{i}" for i in (1, 2, 3)]
            slots = []
            for n in names:
                st = state[n]
                gap = 0 if st["t"] is None else max(0.0, t - st["t"])
                slots.append((st["pos"], settings.TRACK_MAX_JUMP + 4.0 * gap))
            for si, di in _assign(slots, dets[a], gap_cost=settings.TRACK_MAX_JUMP + 1).items():  # new slots only take leftovers
                seen[names[si]] = dets[a][di]
        # robots whose bumper colour was unclear go to the nearest free slot within reach
        for p in dets[None]:
            free = [(field.distance(state[s]["pos"], p), s) for s in SLOTS
                    if s not in seen and state[s]["pos"] is not None]
            free = [f for f in free if f[0] <= settings.TRACK_MAX_JUMP]
            if free:
                seen[min(free)[1]] = p
        times.append(t)
        for s in SLOTS:
            if s in seen:
                state[s] = {"pos": seen[s], "t": t}
                pos[s].append((*seen[s], True))
            else:
                last = state[s]["pos"]
                pos[s].append((*last, False) if last else (None, None, False))
    return times, pos


def _smooth(points, k):
    if k <= 1:
        return points
    out = []
    for i, (x, y, seen) in enumerate(points):
        if x is None:
            out.append((x, y, seen))
            continue
        win = [p for p in points[max(0, i - k // 2): i + k // 2 + 1] if p[0] is not None and p[2]]
        if seen and win:
            out.append((sum(p[0] for p in win) / len(win), sum(p[1] for p in win) / len(win), True))
        else:
            out.append((x, y, seen))
    return out


def _fill(points):
    """Fill the gaps before a robot is first seen with its first position (marked unseen)."""
    first = next((p for p in points if p[0] is not None), None)
    if not first:
        return points
    return [(first[0], first[1], False) if p[0] is None else p for p in points]


# ---------------------------------------------------------------- behaviour
def _speeds(times, pts):
    out = [0.0] * len(pts)
    for i in range(1, len(pts)):
        dt = times[i] - times[i - 1]
        if dt > 0 and pts[i][0] is not None and pts[i - 1][0] is not None:
            out[i] = field.distance(pts[i], pts[i - 1]) / dt
    return out


def _runs(flags, times, min_len):
    """Contiguous True runs as (t_start, t_end) lasting at least min_len seconds."""
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            t0, t1 = times[start], times[i - 1] + (times[1] - times[0] if len(times) > 1 else 0)
            if t1 - t0 >= min_len:
                out.append((round(t0, 1), round(t1, 1)))
            start = None
    return out


def analyze(det, clean_rows, balls, teams, labels=None, layout=None, frame_size=(1920, 1080)):
    """Everything the match page shows about robots.

    det: robot_detections.json, clean_rows: scorebug_clean.json, balls: query.analyze()
    output (per-second ball estimates), teams: {"blue": [..], "red": [..]} in scorebug order,
    labels: {slot: team} set by the user.
    """
    labels = labels or {}
    mapper = field.Mapper(layout or field.load_layout(), *frame_size)
    clock = match_clock(clean_rows)
    times, raw = track(det["samples"], mapper, clock)
    if len(times) < 2:
        return {"available": False, "reason": "no robot detections in the match"}
    dt = (times[-1] - times[0]) / (len(times) - 1)
    pos = {s: _fill(_smooth(raw[s], settings.TRACK_SMOOTH)) for s in SLOTS}

    # slot -> team: user label, otherwise a guess (scorebug order matched to start position, far side first)
    slot_team = {}
    for a in ALLIANCES:
        names = [f"{a}{i}" for i in (1, 2, 3)]
        start_y = {s: next((p[1] for p in pos[s] if p[0] is not None), 0) for s in names}
        order = sorted(names, key=lambda s: -start_y[s])
        guess = list(teams.get(a) or [])
        for i, s in enumerate(order):
            team = labels.get(s) or (guess[i] if i < len(guess) else None)
            slot_team[s] = {"team": team, "team_source": "user" if s in labels else "guess"}

    per_second = {s["t"]: s for s in balls["seconds"]} if balls else {}
    speed = {s: _speeds(times, pos[s]) for s in SLOTS}
    shooting = {}
    for s in SLOTS:
        a = s[:-1]
        # a robot hidden behind people keeps its last position (p[2] False) and still counts:
        # robots mostly stop to shoot, which is exactly when the near-side crowd hides them
        shooting[s] = [p[0] is not None and abs(p[0] - field.wall_x(a)) <= settings.ALLIANCE_ZONE + settings.SHOOT_ZONE_MARGIN
                       and v < settings.SHOOT_MAX_SPEED and 0 <= t <= 160 for p, v, t in zip(pos[s], speed[s], times)]

    # shooting spells (bursts) shorter than MIN_BURST are dropped
    bursts = {s: _runs(shooting[s], times, settings.MIN_BURST) for s in SLOTS}

    def shooting_at(s, t):
        return any(a <= t <= b for a, b in bursts[s])

    # balls in: each second's alliance estimate shared between the robots shooting SHOT_FLIGHT s before
    est = {s: 0.0 for s in SLOTS}
    est_period = {s: {} for s in SLOTS}
    unattributed = {a: 0.0 for a in ALLIANCES}
    burst_balls = {(s, b): 0.0 for s in SLOTS for b in bursts[s]}
    for sec, row in per_second.items():
        for a in ALLIANCES:
            n = row[a]["estimate"]
            if not n:
                continue
            t = sec + 0.5 - settings.SHOT_FLIGHT
            shooters = [s for s in SLOTS if s.startswith(a) and shooting_at(s, t)]
            if not shooters:
                # fallback: the alliance robot closest to its hub, if it is near enough to shoot
                i = min(range(len(times)), key=lambda k: abs(times[k] - t))
                hub = field.hub_xy(a)
                near = [(field.distance(pos[s][i], hub), s) for s in SLOTS
                        if s.startswith(a) and pos[s][i][0] is not None]
                near = [x for x in near if x[0] <= settings.FALLBACK_SHOOT_RANGE]
                if not near:
                    unattributed[a] += n
                    continue
                shooters = [min(near)[1]]
            for s in shooters:
                est[s] += n / len(shooters)
                p = row["period"]
                est_period[s][p] = est_period[s].get(p, 0) + n / len(shooters)
                for b in bursts[s]:
                    if b[0] <= t <= b[1]:
                        burst_balls[(s, b)] += n / len(shooters)

    # contacts between any two robots (opponents flagged)
    events = []
    for i, s1 in enumerate(SLOTS):
        for s2 in SLOTS[i + 1:]:
            close = [p[2] and q[2] and p[0] is not None and q[0] is not None and
                     field.distance(p, q) < settings.CONTACT_DIST for p, q in zip(pos[s1], pos[s2])]
            for t0, t1 in _runs(close, times, settings.CONTACT_MIN):
                events.append({"kind": "contact", "t0": t0, "t1": t1, "a": s1, "b": s2,
                               "opponents": s1[:-1] != s2[:-1]})
    for s in SLOTS:
        for b in bursts[s]:
            events.append({"kind": "shot", "slot": s, "t0": b[0], "t1": b[1],
                           "balls": round(burst_balls[(s, b)], 1),
                           "hub": list(field.hub_xy(s[:-1]))})
    events.sort(key=lambda e: e["t0"])

    # per-robot stats
    robots = []
    for s in SLOTS:
        a = s[:-1]
        opp = [o for o in SLOTS if not o.startswith(a)]
        pts, n = pos[s], len(pos[s])
        seen = [p[2] for p in pts]
        zones = {"own": 0, "neutral": 0, "opponent": 0}
        defense = 0
        dist = 0.0
        for i, p in enumerate(pts):
            if p[0] is None:
                continue
            z = field.zone_of(p[0], a)
            zones[z] += dt
            if i and p[2] and pts[i - 1][2]:
                dist += field.distance(p, pts[i - 1])
            if z != "own" and p[2]:
                near = [pos[o][i] for o in opp if pos[o][i][0] is not None and pos[o][i][2]]
                if any(field.distance(p, q) < settings.DEFENSE_DIST for q in near) and \
                        abs(p[0] - field.wall_x(a)) > settings.FIELD_LENGTH / 2:
                    defense += dt
        contacts = [e for e in events if e["kind"] == "contact" and s in (e["a"], e["b"])]
        end = [p for p, t in zip(pts, times) if t >= 150 and p[0] is not None]
        end_wall = (sum(abs(p[0] - field.wall_x(a)) for p in end) / len(end)) if end else None
        shoot_s = sum(b[1] - b[0] for b in bursts[s])
        total = max(1e-9, times[-1] - times[0])
        stats = {
            "seen_pct": round(100 * sum(seen) / max(1, n)),
            "distance_m": round(dist, 1),
            "avg_speed": round(dist / total, 2),
            "zone_s": {k: round(v) for k, v in zones.items()},
            "shooting_s": round(shoot_s),
            "shots": len(bursts[s]),
            "balls_est": round(est[s], 1),
            "balls_by_period": {k: round(v, 1) for k, v in est_period[s].items()},
            "defense_s": round(defense),
            "contacts": len(contacts),
            "contacts_opponent": sum(1 for e in contacts if e["opponents"]),
            "endgame_near_wall": end_wall is not None and end_wall <= settings.ENDGAME_PARK_WALL,
        }
        stats["role"] = _role(stats, total)
        robots.append({"slot": s, "alliance": a, **slot_team[s], "stats": stats})

    step = max(1, round((1 / settings.REPLAY_HZ) / dt)) if dt else 1
    return {
        "available": True,
        "times": [round(t, 2) for t in times[::step]],
        "positions": {s: [[round(p[0], 2), round(p[1], 2), int(p[2])] if p[0] is not None else None
                          for p in pos[s][::step]] for s in SLOTS},
        "robots": robots,
        "events": events,
        "unattributed": {a: round(v, 1) for a, v in unattributed.items()},
        "field": {"length": settings.FIELD_LENGTH, "width": settings.FIELD_WIDTH,
                  "hubs": {a: field.hub_xy(a) for a in ALLIANCES}, "hub_size": settings.HUB_SIZE,
                  "zone": settings.ALLIANCE_ZONE, "periods": PERIODS},
    }


def _role(st, total):
    """A one-word guess at what the robot mostly did."""
    if st["seen_pct"] < 25:
        return "unknown (rarely seen)"
    if st["avg_speed"] < 0.15:
        return "stationary / disabled?"
    shares = {  # weights are guesses; tune ROLE_WEIGHTS in settings.py
        "scorer": settings.ROLE_WEIGHTS["scorer"] * st["shooting_s"] / total,
        "defender": settings.ROLE_WEIGHTS["defender"] * (st["defense_s"] + 0.3 * st["zone_s"]["opponent"]) / total,
        "collector": settings.ROLE_WEIGHTS["collector"] * 0.3 * st["zone_s"]["neutral"] / total,
    }
    return max(shares, key=shares.get)


# ---------------------------------------------------------------- files
def labels_path(match_dir):
    return Path(match_dir) / "robot_labels.json"


def load_labels(match_dir):
    p = labels_path(match_dir)
    return json.loads(p.read_text()) if p.exists() else {}


def save_labels(match_dir, labels):
    labels = {k: int(v) for k, v in labels.items() if k in SLOTS and v not in (None, "", 0)}
    labels_path(match_dir).write_text(json.dumps(labels))
    return labels
