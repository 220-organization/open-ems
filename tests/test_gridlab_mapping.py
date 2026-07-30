"""Unit tests for GridLab live power-flow mapping (no network)."""

from app.gridlab_power_service import is_stale_sample, map_live_power_flow


def _status(**kwargs):
    base = {
        "device_id": 16,
        "name": "BESS 500/1075",
        "soc_percent": 44.0,
        "power_kw": 156.0,
        "is_online": True,
        "timestamp": "2026-07-30T16:16:45Z",
        "data_age_seconds": 2.1,
        "stale": False,
    }
    base.update(kwargs)
    return base


def _meters(*rows):
    return {"device_id": 16, "generated_at": "2026-07-30T16:16:45Z", "meters": list(rows)}


def _meter(mid, role, power_kw, *, virtual=False, stale=False, age=1.0):
    return {
        "id": mid,
        "name": f"meter-{mid}",
        "role": role,
        "is_virtual": virtual,
        "power_kw": power_kw,
        "kwh_import": 100.0,
        "kwh_export": 10.0,
        "timestamp": "2026-07-30T16:16:45Z",
        "data_age_seconds": age,
        "stale": stale,
    }


def test_map_live_signs_discharge_and_import():
    live = map_live_power_flow(
        _status(power_kw=156.0, soc_percent=44.0),
        _meters(
            _meter(21, "pcc", 25.8),
            _meter(23, "production", 80.0),
            _meter(22, "load", 21.9),
            _meter(27, "load", 0.1),
            _meter(28, "load", 0.05),
        ),
    )
    assert live["ok"] is True
    assert live["socPercent"] == 44.0
    assert live["batteryPowerW"] == 156_000.0  # discharge > 0
    assert live["gridPowerW"] == 25_800.0  # import > 0
    assert live["pvPowerW"] == 80_000.0
    assert live["loadPowerW"] == 21_900.0
    assert abs(live["evPowerW"] - 150.0) < 1e-6
    assert live["stale"] is False


def test_map_live_signs_charge_and_export():
    live = map_live_power_flow(
        _status(power_kw=-2.0),
        _meters(
            _meter(21, "pcc", -12.5),
            _meter(23, "production", 40.0),
            _meter(22, "load", 30.0),
        ),
    )
    assert live["batteryPowerW"] == -2_000.0  # charge < 0
    assert live["gridPowerW"] == -12_500.0  # export < 0


def test_null_not_coerced_to_zero():
    live = map_live_power_flow(
        _status(soc_percent=None, power_kw=None),
        _meters(
            _meter(21, "pcc", None),
            _meter(23, "production", None),
            _meter(22, "load", None),
        ),
    )
    assert live["socPercent"] is None
    assert live["batteryPowerW"] is None
    assert live["gridPowerW"] is None
    assert live["pvPowerW"] is None
    assert live["loadPowerW"] is None


def test_persist_fresh_only_drops_stale():
    live = map_live_power_flow(
        _status(stale=True, data_age_seconds=90, power_kw=10.0, soc_percent=50.0),
        _meters(
            _meter(21, "pcc", 5.0, stale=True, age=90),
            _meter(23, "production", 8.0, stale=False, age=1),
            _meter(22, "load", 3.0, stale=False, age=1),
        ),
        persist_fresh_only=True,
    )
    assert live["socPercent"] is None
    assert live["batteryPowerW"] is None
    assert live["gridPowerW"] is None
    assert live["pvPowerW"] == 8_000.0
    assert live["loadPowerW"] == 3_000.0
    assert live["stale"] is True


def test_live_keeps_stale_values_with_flag():
    live = map_live_power_flow(
        _status(stale=True, data_age_seconds=90, power_kw=10.0, soc_percent=50.0),
        _meters(_meter(21, "pcc", 5.0), _meter(23, "production", 1.0), _meter(22, "load", 2.0)),
        persist_fresh_only=False,
    )
    assert live["socPercent"] == 50.0
    assert live["batteryPowerW"] == 10_000.0
    assert live["stale"] is True


def test_is_stale_sample_by_age():
    assert is_stale_sample(stale_flag=False, data_age_seconds=61, max_age_sec=60) is True
    assert is_stale_sample(stale_flag=False, data_age_seconds=10, max_age_sec=60) is False
    assert is_stale_sample(stale_flag=True, data_age_seconds=1, max_age_sec=60) is True
