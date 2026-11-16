from frcsim.ingest.video.fuel_per_second import hub_active, period_of


def test_periods():
    assert period_of(0) == "AUTO"
    assert period_of(25) == "TRANSITION"
    assert period_of(30) == "SHIFT 1"
    assert period_of(159) == "END GAME"


def test_hub_shifts_table_6_3():
    # red won auto -> red inactive in SHIFT 1 and 3, blue inactive in SHIFT 2 and 4
    assert hub_active("SHIFT 1", "red", "red") is False
    assert hub_active("SHIFT 1", "blue", "red") is True
    assert hub_active("SHIFT 2", "red", "red") is True
    assert hub_active("SHIFT 4", "blue", "red") is False
    assert hub_active("END GAME", "blue", "red") is True
