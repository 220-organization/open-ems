"""Self-consumption ZERO_EXPORT_TO_CT uses the selected discharge floor (at least 5%)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.deye_api import apply_self_consumption_zero_export_ct


class TestSelfConsumptionFloor(unittest.IsolatedAsyncioTestCase):
    async def test_tou_soc_matches_floor_when_above_minimum(self) -> None:
        captured: dict = {}

        async def fake_post(body: dict) -> None:
            captured["body"] = body

        with patch("app.deye_api._post_strategy_dynamic_control", new=fake_post):
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

        with patch("app.deye_api._post_strategy_dynamic_control", new=fake_post):
            await apply_self_consumption_zero_export_ct("1234567890", tou_soc_floor_pct=3.0)

        body = captured.get("body") or {}
        items = body.get("timeUseSettingItems") or []
        for it in items:
            self.assertEqual(it.get("soc"), 5.0)

    async def test_no_floor_uses_5_percent(self) -> None:
        captured: dict = {}

        async def fake_post(body: dict) -> None:
            captured["body"] = body

        with patch("app.deye_api._post_strategy_dynamic_control", new=fake_post):
            await apply_self_consumption_zero_export_ct("1234567890")

        body = captured.get("body") or {}
        items = body.get("timeUseSettingItems") or []
        for it in items:
            self.assertEqual(it.get("soc"), 5.0)


if __name__ == "__main__":
    unittest.main()
