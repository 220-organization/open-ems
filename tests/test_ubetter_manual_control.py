"""Ubetter run-strategy bodies (Open API v1, V2.1 nested blocks)."""

from app import settings
from app.ubetter_api import (
    _CHARGE_CTRL_CHARGE,
    _CHARGE_CTRL_DISCHARGE,
    _CHARGE_CTRL_IDLE,
    _STRATEGY_PEAK_SHAVING,
    _live_strategy_code,
    _manual_run_strategy_body,
    _settings_run_strategy_body,
    _settings_strategy_code,
)

_PEAK = {
    "strategy": 3,
    "peakValley": {
        "chargeSoc": 98,
        "dischargeSoc": 10,
        "chargePower": 50.0,
        "dischargePower": 50.0,
        "allowChargeInValley": 0,
    },
    "slots": [
        {
            "startTime": "09:49:00",
            "endTime": "23:59:00",
            "mode": 1,
            "power": 110.0,
            "price": 1.0,
            "chargeSocLimit": 0,
        }
    ],
}


def test_charge_on_peak_shaving_keeps_strategy_and_updates_open_slot():
    body, reason = _manual_run_strategy_body(
        current=_PEAK,
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=30,
        discharge_soc=10,
        for_charge=True,
        charge_power_kw=50,
        now_hms="14:20:00",
    )
    assert reason is None
    assert body["strategy"] == _STRATEGY_PEAK_SHAVING
    assert "chargeCtrl" not in body
    assert body["peakValley"]["chargeSoc"] == 30
    assert body["peakValley"]["chargePower"] == 50.0
    assert body["peakValley"]["dischargePower"] == 50.0
    assert body["peakValley"]["allowChargeInValley"] == 0
    assert len(body["slots"]) == 1
    slot = body["slots"][0]
    assert slot["startTime"] == "09:49:00"
    assert slot["endTime"] == "23:59:00"
    assert slot["mode"] == _CHARGE_CTRL_CHARGE
    assert slot["power"] == 50.0
    assert slot["price"] == 1.0
    assert slot["chargeSocLimit"] == 30


def test_charge_uses_default_power_inside_peak_valley_only():
    body, reason = _manual_run_strategy_body(
        current={"strategy": 3, "peakValley": {"dischargePower": 40}},
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=95,
        discharge_soc=10,
        for_charge=True,
        now_hms="12:00:00",
    )
    assert reason is None
    assert body["peakValley"]["chargePower"] == float(settings.UBETTER_MANUAL_POWER_KW)
    assert body["peakValley"]["dischargePower"] == 40
    assert "chargePower" not in body
    assert body["slots"][0]["startTime"] == "12:00:00"
    assert body["slots"][0]["endTime"] == "00:00:00"
    assert body["slots"][0]["mode"] == _CHARGE_CTRL_CHARGE


def test_discharge_inserts_a_slot_without_dropping_later_windows():
    body, reason = _manual_run_strategy_body(
        current={
            "strategy": 3,
            "peakValley": {"chargeSoc": 98, "dischargeSoc": 10},
            "slots": [
                {"startTime": "18:00:00", "endTime": "22:00:00", "mode": 2, "power": 40}
            ],
        },
        charge_ctrl=_CHARGE_CTRL_DISCHARGE,
        charge_soc=98,
        discharge_soc=20,
        power_kw=30.0,
        for_charge=False,
        now_hms="10:00:00",
    )
    assert reason is None
    assert body["peakValley"]["dischargePower"] == 30.0
    assert "chargePower" not in body["peakValley"]
    assert body["slots"][0] == {
        "startTime": "10:00:00",
        "endTime": "18:00:00",
        "mode": _CHARGE_CTRL_DISCHARGE,
        "power": 30.0,
        "dischargeSocLimit": 20,
    }
    assert body["slots"][1]["startTime"] == "18:00:00"
    assert body["slots"][1]["mode"] == 2
    assert body["slots"][1]["power"] == 40


def test_idle_on_peak_shaving_sets_the_open_slot_to_idle():
    body, reason = _manual_run_strategy_body(
        current=_PEAK,
        charge_ctrl=_CHARGE_CTRL_IDLE,
        charge_soc=95,
        discharge_soc=10,
        for_charge=True,
        include_power=False,
        now_hms="14:20:00",
    )
    assert reason is None
    assert body["strategy"] == _STRATEGY_PEAK_SHAVING
    assert body["peakValley"]["chargePower"] == 50.0
    assert body["slots"][0]["mode"] == _CHARGE_CTRL_IDLE
    assert body["slots"][0]["power"] == 0
    assert body["slots"][0]["price"] == 1.0


def test_manual_strategy_uses_charge_ctrl_and_no_slots():
    body, reason = _manual_run_strategy_body(
        current={"strategy": 0, "manual": {"chargeCtrl": 0, "dischargePower": 20}},
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=98,
        discharge_soc=10,
        for_charge=True,
        charge_power_kw=40,
        now_hms="14:20:00",
    )
    assert reason is None
    assert body == {
        "strategy": 0,
        "manual": {
            "chargeCtrl": _CHARGE_CTRL_CHARGE,
            "dischargePower": 20,
            "chargeSoc": 98,
            "dischargeSoc": 10,
            "chargePower": 40.0,
        },
    }


