"""Deye device/latest power metric parsing (grid total vs per-phase, load priority)."""

from app.deye_api import (
    _finalize_live_metrics_for_sn,
    _grid_power_signed_watts_from_data_list,
    _load_power_watts_from_data_list,
    _metric_key,
)


def _row(key: str, value: float, unit: str = "W") -> dict:
    return {"key": key, "value": value, "unit": unit}


def test_metric_key_splits_camel_case():
    assert _metric_key("TotalGridPower") == "TOTAL_GRID_POWER"
    assert _metric_key("GridPowerL1") == "GRID_POWER_L1"
    assert _metric_key("UPSLoadPower") == "UPS_LOAD_POWER"


def test_grid_prefers_total_over_single_phase():
    dl = [
        _row("GridPowerL1", 10886.0),
        _row("GridPowerL2", 10894.0),
        _row("GridPowerL3", 10907.0),
        _row("TotalGridPower", 32687.0),
    ]
    assert _grid_power_signed_watts_from_data_list(dl) == 32687.0


def test_grid_sums_phases_when_no_total():
    dl = [
        _row("GridPowerL1", 1000.0),
        _row("GridPowerL2", 2000.0),
        _row("GridPowerL3", 3000.0),
    ]
    assert _grid_power_signed_watts_from_data_list(dl) == 6000.0


def test_load_prefers_ups_over_phase_registers():
    dl = [
        _row("LoadPowerL1", 5000.0),
        _row("LoadPowerL2", 6000.0),
        _row("UPSLoadPower", 21530.0),
        _row("TotalConsumptionPower", 22000.0),
    ]
    assert _load_power_watts_from_data_list(dl) == 21530.0


def test_finalize_derives_grid_when_load_exceeds_reported_supply():
    bat, load_w, pv_w, grid_w, _ = _finalize_live_metrics_for_sn(
        "2601051092",
        140.0,
        13660.0,
        0.0,
        4610.0,
        50.0,
    )
    assert load_w == 13660.0
    assert grid_w == 13660.0 - 140.0
    assert bat == 140.0
    assert pv_w == 0.0


def test_finalize_derives_grid_from_load_when_imbalanced():
    bat, load_w, pv_w, grid_w, _ = _finalize_live_metrics_for_sn(
        "2601051092",
        -130.0,
        21530.0,
        0.0,
        4610.0,
        50.0,
    )
    assert load_w == 21530.0
    assert grid_w == 21530.0 - (-130.0)
    assert bat == -130.0
    assert pv_w == 0.0
