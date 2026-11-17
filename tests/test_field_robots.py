from frcsim import coach, field, robots, settings
from frcsim.ingest import tba


def layout():
    # a camera looking straight down: 100 px per metre, origin at pixel (0, 1000)
    pts = [(0, 0), (16, 0), (0, 8), (16, 8)]
    return {"frame_size": [1920, 1080], "field_region": [0, 0, 1920, 1080],
            "calibration": [{"label": "", "field": [x, y], "image": [x * 100, 1000 - y * 100]} for x, y in pts]}


def test_mapper_round_trip():
    m = field.Mapper(layout())
    x, y = m.to_field(*m.to_image(5.0, 3.0))
    assert abs(x - 5) < 1e-6 and abs(y - 3) < 1e-6


def test_mapper_scales_to_video_size():
    m = field.Mapper(layout(), 960, 540)  # half-size video: same field point at half the pixels
    x, y = m.to_field(250, 350)
    assert abs(x - 5) < 1e-6 and abs(y - 3) < 1e-6


def test_zones():
    assert field.zone_of(1.0, "blue") == "own"
    assert field.zone_of(1.0, "red") == "opponent"
    assert field.zone_of(8.0, "red") == "neutral"


def box(x, y):
    """A pixel box whose robot centre lands on field (x, y) in the test layout."""
    py = 1000 - (y - settings.ROBOT_GROUND_DEPTH) * 100
    return [x * 100 - 40, py - 60, x * 100 + 40, py]


def test_tracker_keeps_identity_when_robots_move():
    m = field.Mapper(layout())
    clock = lambda t: t
    blue, red = (0.0, 0.3), (0.3, 0.0)
    samples = []
    for k in range(6):
        t = k / 3
        samples.append({"video_t": t, "robots": [
            box(2 + 0.3 * k, 2, ) + [0.9, *blue], box(2, 6 - 0.3 * k) + [0.9, *blue],
            box(14, 4) + [0.9, *red]]})
    times, pos = robots.track(samples, m, clock)
    first = {s: pos[s][0][:2] for s in robots.SLOTS if pos[s][0][0] is not None}
    last = {s: pos[s][-1][:2] for s in robots.SLOTS if pos[s][-1][0] is not None}
    mover = next(s for s, p in first.items() if abs(p[0] - 2) < 0.01 and abs(p[1] - 2) < 0.01)
    assert abs(last[mover][0] - 3.5) < 0.01  # same slot followed the robot along x
    assert sum(1 for s in first if s.startswith("red")) == 1


def test_hidden_robot_keeps_last_position():
    m = field.Mapper(layout())
    samples = [{"video_t": 0, "robots": [box(3, 3) + [0.9, 0.0, 0.3]]}, {"video_t": 0.4, "robots": []}]
    _, pos = robots.track(samples, m, lambda t: t)
    s = next(s for s in robots.SLOTS if pos[s][0][0] is not None)
    assert pos[s][1][2] is False and abs(pos[s][1][0] - 3) < 1e-6


def test_coach_strengths_and_recommendation():
    rows = []
    for team, balls in ((1, 100), (2, 20), (3, 20), (4, 200), (5, 30), (6, 30)):
        rows.append({"team": team, "match": "m", "alliance": "blue", "team_source": "user", "role": "scorer",
                     "balls_est": balls, "auto_balls": 5, "shots": 5, "shooting_s": 30, "distance_m": 100,
                     "defense_s": 0, "contacts_opponent": 0, "endgame_rate": 0, "seen_pct": 90})
    profs = coach.profiles(rows)
    rep = coach.report(1, profs)
    assert any("Balls scored" in s for s in rep["strengths"])
    rec = coach.recommend(1, [2, 3], [4, 5, 6], profs)
    assert any("main scorer" in t for t in rec["tips"])
    assert any("4" in t and "defence" in t for t in rec["tips"])


def test_tba_simplify_match():
    m = {"key": "2026x_qm1", "event_key": "2026x", "comp_level": "qm", "set_number": 1, "match_number": 1,
         "alliances": {"blue": {"team_keys": ["frc1", "frc2", "frc3"], "score": 50},
                       "red": {"team_keys": ["frc4", "frc5", "frc6"], "score": 40}},
         "videos": [{"type": "youtube", "key": "abc"}], "score_breakdown": {"blue": {"autoFuel": 3, "x": "y"}}}
    s = tba.simplify_match(m)
    assert s["teams"]["red"] == [4, 5, 6] and s["youtube"] == ["abc"] and s["name"] == "Qual 1"
    assert tba.fuel_totals(s["breakdown"]) == {"blue": {"autoFuel": 3}}
