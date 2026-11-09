"""RDN consultation calendar slots (3 windows / day, next week only, 20% busy)."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.rdn_consultation_slots import (
    BUSY_RATIO,
    WINDOWS,
    list_consultation_days,
    next_week_monday,
    require_available_slot,
    slot_label_uk,
)

KYIV = ZoneInfo("Europe/Kyiv")


class TestRdnConsultationSlots(unittest.TestCase):
    def test_three_windows_per_day(self) -> None:
        now = datetime(2026, 9, 21, 8, 0, tzinfo=KYIV)
        days = list_consultation_days(now)
        self.assertGreaterEqual(len(days), 14)
        self.assertEqual(len(WINDOWS), 3)
        for row in days:
            self.assertEqual(len(row["windows"]), 3)
            labels = [w["label"] for w in row["windows"]]
            self.assertEqual(labels, ["10:00", "14:00", "18:00"])

    def test_book_from_next_week_monday_only(self) -> None:
        # Monday 9 Nov 2026 → calendar starts Mon 16 Nov (current week omitted).
        now = datetime(2026, 11, 9, 12, 0, tzinfo=KYIV)
        self.assertEqual(next_week_monday(now.date()).isoformat(), "2026-11-16")
        days = list_consultation_days(now)
        self.assertEqual(len(days), 14)
        self.assertEqual(days[0]["date"], "2026-11-16")
        self.assertNotIn("2026-11-09", {d["date"] for d in days})
        self.assertNotIn("2026-11-15", {d["date"] for d in days})
        monday = days[0]
        self.assertTrue(monday["hasAvailable"] or any(w["busy"] for w in monday["windows"]))

    def test_busy_ratio_on_future_slots(self) -> None:
        now = datetime(2026, 9, 21, 8, 0, tzinfo=KYIV)
        days = list_consultation_days(now)
        open_future = [w for d in days for w in d["windows"] if w["available"] or w["busy"]]
        busy = [w for w in open_future if w["busy"]]
        expected = int(round(len(open_future) * BUSY_RATIO))
        self.assertEqual(len(busy), expected)
        self.assertTrue(any(w["available"] for w in open_future))

    def test_weekend_have_no_times(self) -> None:
        now = datetime(2026, 10, 1, 16, 40, tzinfo=KYIV)
        days = {row["date"]: row for row in list_consultation_days(now)}
        # Starts Mon 5 Oct; weekends in range still closed.
        self.assertEqual(min(days), "2026-10-05")
        for closed in ("2026-10-10", "2026-10-11"):
            row = days[closed]
            self.assertFalse(row["hasAvailable"])
            self.assertTrue(all(not w["available"] for w in row["windows"]))
        friday = days["2026-10-09"]
        self.assertTrue(any(w["available"] or w["busy"] for w in friday["windows"]))

    def test_require_available_slot(self) -> None:
        now = datetime(2026, 9, 21, 8, 0, tzinfo=KYIV)
        days = list_consultation_days(now)
        free = next(w for d in days for w in d["windows"] if w["available"])
        found = require_available_slot(free["id"], now)
        self.assertEqual(found["id"], free["id"])
        with self.assertRaises(ValueError):
            require_available_slot("1999-01-01T10:00", now)
        # Current-week slot is not in the calendar.
        with self.assertRaises(ValueError):
            require_available_slot("2026-09-21T14:00", now)
        busy = next((w for d in days for w in d["windows"] if w["busy"]), None)
        if busy:
            with self.assertRaises(ValueError):
                require_available_slot(busy["id"], now)

    def test_slot_label_uk(self) -> None:
        self.assertEqual(slot_label_uk("2026-09-21T14:00"), "21.09.2026, 14:00")


if __name__ == "__main__":
    unittest.main()
