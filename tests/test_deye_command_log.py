"""Titles for Deye commands stored in the inverter events list."""

from app.deye_command_log import deye_command_title


def test_discharge_and_charge_titles_use_soc_targets():
    assert (
        deye_command_title(
            "discharge",
            {"ok": True, "startSoc": 40.2, "targetSoc": 20},
        )
        == "Discharge now · SoC 40.2% → 20%"
    )
    assert (
        deye_command_title(
            "charge",
            {"ok": True, "startSoc": 18, "targetSoc": 28},
        )
        == "Charge now · SoC 18% → 28%"
    )


def test_power_limit_title_uses_kilowatts():
    assert (
        deye_command_title(
            "power-limits",
            {"ok": True, "maxSolarPowerW": 5000, "maxChargePowerW": 3000, "maxDischargePowerW": 4000},
        )
        == "Power limits · solar 5 kW · charge 3 kW · discharge 4 kW"
    )


def test_preference_titles():
    assert (
        deye_command_title(
            "peak-auto-discharge",
            {"ok": True, "enabled": True, "dischargeSocDeltaPct": 80},
        )
        == "Peak DAM discharge on · till SoC 80%"
    )
    assert (
        deye_command_title(
            "night-charge",
            {"ok": True, "nightChargeEnabled": False, "chargeSocDeltaPct": 10},
        )
        == "Night charge off · +10%"
    )
    assert deye_command_title("gen-port", {"ok": True, "genOnGridAlwaysOn": True}) == (
        "Gen port On Grid always on: on"
    )
