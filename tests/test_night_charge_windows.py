"""Kyiv night charge vs day discharge window boundaries."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.deye_night_charge_service import (
    kyiv_day_discharge_window_active,
    kyiv_night_charge_deadline,
    kyiv_night_window_anchor_date,
    should_start_night_charge_now,
)

KYIV = ZoneInfo("Europe/Kyiv")


def _kyiv(y: int, m: int, d: int, h: int, minute: int = 0) -> datetime:
    return datetime(y, m, d, h, minute, tzinfo=KYIV)


class TestNightChargeWindows(unittest.TestCase):
    def test_night_anchor_at_23(self) -> None:
        now = _kyiv(2026, 5, 29, 23, 15)
        self.assertEqual(kyiv_night_window_anchor_date(now), date(2026, 5, 29))

    def test_night_anchor_after_midnight(self) -> None:
        now = _kyiv(2026, 5, 30, 2, 0)
        self.assertEqual(kyiv_night_window_anchor_date(now), date(2026, 5, 29))

    def test_night_anchor_last_minute(self) -> None:
        now = _kyiv(2026, 5, 30, 6, 59)
        self.assertEqual(kyiv_night_window_anchor_date(now), date(2026, 5, 29))

    def test_night_anchor_none_during_day(self) -> None:
        now = _kyiv(2026, 5, 30, 7, 0)
        self.assertIsNone(kyiv_night_window_anchor_date(now))
        self.assertIsNone(kyiv_night_window_anchor_date(_kyiv(2026, 5, 30, 12, 0)))
        self.assertIsNone(kyiv_night_window_anchor_date(_kyiv(2026, 5, 30, 22, 59)))

    def test_day_discharge_starts_at_7(self) -> None:
        self.assertFalse(kyiv_day_discharge_window_active(_kyiv(2026, 5, 30, 6, 59)))
        self.assertTrue(kyiv_day_discharge_window_active(_kyiv(2026, 5, 30, 7, 0)))

    def test_day_discharge_ends_at_23(self) -> None:
        self.assertTrue(kyiv_day_discharge_window_active(_kyiv(2026, 5, 30, 22, 59)))
        self.assertFalse(kyiv_day_discharge_window_active(_kyiv(2026, 5, 30, 23, 0)))

    def test_start_only_at_hour_23(self) -> None:
        self.assertTrue(should_start_night_charge_now(_kyiv(2026, 5, 29, 23, 15)))
        self.assertFalse(should_start_night_charge_now(_kyiv(2026, 5, 30, 3, 0)))
        # Same Kyiv instant from a Germany server clock
        berlin = ZoneInfo("Europe/Berlin")
        self.assertTrue(should_start_night_charge_now(_kyiv(2026, 5, 29, 23, 15).astimezone(berlin)))

    def test_charge_deadline_07_kyiv(self) -> None:
        dl = kyiv_night_charge_deadline(date(2026, 5, 29))
        self.assertEqual(dl.hour, 7)
        self.assertEqual(dl.date(), date(2026, 5, 30))
        self.assertEqual(str(dl.tzinfo), "Europe/Kyiv")


if __name__ == "__main__":
    unittest.main()
