"""Kyiv low-DAM charge hour vs day discharge window."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.deye_low_dam_charge_service import kyiv_low_dam_discharge_hour_active, low_hour_index_from_hourly_uah_mwh

KYIV = ZoneInfo("Europe/Kyiv")


def _kyiv(y: int, m: int, d: int, h: int, minute: int = 0) -> datetime:
    return datetime(y, m, d, h, minute, tzinfo=KYIV)


class TestLowDamWindows(unittest.TestCase):
    def test_low_hour_index_picks_minimum(self) -> None:
        hourly = [5000.0 if h != 12 else 0.0 for h in range(24)]
        self.assertEqual(low_hour_index_from_hourly_uah_mwh(hourly), 12)

    def test_discharge_active_outside_min_hour(self) -> None:
        low_hour = 12
        self.assertTrue(kyiv_low_dam_discharge_hour_active(_kyiv(2026, 6, 5, 8, 0), low_hour))
        self.assertTrue(kyiv_low_dam_discharge_hour_active(_kyiv(2026, 6, 5, 18, 0), low_hour))
        self.assertFalse(kyiv_low_dam_discharge_hour_active(_kyiv(2026, 6, 5, 12, 0), low_hour))

    def test_discharge_inactive_when_no_low_hour(self) -> None:
        self.assertFalse(kyiv_low_dam_discharge_hour_active(_kyiv(2026, 6, 5, 10, 0), None))


if __name__ == "__main__":
    unittest.main()
