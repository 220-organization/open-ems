"""Ubetter manual charge/discharge run-strategy body (Open API v1)."""

from app import settings
from app.ubetter_api import (
    _CHARGE_CTRL_CHARGE,
    _CHARGE_CTRL_DISCHARGE,
    _CHARGE_CTRL_IDLE,
    _STRATEGY_MANUAL,
    _manual_run_strategy_body,
)


def test_manual_run_strategy_body_charge_defaults():
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=95,
        discharge_soc=10,
        for_charge=True,
    )
    assert body["strategy"] == _STRATEGY_MANUAL
    assert body["chargeCtrl"] == _CHARGE_CTRL_CHARGE
    assert body["chargeSoc"] == 95
    assert body["dischargeSoc"] == 10
    assert body["chargePower"] == float(settings.UBETTER_MANUAL_POWER_KW)
    assert "dischargePower" not in body


def test_manual_run_strategy_body_discharge_custom_power():
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_DISCHARGE,
        charge_soc=90,
        discharge_soc=20,
        power_kw=30.0,
        for_charge=False,
    )
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
    assert body["chargeCtrl"] == _CHARGE_CTRL_IDLE
    assert "chargePower" not in body
    assert "dischargePower" not in body


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
