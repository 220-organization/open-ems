"""Huawei getDevRealKpi power normalization (kW vs W, meter vs inverter)."""

from app.huawei_api import (
    _active_power_w_from_dev_dim,
    _apply_huawei_power_flow_repairs,
    _normalize_maybe_kw_to_w,
    _normalize_meter_scale_if_implausible,
    _parse_huawei_power_flow_from_dims,
    _repair_huawei_power_flow_triplet,
)


def test_inverter_active_power_kw_to_w():
    assert _normalize_maybe_kw_to_w(13.16) == 13_160.0
    assert _normalize_maybe_kw_to_w(12.925) == 12_925.0


def test_meter_small_watts_not_scaled_to_kw():
    """10я База1: meter active_power=-240 W must not become -240 kW."""
    inv_w = 13_160.0
    assert _normalize_maybe_kw_to_w(-240.0, reference_w=inv_w) == -240.0
    assert _normalize_maybe_kw_to_w(-0.352, reference_w=inv_w) == -352.0


def test_meter_active_power_uses_inverter_reference():
    dim = {"active_power": -240.0}
    inv_dim = {"active_power": 13.16, "mppt_power": 12.925}
    inv_w = _active_power_w_from_dev_dim(inv_dim)
    meter_w = _active_power_w_from_dev_dim(dim, reference_w=inv_w)
    assert inv_w == 13_160.0
    assert meter_w == -240.0


def test_10ya_baza1_power_flow_numbers():
    """Regression: fake 240 kW grid / 253 kW load from x1000 meter misread."""
    inv_w = 13_160.0
    meter_w = _active_power_w_from_dev_dim({"active_power": -240.0}, reference_w=inv_w)
    meter_w = _normalize_meter_scale_if_implausible(meter_w, inv_w)
    grid_ui = -float(meter_w)
    load_w = max(0.0, inv_w - meter_w)
    assert meter_w == -240.0
    assert grid_ui == 240.0
    assert 13_000 <= load_w <= 14_000


def test_normalize_meter_downscales_legacy_240kw_spike():
    inv_w = 13_160.0
    fixed = _normalize_meter_scale_if_implausible(-240_000.0, inv_w)
    assert fixed == -240.0


def test_parse_power_flow_from_dims_all_plants():
    inv_dim = {"active_power": 13.16, "mppt_power": 12.925}
    meter_dim = {"active_power": -240.0}
    stored = _parse_huawei_power_flow_from_dims(meter_dim, inv_dim, for_storage=True)
    assert stored["pvPowerW"] == 12_925.0
    assert stored["gridPowerW"] == 240.0
    assert 13_000 <= stored["loadPowerW"] <= 14_000
    live = _parse_huawei_power_flow_from_dims(meter_dim, inv_dim, for_storage=False)
    assert live["gridPowerW"] == 0.0


def test_repair_legacy_cached_fake_load():
    pv, grid, load = _repair_huawei_power_flow_triplet(13_160.0, 240_000.0, 252_930.0)
    assert grid == 240.0
    assert 13_000 <= load <= 14_000


def test_apply_repairs_on_cached_body():
    body = {
        "ok": True,
        "pvPowerW": 13_160.0,
        "gridPowerW": 240_000.0,
        "loadPowerW": 252_930.0,
    }
    fixed = _apply_huawei_power_flow_repairs(body)
    assert fixed["gridPowerW"] == 240.0
    assert 13_000 <= fixed["loadPowerW"] <= 14_000
