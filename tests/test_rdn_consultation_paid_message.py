"""Paid RDN consultation Telegram alert includes the request description."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.telegram_notify import (
    format_rdn_consultation_paid_message,
    tag_open_ems_support_message,
)


class TestRdnConsultationPaidMessage(unittest.TestCase):
    def test_includes_description_and_escapes_html(self) -> None:
        when = datetime(2026, 10, 19, 14, 5, 6, tzinfo=ZoneInfo("Europe/Kyiv"))
        text = format_rdn_consultation_paid_message(
            name="Іван <b>",
            phone="+380501112233",
            amount_uah=2200,
            paid_at=when,
            slot_label="19.10.2026, 18:00",
            description="Розбір <цін> РДН на тиждень",
        )
        self.assertIn("Оплатив консультацію по РДН.", text)
        self.assertIn("Ім'я: Іван &lt;b&gt;", text)
        self.assertIn("Телефон: +380501112233", text)
        self.assertIn("Опис: Розбір &lt;цін&gt; РДН на тиждень", text)
        self.assertIn("Сума: <b>2200 грн</b>", text)
        self.assertIn("Час оплати: 19.10.2026, 14:05:06", text)
        self.assertIn("Слот: 19.10.2026, 18:00", text)
        self.assertIn("#ОплатаКонсультаціїПоРДН", text)

    def test_support_tag_is_appended_once(self) -> None:
        tagged = tag_open_ems_support_message("Ім'я: Тест\n\n#ОплатаКонсультаціїПоРДН")
        self.assertTrue(tagged.endswith("\n\n#open-ems"))
        self.assertEqual(tagged.count("#open-ems"), 1)
        self.assertEqual(tag_open_ems_support_message(tagged), tagged)


if __name__ == "__main__":
    unittest.main()
