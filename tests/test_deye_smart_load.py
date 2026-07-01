"""Tests for Deye smart-load automation."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.deye_api import (
    _deye_modbus_analysis_failed,
    _find_on_grid_always_on_in_obj,
    _on_grid_always_on_from_register_value,
    _parse_modbus_read_u16,
    _smart_load_power_watts_from_data_list,
    on_grid_always_on_from_deye_order,
)
from app.deye_smart_load_service import pv_below_sl
from app.deye_smart_load_state import (
    HourlyPvSlBucket,
    bump_pv_below_streak,
    clear_device_state,
    prune_hourly_cache,
    record_hourly_sample,
    reset_pv_below_streak,
    yesterday_hour_all_pv_below,
)
from app.oree_dam_service import KYIV


def _row(key: str, value: float, unit: str = "W") -> dict:
    return {"key": key, "value": value, "unit": unit}


def test_smart_load_power_prefers_smart_load_register():
    dl = [
        _row("UPSLoadPower", 21530.0),
        _row("SmartLoadPower", 4200.0),
    ]
    assert _smart_load_power_watts_from_data_list(dl) == 4200.0


def test_smart_load_power_falls_back_to_load():
    dl = [_row("UPSLoadPower", 21530.0)]
    assert _smart_load_power_watts_from_data_list(dl) == 21530.0


def test_find_on_grid_always_on_bool():
    assert _find_on_grid_always_on_in_obj({"onGridAlwaysOn": True}) is True
    assert _find_on_grid_always_on_in_obj({"smartLoadMode": "ON_GRID_ALWAYS_ON"}) is True


def test_on_grid_always_on_from_deye_order_result():
    order_echo = {
        "orderId": 108132801,
        "status": 666,
        "analysisResult": "0500",
        "orderResult": '{"cmd":"smartLoadSetup","onGridAlwaysOn":false}',
    }
    assert on_grid_always_on_from_deye_order(order_echo) is None
    order_verified = {
        "status": 666,
        "analysisResult": "010600B2004201F8",
        "orderResult": '{"cmd":"smartLoadSetup","onGridAlwaysOn":true,"register0x00B2":66,"verified":true}',
    }
    assert on_grid_always_on_from_deye_order(order_verified) is True


def test_parse_modbus_read_and_on_grid_bit():
    assert _parse_modbus_read_u16("01030200023985") == 2
    assert _parse_modbus_read_u16("0500") is None
    assert _deye_modbus_analysis_failed("0500", expect_fc=6) is True
    assert _on_grid_always_on_from_register_value(2) is False
    assert _on_grid_always_on_from_register_value(66) is True


def test_pv_below_sl_comparison():
    assert pv_below_sl(1000.0, 2000.0, min_sl_w=100) is True
    assert pv_below_sl(2500.0, 2000.0, min_sl_w=100) is False
    assert pv_below_sl(2500.0, 50.0, min_sl_w=100) is None


def test_streak_counter():
    sn = "2512291445"
    clear_device_state(sn)
    reset_pv_below_streak(sn)
    assert bump_pv_below_streak(sn) == 1
    assert bump_pv_below_streak(sn) == 2
    reset_pv_below_streak(sn)
    assert bump_pv_below_streak(sn) == 1
    clear_device_state(sn)


def test_hourly_bucket_all_pv_below():
    b = HourlyPvSlBucket()
    b.record(True)
    b.record(True)
    assert b.all_pv_below() is True
    b.record(False)
    assert b.all_pv_below() is False


def test_yesterday_hour_skip_probe():
    sn = "2601051092"
    clear_device_state(sn)
    today = date(2026, 6, 30)
    yesterday = date(2026, 6, 29)
    when = datetime(2026, 6, 29, 14, 30, tzinfo=KYIV)
    record_hourly_sample(sn, when, True)
    record_hourly_sample(sn, when.replace(minute=35), True)
    prune_hourly_cache(sn, today, yesterday)
    assert yesterday_hour_all_pv_below(sn, 14, min_samples=2) is True
    clear_device_state(sn)


def test_prune_hourly_cache_drops_older_than_yesterday():
    sn = "2601051093"
    clear_device_state(sn)
    today = date(2026, 6, 30)
    yesterday = date(2026, 6, 29)
    old = datetime(2026, 6, 27, 10, 0, tzinfo=KYIV)
    record_hourly_sample(sn, old, True)
    prune_hourly_cache(sn, today, yesterday)
    assert yesterday_hour_all_pv_below(sn, 10, min_samples=1) is False
    clear_device_state(sn)
