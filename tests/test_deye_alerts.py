"""Deye /device/alertList rows shown on the power-flow page."""

from __future__ import annotations

import unittest

from app.deye_api import deye_alert_title, normalize_deye_alert


class TestDeyeAlerts(unittest.TestCase):
    def test_f14_title(self) -> None:
        self.assertEqual(deye_alert_title("F14DC_OverCurr_Fault"), "F14 DC overcurrent")

    def test_open_alert_is_active(self) -> None:
        item = normalize_deye_alert(
            {
                "alertId": "1",
                "alertName": "F14DC_OverCurr_Fault",
                "alertStartTime": 1793200439,
                "alertEndTime": None,
                "status": 1,
            }
        )
        assert item is not None
        self.assertTrue(item["active"])
        self.assertEqual(item["title"], "F14 DC overcurrent")
        self.assertIsNone(item["endTime"])

    def test_cleared_alert_is_inactive(self) -> None:
        item = normalize_deye_alert(
            {
                "alertId": "2",
                "alertName": "F13Grid_Mode_changed",
                "alertStartTime": 100,
                "alertEndTime": 200,
                "status": 0,
            }
        )
        assert item is not None
        self.assertFalse(item["active"])
        self.assertEqual(item["endTime"], 200)
