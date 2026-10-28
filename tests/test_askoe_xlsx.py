"""ASKOE workbook matches the DTEK hourly layout and MWh scale."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from io import BytesIO

from app.askoe_xlsx import HOUR_LABELS, build_askoe_xlsx, kwh_to_mwh

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _cells(blob: bytes) -> dict[str, str]:
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    out: dict[str, str] = {}
    for cell in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
        ref = cell.attrib.get("r")
        if not ref:
            continue
        value = cell.find("m:v", NS)
        if value is not None and value.text is not None:
            out[ref] = value.text
            continue
        text = cell.find("m:is/m:t", NS)
        if text is not None and text.text is not None:
            out[ref] = text.text
    return out


class TestAskoeXlsx(unittest.TestCase):
    def test_kwh_to_mwh(self) -> None:
        self.assertEqual(kwh_to_mwh(3.2), 0.0032)
        self.assertIsNone(kwh_to_mwh(None))

    def test_day_sheet_matches_askoe_rows(self) -> None:
        hours = [None] * 24
        hours[0] = 3.2
        hours[1] = 0.0
        blob = build_askoe_xlsx(
            serial="67378533",
            days=[date(2025, 11, 1)],
            hourly_kwh=[hours],
            location='ПрАТ "ДТЕК"',
            point="ВРП (67378533)",
        )
        cells = _cells(blob)
        self.assertEqual(cells["A1"], "Розташування")
        self.assertEqual(cells["B2"], "ВРП (67378533)")
        self.assertEqual(cells["B3"], "A+ (Лічильник) Основн.")
        self.assertEqual(cells["B4"], "67378533")
        self.assertEqual(cells["A5"], "Час \\\\ дата")
        self.assertEqual(cells["B5"], "01.11.2025")
        self.assertEqual(cells["A6"], HOUR_LABELS[0])
        self.assertEqual(cells["A29"], "23:00-24:00")
        self.assertEqual(cells["B6"], "0.0032")
        self.assertEqual(cells["B7"], "0")
        self.assertNotIn("B8", cells)
        self.assertEqual(cells["A30"], "Разом")
        self.assertEqual(cells["B30"], "0.0032")
        self.assertEqual(cells["A31"], "Разом, загальне")
        self.assertEqual(cells["B31"], "0.0032")
