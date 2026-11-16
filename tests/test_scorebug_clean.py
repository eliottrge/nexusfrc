from frcsim.ingest.video.scorebug_clean import clean, clean_series


def test_rejects_spike_and_drop():
    vals = [5, 6, 60, 7, 6, None, 9]
    out, rej = clean_series(vals)
    assert out == [5, 6, 6, 7, 7, 7, 9]
    assert rej == 2


def test_match_time_phases():
    rows = [{"clock": 20, "blue": 0, "red": 0}, {"clock": 0, "blue": 1, "red": 1},
            {"clock": 140, "blue": 2, "red": 2}, {"clock": 0, "blue": 3, "red": 3}]
    out, _ = clean(rows)
    assert [r["phase"] for r in out] == ["auto", "auto", "teleop", "teleop"]
    assert [r["match_t"] for r in out] == [0, 20, 20, 160]


def test_find_match_window():
    from frcsim.pipeline import find_match_window
    rows = [{"video_t": t, "clock": c} for t, c in
            [(0, None), (1, 20), (2, 19), (3, None), (4, 140), (5, 139), (6, 138), (7, None)]]
    assert find_match_window(rows) == (4, 6)
