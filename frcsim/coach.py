"""Team profiles across matches, and plain-language coaching built from them.

A profile averages a team's per-match robot stats (frcsim/robots.py) over every analyzed
match it played. The coach compares a profile with the average of all teams seen
(the "field"), and suggests what a team could do in a match given its partners and
opponents. Every rule is a small function below with its threshold in RULES, so the
advice is easy to read, change, or extend.

All numbers inherit the uncertainty of the robot stats: robot identities are guesses
unless a user labelled them, and per-robot balls are estimates. The coach says so.
"""
from statistics import mean

METRICS = {  # key -> (label, unit, higher is better)
    "balls_est": ("Balls scored (est.)", "", True),
    "auto_balls": ("AUTO balls (est.)", "", True),
    "shots": ("Shooting spells", "", True),
    "shooting_s": ("Time shooting", "s", True),
    "distance_m": ("Distance driven", "m", True),
    "defense_s": ("Time defending", "s", None),
    "contacts_opponent": ("Contacts with opponents", "", False),
    "endgame_rate": ("Ends near own wall (climb/park guess)", "%", True),
}

RULES = {
    "strength_ratio": 1.2,     # >= 120% of the field average is a strength
    "weakness_ratio": 0.8,     # <= 80% is a weakness
    "min_field_value": 1.0,    # ignore metrics where the field average is ~0
    "defend_gap": 1.4,         # an opponent scoring 1.4x the next one is worth defending
    "foul_contacts": 2.0,      # more opponent contacts per match than this = foul risk
}


def match_rows(analyses):
    """Flatten {match_id: robots.analyze() output} into one row per (team, match)."""
    rows = []
    for mid, r in analyses.items():
        if not r.get("available"):
            continue
        for rb in r["robots"]:
            if not rb.get("team"):
                continue
            st = rb["stats"]
            rows.append({"team": rb["team"], "match": mid, "alliance": rb["alliance"],
                         "team_source": rb["team_source"], "role": st["role"],
                         "balls_est": st["balls_est"], "auto_balls": st["balls_by_period"].get("AUTO", 0),
                         "shots": st["shots"], "shooting_s": st["shooting_s"], "distance_m": st["distance_m"],
                         "defense_s": st["defense_s"], "contacts_opponent": st["contacts_opponent"],
                         "endgame_rate": 100.0 if st["endgame_near_wall"] else 0.0,
                         "seen_pct": st["seen_pct"]})
    return rows


def profiles(rows):
    out = {}
    for team in sorted({r["team"] for r in rows}):
        mine = [r for r in rows if r["team"] == team]
        roles = {}
        for r in mine:
            roles[r["role"]] = roles.get(r["role"], 0) + 1
        out[team] = {
            "team": team,
            "matches": len(mine),
            "match_ids": [r["match"] for r in mine],
            "guessed_identity": sum(1 for r in mine if r["team_source"] == "guess"),
            "roles": roles,
            "main_role": max(roles, key=roles.get),
            "avg": {k: round(mean(r[k] for r in mine), 1) for k in METRICS},
            "seen_pct": round(mean(r["seen_pct"] for r in mine)),
        }
    return out


def field_average(profs):
    if not profs:
        return {k: 0 for k in METRICS}
    return {k: round(mean(p["avg"][k] for p in profs.values()), 1) for k in METRICS}


def _fmt(k, v):
    unit = METRICS[k][1]
    return f"{v:.0f}{unit}" if unit else f"{v:.1f}".rstrip("0").rstrip(".")


def report(team, profs, field=None):
    """Strengths, weaknesses and strategy for one team."""
    p = profs.get(team)
    if not p:
        return None
    field = field or field_average(profs)
    strengths, weaknesses = [], []
    for k, (label, _, better) in METRICS.items():
        f, v = field[k], p["avg"][k]
        if better is None or f < RULES["min_field_value"]:
            continue
        ratio = v / f if f else 0
        line = f"{label}: {_fmt(k, v)} per match vs {_fmt(k, f)} field average"
        high, low = ratio >= RULES["strength_ratio"], ratio <= RULES["weakness_ratio"]
        if (high and better) or (low and not better):
            strengths.append(line)
        elif (low and better) or (high and not better):
            weaknesses.append(line)
    strategy = _strategy(p, field)
    caveats = []
    if p["guessed_identity"]:
        caveats.append(f"Robot identity is a guess in {p['guessed_identity']} of {p['matches']} matches; "
                       "label the robots on the match page to make this reliable.")
    if p["matches"] < 3:
        caveats.append(f"Only {p['matches']} match(es) analyzed; patterns need about 3 or more.")
    if p["seen_pct"] < 60:
        caveats.append(f"The robot was visible only {p['seen_pct']}% of the time on average.")
    return {"team": team, "profile": p, "field": field, "strengths": strengths,
            "weaknesses": weaknesses, "strategy": strategy, "caveats": caveats}


