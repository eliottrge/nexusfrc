"""The Blue Alliance (TBA) API v3: events, matches, teams, official scores, video links.

Optional: everything else works without it. Needs a free read key (thebluealliance.com ->
Account -> Read API Keys) saved on the Settings page or as TBA_API_KEY. Responses are cached
on disk (DATA_DIR/_tba_cache) so a page reload does not hit the API again.

The 2026 score_breakdown fields have not been checked against real data yet, so they are
passed through untouched (shown as a table) and `fuel_totals` only picks fields whose name
mentions fuel. Adjust FUEL_FIELD_HINTS once the real names are known.
"""
import hashlib
import json
import time
import urllib.error
import urllib.request

from .. import settings

BASE = "https://www.thebluealliance.com/api/v3"
CACHE_SECONDS = 600
FUEL_FIELD_HINTS = ("fuel",)


class TBAError(Exception):
    pass


def _cache_dir():
    d = settings.DATA_DIR / "_tba_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get(path, max_age=CACHE_SECONDS):
    key = settings.get_key("TBA_API_KEY")
    if not key:
        raise TBAError("No TBA key. Add one on the Settings page (free from thebluealliance.com/account).")
    cache = _cache_dir() / (hashlib.sha1(path.encode()).hexdigest() + ".json")
    if cache.exists() and time.time() - cache.stat().st_mtime < max_age:
        return json.loads(cache.read_text())
    req = urllib.request.Request(BASE + path, headers={"X-TBA-Auth-Key": key, "User-Agent": "nexusfrc"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise TBAError("TBA rejected the key (401). Check it on the Settings page.") from e
        if e.code == 404:
            raise TBAError(f"Not found on TBA: {path}") from e
        raise TBAError(f"TBA error {e.code} for {path}") from e
    except urllib.error.URLError as e:
        if cache.exists():  # offline: use the stale copy
            return json.loads(cache.read_text())
        raise TBAError(f"Cannot reach TBA: {e.reason}") from e
    cache.write_text(json.dumps(data))
    return data


def _team_numbers(keys):
    return [int(k[3:]) for k in keys if k.startswith("frc") and k[3:].isdigit()]


def simplify_match(m):
    """The parts of a TBA match the app uses."""
    al = m.get("alliances", {})
    videos = [v["key"] for v in m.get("videos", []) if v.get("type") == "youtube"]
    return {
        "key": m["key"],
        "event": m.get("event_key"),
        "comp_level": m.get("comp_level"),
        "set": m.get("set_number"),
        "number": m.get("match_number"),
        "name": match_name(m),
        "time": m.get("actual_time") or m.get("predicted_time") or m.get("time"),
        "teams": {a: _team_numbers(al.get(a, {}).get("team_keys", [])) for a in ("blue", "red")},
        "score": {a: al.get(a, {}).get("score") for a in ("blue", "red")},
        "winner": m.get("winning_alliance") or None,
        "youtube": videos,
        "breakdown": m.get("score_breakdown"),
    }


def match_name(m):
    lvl = {"qm": "Qual", "ef": "Eighth", "qf": "Quarter", "sf": "Semi", "f": "Final"}.get(m.get("comp_level"), m.get("comp_level", ""))
    if m.get("comp_level") == "qm":
        return f"Qual {m.get('match_number')}"
    return f"{lvl} {m.get('set_number')}-{m.get('match_number')}"


def event_matches(event_key):
    order = {"qm": 0, "ef": 1, "qf": 2, "sf": 3, "f": 4}
    ms = [simplify_match(m) for m in get(f"/event/{event_key}/matches")]
    return sorted(ms, key=lambda m: (order.get(m["comp_level"], 9), m["set"] or 0, m["number"] or 0))


def match(match_key):
    return simplify_match(get(f"/match/{match_key}"))


def event(event_key):
    e = get(f"/event/{event_key}", max_age=86400)
    return {"key": e["key"], "name": e.get("name"), "year": e.get("year"), "city": e.get("city")}


def events(year):
    return [{"key": e["key"], "name": e.get("name"), "start": e.get("start_date")}
            for e in get(f"/events/{year}/simple", max_age=86400)]


def fuel_totals(breakdown):
    """{alliance: {field: value}} for numeric breakdown fields whose name mentions fuel."""
    out = {}
    for a, fields in (breakdown or {}).items():
        if isinstance(fields, dict):
            out[a] = {k: v for k, v in fields.items()
                      if isinstance(v, (int, float)) and any(h in k.lower() for h in FUEL_FIELD_HINTS)}
    return out
