from frcsim.query import analyze, count_range
from frcsim.schema import Event, Timeline


def ev(t, kind, alliance, n, active=True):
    return Event(t=t, kind=kind, alliance=alliance, count=n, hub_active=active,
                 source="scorebug_ocr" if kind == "fuel_scored" else "video_counter")


def timeline(events, auto_winner="red"):
    return Timeline(auto_winner=auto_winner, events=events)


def test_active_hub_uses_scorebug_points():
    a = analyze(timeline([ev(5, "fuel_scored", "blue", 8), ev(5, "fuel_entry", "blue", 4)]))
    r = count_range(a, 0, 20)
    assert r["blue"]["estimate"] == 8
    assert (r["blue"]["scored"], r["blue"]["counted"]) == (8, 4)


def test_inactive_hub_uses_scaled_video_count():
    # While active the video sees half of what the scorebug scores -> factor 2.
    # Red won AUTO, so red's hub is inactive in SHIFT 1 (30-55 s): only the video count is used.
    events = [ev(5, "fuel_scored", "red", 10), ev(5, "fuel_entry", "red", 5),
              ev(40, "fuel_entry", "red", 3, active=False), ev(40, "fuel_scored", "red", 99, active=False)]
    a = analyze(timeline(events))
    assert a["calibration"] == 2.0
    r = count_range(a, 30, 55)["red"]
    assert r["estimate"] == 6 and r["video_only_seconds"] == 25


def test_end_game_ignores_scorebug_points():
    # tower points inflate the scorebug in END GAME, so only the (scaled) video count is used
    a = analyze(timeline([ev(140, "fuel_scored", "red", 30), ev(140, "fuel_entry", "red", 4)]))
    assert count_range(a, 130, 160)["red"]["estimate"] == 4


def test_range_is_half_open_and_clamped():
    a = analyze(timeline([ev(10, "fuel_scored", "red", 3), ev(11, "fuel_scored", "red", 4)]))
    assert count_range(a, 10, 11)["red"]["estimate"] == 3
    assert count_range(a, -5, 999)["red"]["estimate"] == 7
    assert count_range(a, 12, 12)["red"]["estimate"] == 0


def test_scorebug_lag_is_found_and_removed():
    # the scorebug repeats every video entry two seconds later
    events = []
    for t, n in ((3, 4), (6, 9), (9, 2), (12, 7), (15, 5)):
        events += [ev(t, "fuel_entry", "blue", n), ev(t + 2, "fuel_scored", "blue", n)]
    a = analyze(timeline(events))
    assert a["lag"] == 2
    assert count_range(a, 0, 5)["blue"]["estimate"] == 4  # the ball entering at 3 s, not at 5 s
