"""Kyiv low-DAM charge window vs day discharge window."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.deye_low_dam_charge_service import (
    kyiv_low_dam_charge_deadline,
    kyiv_low_dam_charge_window_active,
    kyiv_low_dam_discharge_hour_active,
    low_dam_charge_plan_from_hourly,
    low_hour_index_from_hourly_uah_mwh,
)

KYIV = ZoneInfo("Europe/Kyiv")


def _kyiv(y: int, m: int, d: int, h: int, minute: int = 0) -> datetime:
    return datetime(y, m, d, h, minute, tzinfo=KYIV)


class TestLowDamWindows(unittest.TestCase):
    def test_low_hour_index_picks_minimum(self) -> None:
        hourly = [5000.0 if h != 12 else 0.0 for h in range(24)]
        self.assertEqual(low_hour_index_from_hourly_uah_mwh(hourly), 12)

    def test_charge_plan_picks_cheapest_3h_block_around_low(self) -> None:
        # Minimum at hour 16; cheapest 3h block is 14–16 (sum 700).
        hourly = [5000.0] * 24
        hourly[13] = 670.0
        hourly[14] = 400.0
        hourly[15] = 200.0
        hourly[16] = 100.0
        hourly[17] = 700.0
        hourly[18] = 2000.0
        low_hour, charge_start = low_dam_charge_plan_from_hourly(hourly)
        self.assertEqual(low_hour, 16)
        self.assertEqual(charge_start, 14)

    def test_charge_plan_tie_prefers_earlier_start(self) -> None:
        hourly = [100.0] * 24
        for h in (10, 11, 12, 13, 14, 15):
            hourly[h] = 1.0
        hourly[12] = 0.0
        _, charge_start = low_dam_charge_plan_from_hourly(hourly)
        self.assertEqual(charge_start, 10)

    def test_charge_plan_fallback_to_low_hour_when_no_block(self) -> None:
        hourly = [None] * 24
        hourly[8] = 10.0
        low_hour, charge_start = low_dam_charge_plan_from_hourly(hourly)
        self.assertEqual(low_hour, 8)
        self.assertEqual(charge_start, 8)

    def test_charge_window_active_for_three_hours(self) -> None:
        start = 14
        self.assertFalse(kyiv_low_dam_charge_window_active(_kyiv(2026, 6, 7, 13, 59), start))
        self.assertTrue(kyiv_low_dam_charge_window_active(_kyiv(2026, 6, 7, 14, 0), start))
        self.assertTrue(kyiv_low_dam_charge_window_active(_kyiv(2026, 6, 7, 16, 59), start))
        self.assertFalse(kyiv_low_dam_charge_window_active(_kyiv(2026, 6, 7, 17, 0), start))

    def test_discharge_active_outside_charge_window(self) -> None:
        charge_start = 14
        self.assertTrue(kyiv_low_dam_discharge_hour_active(_kyiv(2026, 6, 7, 8, 0), charge_start))
        self.assertTrue(kyiv_low_dam_discharge_hour_active(_kyiv(2026, 6, 7, 18, 0), charge_start))
        self.assertFalse(kyiv_low_dam_discharge_hour_active(_kyiv(2026, 6, 7, 15, 0), charge_start))

    def test_discharge_inactive_when_no_charge_start(self) -> None:
        self.assertFalse(kyiv_low_dam_discharge_hour_active(_kyiv(2026, 6, 7, 10, 0), None))

    def test_charge_deadline_same_day(self) -> None:
        dl = kyiv_low_dam_charge_deadline(date(2026, 6, 7), 14)
        self.assertEqual(dl, _kyiv(2026, 6, 7, 17, 0))

    def test_charge_deadline_wraps_next_day(self) -> None:
        dl = kyiv_low_dam_charge_deadline(date(2026, 6, 7), 22)
        self.assertEqual(dl, _kyiv(2026, 6, 8, 1, 0))


if __name__ == "__main__":
    unittest.main()
