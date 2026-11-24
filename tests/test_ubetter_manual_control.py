"""Ubetter manual charge/discharge run-strategy body (Open API v1)."""

from app import settings
from app.ubetter_api import (
    _CHARGE_CTRL_CHARGE,
    _CHARGE_CTRL_DISCHARGE,
    _CHARGE_CTRL_IDLE,
    _FULL_DAY_END,
    _FULL_DAY_START,
    _STRATEGY_PEAK_SHAVING,
    _live_strategy_code,
    _manual_run_strategy_body,
    _settings_run_strategy_body,
)


def test_manual_run_strategy_body_charge_defaults():
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=95,
        discharge_soc=10,
        for_charge=True,
    )
    assert body["strategy"] == _STRATEGY_PEAK_SHAVING
    assert body["chargeCtrl"] == _CHARGE_CTRL_CHARGE
    assert body["chargeSoc"] == 95
    assert body["dischargeSoc"] == 10
    assert body["chargePower"] == float(settings.UBETTER_MANUAL_POWER_KW)
    assert "dischargePower" not in body
    assert body["startTime"] == _FULL_DAY_START
    assert body["endTime"] == _FULL_DAY_END
    assert body["startChargeTime"] == _FULL_DAY_START
    assert body["endChargeTime"] == _FULL_DAY_END
    assert body["startDischargeTime"] == _FULL_DAY_START
    assert body["endDischargeTime"] == _FULL_DAY_END


def test_manual_run_strategy_body_discharge_custom_power():
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_DISCHARGE,
        charge_soc=90,
        discharge_soc=20,
        power_kw=30.0,
        for_charge=False,
    )
    assert body["strategy"] == _STRATEGY_PEAK_SHAVING
    assert body["chargeCtrl"] == _CHARGE_CTRL_DISCHARGE
    assert body["dischargePower"] == 30.0
    assert "chargePower" not in body


def test_manual_run_strategy_body_idle_no_power():
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_IDLE,
        charge_soc=95,
        discharge_soc=10,
        for_charge=True,
        include_power=False,
    )
    assert body["strategy"] == _STRATEGY_PEAK_SHAVING
    assert body["chargeCtrl"] == _CHARGE_CTRL_IDLE
    assert "chargePower" not in body
    assert "dischargePower" not in body


def test_ubetter_command_password():
    from app.routers.ubetter_proxy import ubetter_command_password_ok

    assert ubetter_command_password_ok("3759") is True
    assert ubetter_command_password_ok(" 3759 ") is True
    assert ubetter_command_password_ok("3758") is False
    assert ubetter_command_password_ok("") is False
    assert ubetter_command_password_ok(None) is False


def test_live_strategy_code_keeps_the_mode_already_set():
    assert _live_strategy_code(4) == 4
    assert _live_strategy_code(6) == 6
    assert _live_strategy_code(None) is None
    assert _live_strategy_code(7) is None


def test_manual_run_strategy_body_keeps_readonly_strategy():
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=98,
        discharge_soc=10,
        for_charge=True,
        strategy=6,
        allow_readonly_strategy=True,
        include_power=False,
    )
    assert body["strategy"] == 6


def test_manual_run_strategy_body_custom_strategy_and_both_powers():
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=98,
        discharge_soc=10,
        for_charge=True,
        strategy=5,
        charge_power_kw=40,
        discharge_power_kw=35,
    )
    assert body["strategy"] == 5
    assert body["chargePower"] == 40.0
    assert body["dischargePower"] == 35.0


def test_settings_run_strategy_body_keeps_charge_ctrl_and_window():
    body = _settings_run_strategy_body(
        {
            "chargeCtrl": 1,
            "chargeSoc": 98,
            "dischargeSoc": 10,
            "startTime": "00:00:00",
            "endTime": "23:59:59",
            "startChargeTime": "00:00:00",
            "endChargeTime": "23:59:59",
            "startDischargeTime": "00:00:00",
            "endDischargeTime": "23:59:59",
            "chargePeriodPeak": 0,
            "aiSeasonMode": 0,
        },
        strategy=4,
        charge_power_kw=60,
        discharge_power_kw=45,
    )
    assert body["strategy"] == 4
    assert body["chargeCtrl"] == 1
    assert body["chargeSoc"] == 98
    assert body["dischargeSoc"] == 10
    assert body["chargePower"] == 60.0
    assert body["dischargePower"] == 45.0
    assert body["startTime"] == _FULL_DAY_START
    assert body["endTime"] == _FULL_DAY_END
    assert body["chargePeriodPeak"] == 0
    assert body["aiSeasonMode"] == 0


def test_settings_run_strategy_body_ai_economic_falls_back_to_peak_shaving():
    body = _settings_run_strategy_body({}, strategy=6, charge_power_kw=50, discharge_power_kw=50)
    assert body["strategy"] == _STRATEGY_PEAK_SHAVING


def test_manual_run_strategy_body_clamps_soc():
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=150,
        discharge_soc=-5,
        for_charge=True,
        include_power=False,
    )
    assert body["chargeSoc"] == 100
    assert body["dischargeSoc"] == 0
