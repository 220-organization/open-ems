"""Hourly DAM prices Excel builder."""

from __future__ import annotations

import unittest
import zipfile
from datetime import date
from io import BytesIO

from app.dam_prices_xlsx import build_hourly_dam_prices_xlsx, dam_xlsx_filename


class TestDamPricesXlsx(unittest.TestCase):
    def test_filename(self) -> None:
        self.assertEqual(dam_xlsx_filename("oree", 2026), "dam-prices-oree-2026.xlsx")
        self.assertEqual(dam_xlsx_filename("entsoe", 2025, "ES"), "dam-prices-entsoe-ES-2025.xlsx")

    def test_workbook_has_day_and_scaled_price(self) -> None:
        blob = build_hourly_dam_prices_xlsx(
            [
                (date(2026, 1, 2), 1, 3456.0),
                (date(2026, 1, 2), 2, 2100.0),
            ],
            year=2026,
            market_label="Ukraine (OREE)",
            zone_label="10Y1001C--000182",
            unit_label="UAH/kWh",
        )
        self.assertGreater(len(blob), 200)
        with zipfile.ZipFile(BytesIO(blob)) as zf:
            names = set(zf.namelist())
            self.assertIn("xl/worksheets/sheet1.xml", names)
            sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("2026-01-02", sheet)
        self.assertIn("00:00", sheet)
        self.assertIn("23:00", sheet)
        self.assertIn("3.456", sheet)
        self.assertIn("2.1", sheet)
        self.assertIn("UAH/kWh", sheet)
        self.assertIn("Ukraine (OREE)", sheet)

    def test_empty_year_still_xlsx(self) -> None:
        blob = build_hourly_dam_prices_xlsx(
            [],
            year=2025,
            market_label="ENTSO-E",
            zone_label="ES (10YES-REE------0)",
            unit_label="EUR/kWh",
        )
        with zipfile.ZipFile(BytesIO(blob)) as zf:
            sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("No prices in database for this year", sheet)
        self.assertIn("EUR/kWh", sheet)


if __name__ == "__main__":
    unittest.main()
