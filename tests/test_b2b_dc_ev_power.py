"""EV port aggregate power from device station/all?acdc=ac|dc."""

from app.ev_port_power_service import sum_ev_power_w_from_station_rows
from app.routers.b2b_proxy import use_fleet_origin_fallback


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


def test_far_location_with_no_ports_falls_back_to_fleet_origin():
    assert use_fleet_origin_fallback(40.4168, -3.7038, 0) is True
    assert use_fleet_origin_fallback(1.35, 103.82, 0) is True


def test_kyiv_or_nearby_hits_do_not_fall_back():
    assert use_fleet_origin_fallback(50.4501, 30.5234, 0) is False
    assert use_fleet_origin_fallback(40.4168, -3.7038, 3) is False
