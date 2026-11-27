"""Admin booking ICS feed for Google Calendar."""

from __future__ import annotations

import unittest
from datetime import datetime
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from app.admin_calendar_ics import (
    build_ics,
    calendar_feed_token,
    calendar_feed_token_ok,
    google_subscribe_url,
    parse_slot,
)
from app import settings

KYIV = ZoneInfo("Europe/Kyiv")


class TestAdminCalendarIcs(unittest.TestCase):
    def test_kyiv_slot_becomes_utc(self) -> None:
        start = parse_slot("30.11.2026, 18:00")
        self.assertIsNotNone(start)
        assert start is not None
        self.assertEqual(start, datetime(2026, 11, 30, 18, 0, tzinfo=KYIV))
        self.assertEqual(start.utctimetuple()[3], 16)

    def test_paid_consultation_event(self) -> None:
        body = build_ics(
            [
                {
                    "id": "oleksandr",
                    "source": "consultation",
                    "kind": "payment",
                    "name": "Олександр",
                    "phone": "+380501112233",
                    "slot_label": "30.11.2026, 18:00",
                    "status": "SUCCESS",
                    "amount_uah": 1500,
                }
            ],
            admin_url="https://220-km.com:9220/admin",
        )
        body = body.replace("\r\n ", "")
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("X-WR-CALNAME:220 km admin", body)
        self.assertIn("DTSTART:20261130T160000Z", body)
        self.assertIn("DTEND:20261130T170000Z", body)
        self.assertIn("Олександр — Оплата · SUCCESS", body)
        self.assertIn("UID:consultation-oleksandr@220-km.com", body)
        self.assertIn("STATUS:CONFIRMED", body)
        self.assertIn("https://220-km.com:9220/admin", body)

    def test_skips_rows_without_time(self) -> None:
        body = build_ics([{"id": "x", "name": "No slot", "slot_label": "30.11.2026"}])
        self.assertNotIn("BEGIN:VEVENT", body)

    def test_feed_token_is_not_the_admin_api_token(self) -> None:
        token = calendar_feed_token()
        self.assertNotEqual(token, settings.OPEN_EMS_ADMIN_TOKEN)
        self.assertTrue(calendar_feed_token_ok(token))
        self.assertFalse(calendar_feed_token_ok(settings.OPEN_EMS_ADMIN_TOKEN))
        self.assertFalse(calendar_feed_token_ok(""))

    def test_google_subscribe_url(self) -> None:
        feed = "https://220-km.com:9220/api/admin/calendar.ics?token=abc"
        url = google_subscribe_url(feed)
        self.assertTrue(url.startswith("https://calendar.google.com/calendar/u/0/r?cid=webcal%3A%2F%2F"))
        self.assertIn("webcal://220-km.com:9220/api/admin/calendar.ics?token=abc", unquote(url))
        self.assertNotIn("cid=https%3A", url)
