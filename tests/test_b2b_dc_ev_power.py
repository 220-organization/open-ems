"""EV port aggregate power from device station/all?acdc=ac|dc."""

from app.ev_port_power_service import sum_ev_power_w_from_station_rows


def test_sum_skips_rows_without_job():
    raw = [
        {"number": "1", "job": None},
        {"number": "2", "job": {"powerWt": 51000, "state": "IN_PROGRESS"}},
        {"number": "3", "job": {"powerWt": 12000}},
    ]
    total, sessions = sum_ev_power_w_from_station_rows(raw)
    assert total == 63000.0
    assert sessions == 2


def test_sum_ignores_invalid_power():
    raw = [
        {"job": {"powerWt": None}},
        {"job": {"powerWt": "bad"}},
        {"job": {"powerWt": 0}},
    ]
    total, sessions = sum_ev_power_w_from_station_rows(raw)
    assert total == 0.0
    assert sessions == 0
