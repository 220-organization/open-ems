"""Hourly DAM prices Excel builder."""

from __future__ import annotations

import unittest
import zipfile
from datetime import date
from io import BytesIO

from app.dam_prices_xlsx import DamXlsxSheet, build_hourly_dam_prices_xlsx, dam_xlsx_filename


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

    def test_workbook_includes_entsoe_country_tabs(self) -> None:
        extra = [
            DamXlsxSheet(
                name="ENTSO-E UA",
                rows=[(date(2026, 3, 1), 1, 80.0)],
                year=2026,
                market_label="ENTSO-E",
                zone_label="UA (10Y1001C--000182)",
                unit_label="EUR/kWh",
            ),
            DamXlsxSheet(
                name="ENTSO-E PL",
                rows=[(date(2026, 3, 1), 1, 90.0)],
                year=2026,
                market_label="ENTSO-E",
                zone_label="PL (10YPL-AREA-----S)",
                unit_label="EUR/kWh",
            ),
            DamXlsxSheet(
                name="ENTSO-E ES",
                rows=[(date(2026, 3, 1), 1, 100.0)],
                year=2026,
                market_label="ENTSO-E",
                zone_label="ES (10YES-REE------0)",
                unit_label="EUR/kWh",
            ),
        ]
        blob = build_hourly_dam_prices_xlsx(
            [(date(2026, 3, 1), 1, 3456.0)],
            year=2026,
            market_label="Ukraine (OREE)",
            zone_label="10Y1001C--000182",
            unit_label="UAH/kWh",
            extra_sheets=extra,
        )
        with zipfile.ZipFile(BytesIO(blob)) as zf:
            names = set(zf.namelist())
            workbook = zf.read("xl/workbook.xml").decode("utf-8")
            ua = zf.read("xl/worksheets/sheet2.xml").decode("utf-8")
            pl = zf.read("xl/worksheets/sheet3.xml").decode("utf-8")
            es = zf.read("xl/worksheets/sheet4.xml").decode("utf-8")
        self.assertIn("xl/worksheets/sheet4.xml", names)
        self.assertIn('name="DAM prices"', workbook)
        self.assertIn('name="ENTSO-E UA"', workbook)
        self.assertIn('name="ENTSO-E PL"', workbook)
        self.assertIn('name="ENTSO-E ES"', workbook)
        self.assertIn("0.08", ua)
        self.assertIn("0.09", pl)
        self.assertIn("0.1", es)
        self.assertIn("EUR/kWh", es)

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


class TestDamXlsxPayment(unittest.TestCase):
    def test_invoice_amount_is_5000_uah(self) -> None:
        from app.rdn_consultation_payment import DAM_XLSX_AMOUNT_UAH, dam_xlsx_invoice_payload

        self.assertEqual(DAM_XLSX_AMOUNT_UAH, 5000)
        payload = dam_xlsx_invoice_payload(
            redirect_url="https://example.com/?market=oree",
            reference="pay-1",
        )
        self.assertEqual(payload["amount"], 500000)
        self.assertEqual(payload["ccy"], 980)
        self.assertIn("Excel", payload["merchantPaymInfo"]["destination"])

    def test_download_unlocks_only_after_success(self) -> None:
        from app.routers import dam as dam_router

        dam_router._XLSX_PENDING.clear()
        self.assertFalse(dam_router._xlsx_payment_unlocked(None))
        self.assertFalse(dam_router._xlsx_payment_unlocked("missing"))
        dam_router._XLSX_PENDING["p1"] = {"status": "created", "invoice_id": "inv"}
        self.assertFalse(dam_router._xlsx_payment_unlocked("p1"))
        dam_router._XLSX_PENDING["p1"]["status"] = "SUCCESS"
        self.assertTrue(dam_router._xlsx_payment_unlocked("p1"))
        dam_router._XLSX_PENDING.clear()


class TestDamXlsxYears(unittest.TestCase):
    def test_pick_xlsx_year(self) -> None:
        from app.routers.dam import pick_xlsx_year

        self.assertIsNone(pick_xlsx_year(2026, []))
        self.assertEqual(pick_xlsx_year(None, [2025, 2026]), 2026)
        self.assertEqual(pick_xlsx_year(2025, [2025, 2026]), 2025)
        self.assertEqual(pick_xlsx_year(2024, [2025, 2026]), 2026)


if __name__ == "__main__":
    unittest.main()
