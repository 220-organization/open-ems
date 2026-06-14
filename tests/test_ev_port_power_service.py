"""EV port power sample aggregation."""

from datetime import datetime, timezone

from app.ev_port_power_service import sum_ev_power_w_from_station_rows
from app.huawei_power_service import floor_to_5min_utc


def test_sum_skips_rows_without_job():
    raw = [
        {"number": "1", "job": None},
        {"number": "2", "job": {"powerWt": 51000, "state": "IN_PROGRESS"}},
        {"number": "3", "job": {"powerWt": 12000}},
    ]
    total, sessions = sum_ev_power_w_from_station_rows(raw)
    assert total == 63000.0
    assert sessions == 2


def test_floor_to_5min_utc():
    ts = datetime(2026, 6, 14, 12, 7, 59, tzinfo=timezone.utc)
    assert floor_to_5min_utc(ts) == datetime(2026, 6, 14, 12, 5, 0, tzinfo=timezone.utc)


def test_hourly_kwh_from_power_w():
    # 60 kW for one 5-min bucket → 5 kWh
    kwh = 60_000.0 / 12000.0
    assert kwh == 5.0
