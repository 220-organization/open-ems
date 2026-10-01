"""TOV payment invoice workbook."""

from __future__ import annotations

import unittest
import zipfile
from datetime import date
from io import BytesIO

from app.tov_invoice_xlsx import build_tov_invoice_xlsx, buyer_from_requisites, uah_amount_words


def _buyer():
    buyer, edrpou = buyer_from_requisites(
        "ТОВ «Приклад»\n"
        "Код ЄДРПОУ: 12345678\n"
        "Адреса: 01001 м. Київ, вул. Тестова, 1\n"
        "Директор: Іваненко І. І."
    )
    assert edrpou == "12345678"
    return buyer


class TestTovInvoiceXlsx(unittest.TestCase):
    def test_amount_words(self) -> None:
        self.assertEqual(uah_amount_words(2200), "дві тисячі двісті гривень 00 копійок")
        self.assertEqual(uah_amount_words(5000), "п'ять тисяч гривень 00 копійок")
        self.assertEqual(uah_amount_words(1), "одна гривня 00 копійок")

    def test_workbook_contains_buyer_and_amount(self) -> None:
        blob = build_tov_invoice_xlsx(_buyer(), amount_uah=2200, issued_on=date(2026, 10, 1))
        self.assertGreater(len(blob), 200)
        with zipfile.ZipFile(BytesIO(blob)) as zf:
            names = set(zf.namelist())
            sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("ТОВ «Приклад»", sheet)
        self.assertIn("12345678", sheet)
        self.assertIn("Консультація по EMS + РДН", sheet)
        self.assertIn("2200", sheet)
        self.assertIn("Дві тисячі двісті гривень 00 копійок, без ПДВ", sheet)
        self.assertIn("1 жовтня 2026 р.", sheet)
        self.assertIn("без ПДВ", sheet)
        self.assertIn('s="39"', sheet)
        self.assertIn('s="35"', sheet)
        self.assertIn('ht="99.95"', sheet)
        self.assertIn('width="19.5703125"', sheet)
        self.assertIn("A2:K4", sheet)
        self.assertIn("xl/styles.xml", names)


if __name__ == "__main__":
    unittest.main()
