"""Self-consumption ZERO_EXPORT_TO_CT uses the selected discharge floor (at least 5%)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.deye_api import (
    _body_selling_first,
    _body_zero_export_target_soc,
    apply_self_consumption_zero_export_ct,
)


class TestSelfConsumptionFloor(unittest.IsolatedAsyncioTestCase):
    async def test_tou_soc_matches_floor_when_above_minimum(self) -> None:
        captured: dict = {}

        async def fake_post(body: dict) -> None:
            captured["body"] = body

        async def fake_power(_sn: str) -> int:
            return 10_000

        with patch("app.deye_api.strategy_power_w", new=fake_power), patch(
            "app.deye_api._post_strategy_dynamic_control", new=fake_post
        ):
            await apply_self_consumption_zero_export_ct("1234567890", tou_soc_floor_pct=80.0)

        body = captured.get("body") or {}
        items = body.get("timeUseSettingItems") or []
        self.assertGreater(len(items), 0)
        for it in items:
            self.assertEqual(it.get("soc"), 80.0)

    async def test_tou_soc_clamps_to_minimum_when_floor_below_5(self) -> None:
        captured: dict = {}

        async def fake_post(body: dict) -> None:
            captured["body"] = body

        async def fake_power(_sn: str) -> int:
            return 10_000

        with patch("app.deye_api.strategy_power_w", new=fake_power), patch(
            "app.deye_api._post_strategy_dynamic_control", new=fake_post
        ):
            await apply_self_consumption_zero_export_ct("1234567890", tou_soc_floor_pct=3.0)

        body = captured.get("body") or {}
        items = body.get("timeUseSettingItems") or []
        for it in items:
            self.assertEqual(it.get("soc"), 5.0)

    async def test_no_floor_uses_5_percent(self) -> None:
        captured: dict = {}

        async def fake_post(body: dict) -> None:
            captured["body"] = body

        async def fake_power(_sn: str) -> int:
            return 10_000

        with patch("app.deye_api.strategy_power_w", new=fake_power), patch(
            "app.deye_api._post_strategy_dynamic_control", new=fake_post
        ):
            await apply_self_consumption_zero_export_ct("1234567890")

        body = captured.get("body") or {}
        items = body.get("timeUseSettingItems") or []
        for it in items:
            self.assertEqual(it.get("soc"), 5.0)
        self.assertNotIn("maxSolarPower", body)

    def test_strategy_bodies_omit_max_solar_power(self) -> None:
        selling = _body_selling_first("1234567890", 20.0, 10_000)
        zero = _body_zero_export_target_soc("1234567890", 80.0, 10_000)
        self.assertNotIn("maxSolarPower", selling)
        self.assertNotIn("maxSolarPower", zero)
        self.assertEqual(selling["maxSellPower"], 10_000)
        self.assertEqual(zero["maxSellPower"], 10_000)
        for it in selling["timeUseSettingItems"]:
            self.assertTrue(it.get("enableSell"))
            self.assertFalse(it.get("enableGridCharge"))
            self.assertFalse(it.get("enableGeneration"))
        for it in zero["timeUseSettingItems"]:
            self.assertNotIn("enableSell", it)
            self.assertTrue(it.get("enableGridCharge"))


if __name__ == "__main__":
    unittest.main()
