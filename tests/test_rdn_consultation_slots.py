"""RDN consultation calendar slots (3 windows / day, 20% busy)."""

from __future__ import annotations

import unittest
from datetime import datetime

from app.rdn_consultation_slots import (
    BUSY_RATIO,
    SLOT_DAYS,
    WINDOWS,
    list_consultation_days,
    require_available_slot,
    slot_label_uk,
)


class TestRdnConsultationSlots(unittest.TestCase):
    def test_two_weeks_three_windows(self) -> None:
        now = datetime(2026, 9, 21, 8, 0, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Kyiv"))
        days = list_consultation_days(now)
        self.assertEqual(len(days), SLOT_DAYS)
        self.assertEqual(len(WINDOWS), 3)
        for row in days:
            self.assertEqual(len(row["windows"]), 3)
            labels = [w["label"] for w in row["windows"]]
            self.assertEqual(labels, ["10:00", "14:00", "18:00"])

    def test_busy_ratio_on_future_slots(self) -> None:
        now = datetime(2026, 9, 21, 8, 0, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Kyiv"))
        days = list_consultation_days(now)
        future = [w for d in days for w in d["windows"] if not w["past"]]
        busy = [w for w in future if w["busy"]]
        expected = int(round(len(future) * BUSY_RATIO))
        self.assertEqual(len(busy), expected)
        self.assertTrue(any(w["available"] for w in future))

    def test_past_today_windows_not_available(self) -> None:
        now = datetime(2026, 9, 21, 15, 30, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Kyiv"))
        days = list_consultation_days(now)
        today = days[0]
        self.assertEqual(today["date"], "2026-09-21")
        by_label = {w["label"]: w for w in today["windows"]}
        self.assertTrue(by_label["10:00"]["past"])
        self.assertFalse(by_label["10:00"]["available"])
        self.assertTrue(by_label["14:00"]["past"])
        self.assertFalse(by_label["18:00"]["past"])

    def test_require_available_slot(self) -> None:
        now = datetime(2026, 9, 21, 8, 0, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Kyiv"))
        days = list_consultation_days(now)
        free = next(w for d in days for w in d["windows"] if w["available"])
        found = require_available_slot(free["id"], now)
        self.assertEqual(found["id"], free["id"])
        with self.assertRaises(ValueError):
            require_available_slot("1999-01-01T10:00", now)
        busy = next((w for d in days for w in d["windows"] if w["busy"]), None)
        if busy:
            with self.assertRaises(ValueError):
                require_available_slot(busy["id"], now)

    def test_slot_label_uk(self) -> None:
        self.assertEqual(slot_label_uk("2026-09-21T14:00"), "21.09.2026, 14:00")


if __name__ == "__main__":
    unittest.main()
