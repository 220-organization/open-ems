"""Manual solar / battery limit payloads. Automation still must not send maxSolarPower."""

from __future__ import annotations

import unittest

from app.deye_api import (
    DeyeOrderFailed,
    _parse_modbus_read_u16s,
    deye_order_failure_is_retryable,
    deye_order_failure_message,
    modbus_write_from_order_result,
)
from app.deye_manual_limits import (
    battery_current_update_body,
    battery_voltage_v_from_latest,
    kw_to_watts,
    limits_view,
    rated_power_w_from_latest,
    registers_from_dynamic_read,
    sell_power_update_body,
    solar_power_update_body,
    solar_watts_from_registers,
    uses_lv_current_registers,
    watts_to_charge_amps,
)


class TestManualPowerLimits(unittest.TestCase):
    def test_solar_body_is_max_solar_power_watts(self) -> None:
        body = solar_power_update_body("2503291033", kw_to_watts(80))
        self.assertEqual(body["powerType"], "MAX_SOLAR_POWER")
        self.assertEqual(body["value"], 80_000)
        self.assertNotIn("maxSolarPower", body)

    def test_sell_body_is_discharge_watts(self) -> None:
        body = sell_power_update_body("2503291033", kw_to_watts(80))
        self.assertEqual(body["powerType"], "MAX_SELL_POWER")
        self.assertEqual(body["value"], 80_000)

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

    def test_hv_charge_voltage_is_not_treated_as_amps(self) -> None:
        # 2503291033: 0x00D2 is 864.0 V in 0.1 V steps. User charge current is 0x006C.
        self.assertFalse(uses_lv_current_registers(8640, 0))
        self.assertTrue(uses_lv_current_registers(113, 113))
        self.assertFalse(uses_lv_current_registers(None, 80))

    def test_hv_solar_register_is_ten_watt_steps(self) -> None:
        # 2503291033: 0x0035 is 0, 0x0154 is 8000 after a manual 80 kW write.
        self.assertEqual(solar_watts_from_registers(0, 8000), 80_000)
        self.assertEqual(solar_watts_from_registers(None, 8000), 80_000)
        # Single-phase keeps the watt register and ignores 0x0154.
        self.assertEqual(solar_watts_from_registers(6000, 20), 6000)
        self.assertIsNone(solar_watts_from_registers(0, 20))
        self.assertIsNone(solar_watts_from_registers(None, None))

    def test_fc3_pair_returns_both_registers(self) -> None:
        # Charge 80 A then discharge 62 A. CRC bytes are not checked.
        self.assertEqual(_parse_modbus_read_u16s("0103040050003EABCD"), [80, 62])
        self.assertIsNone(_parse_modbus_read_u16s("018302C1"))

    def test_discharge_order_frame_is_register_006d(self) -> None:
        # Order 864535587234309 echoed the 87 A write (70 kW at ~800 V) then failed 540.
        parsed = modbus_write_from_order_result("0110006D0001020057EF13")
        self.assertEqual(parsed, (0x006D, 87))
        self.assertIsNone(modbus_write_from_order_result(""))
        self.assertIsNone(modbus_write_from_order_result("not-hex"))

    def test_silent_inverter_is_retryable_and_named(self) -> None:
        payload = {
            "orderId": 864535587234309,
            "status": 500,
            "error": "540",
            "msg": "success",
            "orderResult": "0110006D0001020057EF13",
        }
        message = deye_order_failure_message(payload)
        self.assertIn("did not respond", message)
        self.assertIn("540", message)
        self.assertNotIn("success", message)
        failed = DeyeOrderFailed(message, code="540", status=500, deye_order=payload)
        self.assertTrue(deye_order_failure_is_retryable(failed))
        rejected = DeyeOrderFailed("no", code="530", status=500)
        self.assertFalse(deye_order_failure_is_retryable(rejected))
        self.assertTrue(deye_order_failure_is_retryable(DeyeOrderFailed("Deye order 1 timed out")))

    def test_rated_power_is_nameplate_watts(self) -> None:
        latest = {
            "deviceDataList": [
                {
                    "dataList": [
                        {"key": "RatedPower", "value": "6000.00"},
                        {"key": "BatteryVoltage", "value": "52.4"},
                    ]
                }
            ]
        }
        self.assertEqual(rated_power_w_from_latest(latest), 6000)
        self.assertIsNone(rated_power_w_from_latest({"deviceDataList": []}))


if __name__ == "__main__":
    unittest.main()
