"""Manual solar / battery limit payloads. Automation still must not send maxSolarPower."""

from __future__ import annotations

import unittest

from app.deye_manual_limits import (
    battery_current_update_body,
    battery_voltage_v_from_latest,
    kw_to_watts,
    limits_view,
    registers_from_dynamic_read,
    solar_power_update_body,
    watts_to_charge_amps,
)


class TestManualPowerLimits(unittest.TestCase):
    def test_solar_body_is_max_solar_power_watts(self) -> None:
        body = solar_power_update_body("2503291033", kw_to_watts(80))
        self.assertEqual(body["powerType"], "MAX_SOLAR_POWER")
        self.assertEqual(body["value"], 80_000)
        self.assertNotIn("maxSolarPower", body)

    def test_battery_bodies_are_current_not_watts(self) -> None:
        charge = battery_current_update_body("2503291033", "MAX_CHARGE_CURRENT", 70)
        discharge = battery_current_update_body("2503291033", "MAX_DISCHARGE_CURRENT", 80)
        self.assertEqual(charge["paramterType"], "MAX_CHARGE_CURRENT")
        self.assertEqual(charge["value"], 70)
        self.assertEqual(discharge["paramterType"], "MAX_DISCHARGE_CURRENT")
        self.assertEqual(discharge["value"], 80)

    def test_kw_converts_with_battery_voltage(self) -> None:
        self.assertEqual(watts_to_charge_amps(48_000, 800.0), 60)
        with self.assertRaises(ValueError):
            watts_to_charge_amps(48_000, 0)

    def test_voltage_from_latest_and_kw_view(self) -> None:
        latest = {
            "deviceDataList": [
                {
                    "dataList": [
                        {"key": "BatteryVoltage", "value": "640.0", "unit": "V"},
                        {"key": "BatteryPower", "value": "-1000", "unit": "W"},
                    ]
                }
            ]
        }
        voltage = battery_voltage_v_from_latest(latest)
        self.assertEqual(voltage, 640.0)
        view = limits_view(
            {"maxSolarPower": 10000},
            {"maxChargeCurrent": 50, "maxDischargeCurrent": 60},
            voltage,
        )
        self.assertEqual(view["maxSolarPowerW"], 10000)
        self.assertEqual(view["maxChargePowerW"], 32_000)
        self.assertEqual(view["maxDischargePowerW"], 38_400)

    def test_hybrid_registers_from_dynamic_read(self) -> None:
        order = {
            "status": 666,
            "analysisResult": '{"0035":10000,"00D2":19,"00D3":39,"00F5":10000}',
        }
        regs = registers_from_dynamic_read(order)
        self.assertEqual(regs["0035"], 10000)
        self.assertEqual(regs["00D2"], 19)
        self.assertEqual(regs["00D3"], 39)
        view = limits_view(
            {"maxSolarPower": regs["0035"]},
            {"maxChargeCurrent": regs["00D2"], "maxDischargeCurrent": regs["00D3"]},
            52.39,
        )
        self.assertEqual(view["maxSolarPowerW"], 10000)
        self.assertEqual(view["maxChargePowerW"], 995)
        self.assertEqual(view["maxDischargePowerW"], 2043)


if __name__ == "__main__":
    unittest.main()
