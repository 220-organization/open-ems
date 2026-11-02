from app.deye_soc_service import classify_hour_off_grid


def test_stored_off_grid_sample_marks_the_hour():
    assert classify_hour_off_grid([True], [50.0]) is True
    assert classify_hour_off_grid([False, True], [50.0, 50.0]) is True


def test_on_grid_sample_keeps_the_hour_on_grid():
    assert classify_hour_off_grid([False], [50.0]) is False


def test_missing_frequency_is_legacy_off_grid():
    assert classify_hour_off_grid([None, None], [None, None]) is True


def test_empty_hour_is_unknown():
    assert classify_hour_off_grid([], []) is None
