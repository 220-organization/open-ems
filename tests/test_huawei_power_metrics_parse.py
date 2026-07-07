"""Huawei getDevRealKpi power normalization (kW vs W, meter vs inverter)."""

from app.huawei_api import (
    _active_power_w_from_dev_dim,
    _apply_huawei_power_flow_repairs,
    _huawei_live_kpi_cache_fresh,
    _normalize_maybe_kw_to_w,
    _normalize_meter_scale_if_implausible,
    _parse_huawei_power_flow_from_dims,
    _pick_all_inverters_from_rows,
    _repair_huawei_power_flow_triplet,
    _sum_inverter_power_from_dims,
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
    stored = _parse_huawei_power_flow_from_dims(meter_dim, [inv_dim], for_storage=True)
    assert stored["pvPowerW"] == 12_925.0
    assert stored["gridPowerW"] == 240.0
    assert 13_000 <= stored["loadPowerW"] <= 14_000
    live = _parse_huawei_power_flow_from_dims(meter_dim, [inv_dim], for_storage=False)
    assert live["gridPowerW"] == 0.0


def test_pick_all_inverters_from_rows():
    rows = [
        {"id": "1001", "devTypeId": 1},
        {"id": "1002", "devTypeId": 1},
        {"id": "2001", "devTypeId": 47},
        {"id": "1001", "devTypeId": 1},
    ]
    pairs = _pick_all_inverters_from_rows(rows)
    assert pairs == [("1001", 1), ("1002", 1)]


def test_10ya_baza1_multi_inverter_matches_fusionsolar():
    """NE=256081648: ~50 kW PV / ~3.7 kW grid / ~54 kW load — sum all inverters, not one."""
    inv_dims = [
        {"active_power": 12.52, "mppt_power": 12.519},
        {"active_power": 12.51, "mppt_power": 12.518},
        {"active_power": 12.52, "mppt_power": 12.519},
        {"active_power": 12.52, "mppt_power": 12.518},
    ]
    pv_sum, inv_sum = _sum_inverter_power_from_dims(inv_dims)
    assert 49_000 <= pv_sum <= 51_000
    assert 49_000 <= inv_sum <= 51_000

    meter_dim = {"active_power": -3.696}
    stored = _parse_huawei_power_flow_from_dims(meter_dim, inv_dims, for_storage=True)
    assert 49_000 <= stored["pvPowerW"] <= 51_000
    assert 3_000 <= stored["gridPowerW"] <= 4_500
    assert 52_000 <= stored["loadPowerW"] <= 55_000
    assert abs(stored["loadPowerW"] - (stored["pvPowerW"] + stored["gridPowerW"])) < 2_000


def test_inverter_pairs_for_power_flow_uses_dev_list_not_cached_single():
    from app.huawei_api import _inverter_pairs_for_power_flow

    rows = [
        {"id": "1001", "devTypeId": 1},
        {"id": "1002", "devTypeId": 1},
    ]
    pairs = _inverter_pairs_for_power_flow(("1001", 1), rows)
    assert pairs == [("1001", 1), ("1002", 1)]

    # Cached single pair with empty dev list — legacy fallback (one inverter only).
    pairs_cached = _inverter_pairs_for_power_flow(("1001", 1), [])
    assert pairs_cached == [("1001", 1)]


def test_10ya_baza1_two_inverter_partial_cloud():
    """FusionSolar ~21 kW PV when only ~2 of 4 strings produce strongly."""
    inv_dims = [
        {"active_power": 12.95, "mppt_power": 12.948},
        {"active_power": 8.34, "mppt_power": 8.336},
        {"active_power": 0.0, "mppt_power": 0.0},
        {"active_power": 0.0, "mppt_power": 0.0},
    ]
    meter_dim = {"active_power": -17.168}
    stored = _parse_huawei_power_flow_from_dims(meter_dim, inv_dims, for_storage=True)
    assert 20_000 <= stored["pvPowerW"] <= 22_000
    assert 16_000 <= stored["gridPowerW"] <= 18_500
    assert 37_000 <= stored["loadPowerW"] <= 40_000


def test_huawei_live_kpi_cache_ttl_ten_minutes():
    now = 1_000_000.0
    assert _huawei_live_kpi_cache_fresh(now - 599.0, now=now) is True
    assert _huawei_live_kpi_cache_fresh(now - 600.0, now=now) is True
    assert _huawei_live_kpi_cache_fresh(now - 601.0, now=now) is False
    assert _huawei_live_kpi_cache_fresh(now - 29_000.0, now=now) is False


def test_huawei_sample_age_ok_stale_display_window():
    from app.huawei_api import _huawei_sample_age_ok

    now = 1_000_000.0
    assert _huawei_sample_age_ok(now - 3500.0, 3600.0, now=now) is True
    assert _huawei_sample_age_ok(now - 3700.0, 3600.0, now=now) is False


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


def test_pick_snapshot_station_codes_round_robin():
    from app.huawei_power_service import pick_snapshot_station_codes

    codes = ["NE=A", "NE=B"]
    assert pick_snapshot_station_codes(codes, rr_index=0) == ["NE=A"]
    assert pick_snapshot_station_codes(codes, rr_index=1) == ["NE=B"]
    assert pick_snapshot_station_codes(codes, rr_index=2) == ["NE=A"]
    assert pick_snapshot_station_codes(codes, rr_index=0, only_station="NE=B") == ["NE=B"]
    assert pick_snapshot_station_codes([], rr_index=0) == []


def test_inverter_only_load_without_meter():
    inv_dim = {"active_power": 25.0, "mppt_power": 24.5}
    metrics = _parse_huawei_power_flow_from_dims({}, [inv_dim], for_storage=True)
    assert metrics["pvPowerW"] == 24_500.0
    assert metrics["gridPowerW"] is None
    assert metrics["loadPowerW"] == 25_000.0