def _strategy(p, field):
    a = p["avg"]
    role = p["main_role"]
    lines = {
        "scorer": f"Mainly a scorer: about {a['shots']:.0f} shooting spells and {a['balls_est']:.0f} balls per match.",
        "defender": f"Often plays defence: {a['defense_s']:.0f} s per match close to opponents in their half.",
        "collector": "Spends a lot of time in the neutral zone, likely collecting or feeding balls.",
    }
    out = [lines.get(role, f"Main role: {role}.")]
    if field["auto_balls"] and a["auto_balls"] >= 1.5 * field["auto_balls"]:
        out.append("Strong AUTO: scores much of its fuel in the first 20 s.")
    if a["endgame_rate"] >= 50:
        out.append("Usually ends the match near its own wall (likely climbing or parking).")
    if len(p["roles"]) > 1:
        out.append("Role changes between matches: " + ", ".join(f"{k} x{v}" for k, v in p["roles"].items()) + ".")
    return out


def recommend(team, partners, opponents, profs):
    """What `team` could most logically do in a match with these partners and opponents."""
    field = field_average(profs)
    me = profs.get(team)
    known = lambda ts: [profs[t] for t in ts if t in profs]
    part, opp = known(partners), known(opponents)
    tips, missing = [], [t for t in [team, *partners, *opponents] if t not in profs]

    if me:
        my_balls = me["avg"]["balls_est"]
        part_balls = [q["avg"]["balls_est"] for q in part]
        if part_balls and my_balls >= max(part_balls):
            tips.append(f"Be the alliance's main scorer: {my_balls:.0f} balls per match is the most on this alliance.")
        elif part_balls and len([b for b in part_balls if b > my_balls]) == len(part_balls) and len(part_balls) >= 2:
            tips.append(f"Both partners score more ({', '.join(f'{b:.0f}' for b in part_balls)} per match): "
                        "consider feeding them, defending, or securing the end game instead.")
        if me["avg"]["contacts_opponent"] > RULES["foul_contacts"]:
            tips.append(f"Many contacts with opponents ({me['avg']['contacts_opponent']:.1f} per match): watch the foul risk.")
        if field["auto_balls"] and me["avg"]["auto_balls"] < 0.6 * field["auto_balls"]:
            tips.append("AUTO is below the field average: a stronger AUTO also decides which hub is active first.")

    if len(opp) >= 2:
        ranked = sorted(opp, key=lambda q: -q["avg"]["balls_est"])
        top, nxt = ranked[0], ranked[1]
        if nxt["avg"]["balls_est"] and top["avg"]["balls_est"] >= RULES["defend_gap"] * nxt["avg"]["balls_est"]:
            tips.append(f"Opponent {top['team']} scores far more than its partners "
                        f"({top['avg']['balls_est']:.0f} vs {nxt['avg']['balls_est']:.0f} per match): "
                        "slowing it down is the highest-value defence.")
    alliance = ([me] if me else []) + part
    if alliance and not any(q["avg"]["endgame_rate"] >= 50 for q in alliance):
        tips.append("No robot on this alliance usually finishes near its wall: plan who takes the end game.")
    if not tips:
        tips.append("No clear advantage found in the data; play to the team's usual role.")
    note = "Based on estimated per-robot stats." + (f" No data yet for: {', '.join(map(str, missing))}." if missing else "")
    return {"team": team, "tips": tips, "note": note}


def match_notes(result):
    """Short per-robot notes for one match: what stood out compared with the other five robots."""
    if not result.get("available"):
        return {}
    keys = ["balls_est", "shooting_s", "defense_s", "distance_m", "contacts_opponent"]
    avg = {k: mean(r["stats"][k] for r in result["robots"]) for k in keys}
    out = {}
    for r in result["robots"]:
        st, notes = r["stats"], []
        if avg["balls_est"] and st["balls_est"] >= 1.3 * avg["balls_est"]:
            notes.append(f"Top scorer of the match (about {st['balls_est']:.0f} balls).")
        elif avg["balls_est"] and st["balls_est"] <= 0.5 * avg["balls_est"]:
            notes.append("Scored little compared with the other robots.")
        if st["defense_s"] >= 20:
            notes.append(f"Played defence for about {st['defense_s']} s.")
        if st["contacts_opponent"] >= 2:
            notes.append(f"{st['contacts_opponent']} contacts with opponents.")
        if st["endgame_near_wall"]:
            notes.append("Finished near its own wall (climb/park?).")
        if st["seen_pct"] < 50:
            notes.append(f"Only visible {st['seen_pct']}% of the time: stats are rough.")
        if not notes:
            notes.append(f"Main role this match: {st['role']}.")
        out[r["slot"]] = notes
    return out
