"""Ubetter faultList alarm normalization and command event lines."""

from datetime import datetime, timezone

from app.models import UbetterEvent
from app.ubetter_api import alarms_from_fault_list, normalize_ubetter_alarm
from app.ubetter_event_service import event_row_to_api, format_command_event_title


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


def test_command_event_title_matches_the_cloud_summary():
    title = format_command_event_title(
        {
            "strategy": 3,
            "peakValley": {
                "chargeSoc": 98,
                "dischargeSoc": 10,
                "chargePower": 100,
                "dischargePower": 50,
            },
            "slots": [
                {
                    "startTime": "09:49:00",
                    "endTime": "23:59:00",
                    "mode": 1,
                    "power": 110,
                }
            ],
        }
    )
    assert title == (
        "PUT run-strategy → strategy=3 · chargeSoc=98% · dischargeSoc=10%"
        " · chargePower=100 kW · dischargePower=50 kW"
        " · slots=09:49:00-23:59:00 charge 110 kW"
    )


def test_command_row_is_not_an_active_alarm():
    row = UbetterEvent(
        device_sn="UBT0420215200730007",
        alarm_id="cmd-abc",
        alarm_name_en="PUT run-strategy → strategy=3",
        alarm_source="command",
        is_current=False,
        occurred_at=datetime(2026, 11, 24, 13, 41, tzinfo=timezone.utc),
        detail='{"command": {"ok": true}}',
    )
    item = event_row_to_api(row)
    assert item["kind"] == "command"
    assert item["active"] is False
    assert item["title"] == "PUT run-strategy → strategy=3"
    assert item["detail"] == '{"command": {"ok": true}}'


def test_missing_identity_is_dropped():
    assert normalize_ubetter_alarm({}) is None
    assert normalize_ubetter_alarm("nope") is None
    assert alarms_from_fault_list(None) == []
    assert alarms_from_fault_list([{}, PCS_FAILURE, PCS_FAILURE]) == [
        normalize_ubetter_alarm(PCS_FAILURE)
    ]
