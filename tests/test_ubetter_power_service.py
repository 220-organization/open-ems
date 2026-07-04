"""Ubetter 5-minute power snapshot helpers."""

from datetime import datetime, timezone

from app.deye_soc_service import floor_to_5min_utc
from app.ubetter_power_service import _mean_or_none, _mean_power_w_to_kwh_hour, _optional_float


def test_floor_to_5min_utc_aligns():
    dt = datetime(2026, 7, 4, 10, 17, 42, tzinfo=timezone.utc)
    bucket = floor_to_5min_utc(dt)
    assert bucket.minute % 5 == 0
    assert bucket.second == 0


def test_optional_float():
    assert _optional_float(27.0) == 27.0
    assert _optional_float("bad") is None
    assert _optional_float(None) is None


def test_mean_power_w_to_kwh_hour():
    assert _mean_power_w_to_kwh_hour(500.0) == 0.5
    assert _mean_power_w_to_kwh_hour(None) is None


def test_mean_or_none():
    assert _mean_or_none([10.0, 20.0]) == 15.0
    assert _mean_or_none([]) is None
