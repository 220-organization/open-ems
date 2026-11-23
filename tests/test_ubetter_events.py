"""Ubetter faultList alarm normalization."""

from app.ubetter_api import alarms_from_fault_list, normalize_ubetter_alarm


PCS_FAILURE = {
    "id": "29042741996429785",
    "alarmName": "Pcs通讯失败",
    "alarmNameEn": "PCS Communication Failure",
    "alarmLevel": 2,
    "alarmSource": "设备端-事件",
    "eventStatus": 1,
    "isFault": True,
    "isCurrentAlarm": True,
    "time": "1795436246000",
}


def test_normalize_current_alarm_uses_english_title_and_unix_seconds():
    item = normalize_ubetter_alarm(PCS_FAILURE)
    assert item["id"] == "29042741996429785"
    assert item["title"] == "PCS Communication Failure"
    assert item["name"] == "Pcs通讯失败"
    assert item["active"] is True
    assert item["startTime"] == 1795436246
    assert item["level"] == 2
    assert item["isFault"] is True


def test_cleared_alarm_is_inactive():
    row = {**PCS_FAILURE, "isCurrentAlarm": False}
    assert normalize_ubetter_alarm(row)["active"] is False


def test_missing_identity_is_dropped():
    assert normalize_ubetter_alarm({}) is None
    assert normalize_ubetter_alarm("nope") is None
    assert alarms_from_fault_list(None) == []
    assert alarms_from_fault_list([{}, PCS_FAILURE, PCS_FAILURE]) == [
        normalize_ubetter_alarm(PCS_FAILURE)
    ]
