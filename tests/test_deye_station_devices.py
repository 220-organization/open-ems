"""Which Deye listWithDevice rows become power-flow sources."""

from app.deye_api import _devices_from_station, _station_created_at_unix


def _dev(sn: str, device_type: str) -> dict:
    return {"deviceSn": sn, "deviceType": device_type}


def test_keeps_inverters_and_feed_in_limit_not_battery():
    station = {
        "deviceListItems": [
            _dev("111", "COLLECTOR"),
            _dev("222", "INVERTER"),
            _dev("333", "BATTERY"),
            _dev("444", "FEED_IN_LIMIT"),
        ]
    }
    sns = [d["deviceSn"] for d in _devices_from_station(station)]
    assert sns == ["222", "444"]


def test_pcs_only_plant_uses_pcs_not_battery_or_collector():
    """Commercial BESS such as station 61942715 has no INVERTER rows."""
    station = {
        "deviceListItems": [
            _dev("3580064223", "COLLECTOR"),
            _dev("2512011265", "PCS"),
            _dev("2512011265M01", "BATTERY"),
            _dev("2510100262", "PCS"),
        ]
    }
    sns = [d["deviceSn"] for d in _devices_from_station(station)]
    assert sns == ["2512011265", "2510100262"]


def test_station_created_at_is_unix_seconds():
    assert _station_created_at_unix({"createdDate": 1794149547.0}) == 1794149547
    assert _station_created_at_unix({"createdDate": 1794149547000}) == 1794149547
    assert _station_created_at_unix({}) is None
    assert _station_created_at_unix({"createdDate": "nope"}) is None


def test_pcs_ignored_when_an_inverter_exists():
    station = {
        "deviceListItems": [
            _dev("100", "INVERTER"),
            _dev("200", "PCS"),
        ]
    }
    sns = [d["deviceSn"] for d in _devices_from_station(station)]
    assert sns == ["100"]
