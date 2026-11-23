"""Ubetter detail → power-flow mapping (SoC, battery, energyFlow meters)."""

from app.ubetter_api import (
    _extract_detail_group_summary,
    _map_detail_to_power_flow,
    _map_summary_to_power_flow,
    _off_grid_from_energy_flow,
)

DETAIL_FIXTURE = {
    "viewScopeResolved": "standalone",
    "groupRow": {
        "summary": {
            "soc": 27.0,
            "capacity": 160,
            "online": True,
            "realtimePower": {
                "realTimePower": 0.0,
                "pcsPower": 0.04,
                "batteryPower": -0.26,
                "powerTimestamp": "1783148377",
            },
            "energyFlow": {
                "pvData": {"power": 0.0, "configured": True},
                "loadData": {"power": 0.0, "configured": True},
                "gridData": {"power": 0.0, "configured": False},
            },
        }
    },
}

SUMMARY_FALLBACK = {
    "sn": "UBT_160kWh_test",
    "soc": 0,
    "soh": 98,
    "batteryVoltage": 512.0,
    "batteryCurrent": 1.2,
    "batteryTemperature": 25.0,
    "reportTime": "1783148645",
    "pvTotalPower": 0.0,
    "gridActivePower": 0.0,
    "loadActivePower": 0.0,
    "batteryPower": 0.0,
}


def test_extract_detail_group_summary():
    assert _extract_detail_group_summary(DETAIL_FIXTURE) is DETAIL_FIXTURE["groupRow"]["summary"]
    assert _extract_detail_group_summary({"singleDevice": {"summary": {"soc": 11.0}}}) == {"soc": 11.0}
    assert _extract_detail_group_summary({}) is None


def test_map_detail_to_power_flow_user_fixture():
    summary = _extract_detail_group_summary(DETAIL_FIXTURE)
    body = _map_detail_to_power_flow("UBT_160kWh_test", summary, SUMMARY_FALLBACK)
    assert body["ok"] is True
    assert body["socPercent"] == 27.0
    assert body["batteryPowerW"] == 260.0
    assert body["pvPowerW"] == 0.0
    assert body["loadPowerW"] == 0.0
    assert body["gridPowerW"] == 0.0
    assert body["reportTimeMs"] == 1783148377
    assert body["sohPercent"] == 98
    assert body["batteryVoltageV"] == 512.0
    assert body["offGrid"] is None


def test_map_summary_fallback_when_detail_missing():
    body = _map_summary_to_power_flow("UBT_160kWh_test", SUMMARY_FALLBACK)
    assert body["socPercent"] == 0.0
    assert body["batteryPowerW"] == -0.0
    assert body["offGrid"] is None


def test_grid_connected_false_is_off_grid():
    summary = _extract_detail_group_summary(DETAIL_FIXTURE)
    island = {
        **summary,
        "energyFlow": {
            **summary["energyFlow"],
            "gridData": {
                "power": 0.0,
                "configured": False,
                "gridConnected": False,
                "gridSwitchOpen": False,
            },
        },
    }
    body = _map_detail_to_power_flow("UBT0420215200730007", island, SUMMARY_FALLBACK)
    assert body["offGrid"] is True
    assert body["gridPowerW"] == 0.0
    assert body["loadPowerW"] == 0.0


def test_grid_connected_true_stays_on_grid():
    assert _off_grid_from_energy_flow({"gridData": {"gridConnected": True, "power": 1.2}}) is False
    assert _off_grid_from_energy_flow({"gridData": {"power": 0.0}}) is None
    assert _off_grid_from_energy_flow(None) is None