def test_self_consumption_updates_soc_only():
    body, reason = _manual_run_strategy_body(
        current={"strategy": 5, "selfConsumption": {"chargeSoc": 100, "dischargeSoc": 15}},
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=90,
        discharge_soc=12,
        for_charge=True,
        charge_power_kw=40,
        discharge_power_kw=35,
        now_hms="14:20:00",
    )
    assert reason is None
    assert body == {"strategy": 5, "selfConsumption": {"chargeSoc": 90, "dischargeSoc": 12}}


def test_ai_auto_does_not_send_slots():
    body, reason = _manual_run_strategy_body(
        current={"strategy": 6, "aiAuto": {"aiEnergySource": 1, "chargePower": 40}},
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=95,
        discharge_soc=10,
        for_charge=True,
        include_power=False,
        now_hms="14:20:00",
    )
    assert reason is None
    assert body["strategy"] == 6
    assert body["aiAuto"]["aiEnergySource"] == 1
    assert body["aiAuto"]["chargeSoc"] == 95
    assert "slots" not in body


def test_backup_discharge_is_rejected():
    body, reason = _manual_run_strategy_body(
        current={"strategy": 1, "backup": {"chargeSoc": 100, "chargePower": 20}},
        charge_ctrl=_CHARGE_CTRL_DISCHARGE,
        charge_soc=100,
        discharge_soc=10,
        for_charge=False,
        now_hms="14:20:00",
    )
    assert body is None
    assert reason == "backup_charge_only"


def test_backup_charge_has_no_slots():
    body, reason = _manual_run_strategy_body(
        current={"strategy": 1, "backup": {"chargeSoc": 80}},
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=100,
        discharge_soc=10,
        for_charge=True,
        charge_power_kw=20,
        now_hms="14:20:00",
    )
    assert reason is None
    assert body == {"strategy": 1, "backup": {"chargeSoc": 100, "chargePower": 20.0}}


def test_transformer_expansion_can_take_a_slot():
    body, reason = _manual_run_strategy_body(
        current={"strategy": 7, "transformerExpand": {"chargePower": 30, "dischargePower": 80}},
        charge_ctrl=_CHARGE_CTRL_DISCHARGE,
        charge_soc=90,
        discharge_soc=20,
        for_charge=False,
        discharge_power_kw=80,
        now_hms="09:00:00",
    )
    assert reason is None
    assert body["strategy"] == 7
    assert body["transformerExpand"]["dischargePower"] == 80.0
    assert body["slots"][0]["mode"] == _CHARGE_CTRL_DISCHARGE
    assert body["slots"][0]["power"] == 80.0


def test_live_strategy_code_keeps_the_mode_already_set():
    assert _live_strategy_code(4) == 4
    assert _live_strategy_code(6) == 6
    assert _live_strategy_code(7) == 7
    assert _live_strategy_code(None) is None
    assert _live_strategy_code(8) is None
    assert _settings_strategy_code(2) is None
    assert _settings_strategy_code(6) == 6


def test_settings_peak_shaving_keeps_flags_and_does_not_send_slots():
    body = _settings_run_strategy_body(
        _PEAK,
        strategy=3,
        charge_power_kw=60,
        discharge_power_kw=45,
    )
    assert body["strategy"] == 3
    assert "slots" not in body
    assert "chargeCtrl" not in body
    assert body["peakValley"]["chargeSoc"] == 98
    assert body["peakValley"]["dischargeSoc"] == 10
    assert body["peakValley"]["chargePower"] == 60.0
    assert body["peakValley"]["dischargePower"] == 45.0
    assert body["peakValley"]["allowChargeInValley"] == 0


def test_settings_backup_sends_charge_power_only():
    body = _settings_run_strategy_body(
        _PEAK,
        strategy=1,
        charge_power_kw=20,
        discharge_power_kw=45,
    )
    assert body == {"strategy": 1, "backup": {"chargeSoc": 98, "chargePower": 20.0}}


def test_settings_self_consumption_has_no_power():
    body = _settings_run_strategy_body(
        _PEAK,
        strategy=5,
        charge_power_kw=50,
        discharge_power_kw=50,
    )
    assert body == {"strategy": 5, "selfConsumption": {"chargeSoc": 98, "dischargeSoc": 10}}


def test_settings_ai_auto_stays_ai_auto():
    body = _settings_run_strategy_body(
        {"strategy": 6, "aiAuto": {"aiEnergySource": 1, "chargeSoc": 90, "dischargeSoc": 15}},
        strategy=6,
        charge_power_kw=40,
        discharge_power_kw=35,
    )
    assert body["strategy"] == 6
    assert body["aiAuto"]["aiEnergySource"] == 1
    assert body["aiAuto"]["chargePower"] == 40.0
    assert body["aiAuto"]["dischargePower"] == 35.0
    assert body["aiAuto"]["chargeSoc"] == 90
    assert "slots" not in body


def test_manual_run_strategy_body_clamps_soc():
    body, reason = _manual_run_strategy_body(
        current={"strategy": 3, "peakValley": {}},
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=150,
        discharge_soc=-5,
        for_charge=True,
        include_power=False,
        now_hms="12:00:00",
    )
    assert reason is None
    assert body["peakValley"]["chargeSoc"] == 100
    assert body["peakValley"]["dischargeSoc"] == 0
    assert body["slots"][0]["chargeSocLimit"] == 100


def test_ubetter_command_password():
    from app.routers.ubetter_proxy import ubetter_command_password_ok

    assert ubetter_command_password_ok("3759") is True
    assert ubetter_command_password_ok(" 3759 ") is True
    assert ubetter_command_password_ok("3758") is False
    assert ubetter_command_password_ok("") is False
    assert ubetter_command_password_ok(None) is False
