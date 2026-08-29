"""Energotrendy Ukrainy (ETU) UAH price-list parser + SKU canonicalization."""

from __future__ import annotations

import unittest

from app.routers.bess_order import (
    _canonical_article,
    _merge_etu_items,
    _parse_etu_sheet_csv,
    _uah_to_usd,
)

_ETU_CSV = """\
"ОБЛАДНАННЯ DEYE. Інвертори та АКБ  ","Прайс лист 27/08","високовольний низьковольний К-сть фаз ","Тип  ","Потужність/ємність ","Контакти Модель ","Опис ","Ціна, грн передплата 100%
гарантована поставка 
5-10 днів з Нідерландів ","Ціна  ТОВ без ПДВ, грн "
"","Deye ","Однофазні ","","6KW ","SUN-6K-SG05LP1-EU-AM2-P","DEYE низьковольтний однофазний інвертор ","38500","40500"
"","Deye ","3-х фазна ","","50KW ","SUN-50K-SG01HP3-EU
BM4","Deye високовольтний трьохфазний інвертор 50kw ","195000","205000"
"","Deye ","Низьковольний","Тільки для низьковольтних інверторів DEYE 
","5 KWH ","SE-G5.1 Pro-B ","Низьковольтна універсальна","37500","39500"
"","Deye ","Високовольтний","","5 kwh ","BOS-G-PACK5.1 PRO","Високовольний акумуляторний модуль 5.12 kwh","38500","40500"
"","Інвертори DEYE","","","","","","",""
"""


class TestBessEtuSheet(unittest.TestCase):
    def test_canonical_articles(self) -> None:
        self.assertEqual(
            _canonical_article("SUN-50K-SG01HP3-EU\nBM4"),
            "SUN-50K-SG01HP3-EU-BM4",
        )
        self.assertEqual(_canonical_article("SUN-6K-SG05LP1-EU-AM2-P"), "SUN-6K-SG05LP1-EU-AM2-P")
        self.assertEqual(_canonical_article("SE-G5.1 Pro-B"), "SE-G5.1-PRO-B")
        self.assertEqual(_canonical_article("BOS-G-PACK5.1 PRO"), "BOS-G-Pack5.1")
        self.assertEqual(_canonical_article("BOS-G Pro-Pack5.1"), "BOS-G-Pack5.1")
        self.assertEqual(_canonical_article("DEYE SE-F16-С"), "SE-F16-C")
        self.assertEqual(
            _canonical_article("SUN-80K-SG02HP3-EU-EM6\nBM4"),
            "SUN-80K-SG02HP3-EU-EM6",
        )

    def test_parse_prepaid_and_tov(self) -> None:
        items = _parse_etu_sheet_csv(_ETU_CSV)
        by_art = {row["article"]: row for row in items.values()}
        inv = by_art["SUN-50K-SG01HP3-EU-BM4"]
        self.assertEqual(inv["prepaidUah"], 195000.0)
        self.assertEqual(inv["tovUah"], 205000.0)
        six = by_art["SUN-6K-SG05LP1-EU-AM2-P"]
        self.assertEqual(six["prepaidUah"], 38500.0)
        bat = by_art["BOS-G-Pack5.1"]
        self.assertEqual(bat["prepaidUah"], 38500.0)
        se = by_art["SE-G5.1-PRO-B"]
        self.assertEqual(se["prepaidUah"], 37500.0)

    def test_merge_prefers_cheaper_etu_retail(self) -> None:
        fx = 45.3
        by_article = {
            "SUN-50K-SG01HP3-EU-BM4": {
                "article": "SUN-50K-SG01HP3-EU-BM4",
                "name": "BIOM",
                "installerCheapestUsd": 3850.0,
                "installerUsd": 4030.0,
                "retailUsd": 5237.55,
                "retailVatUsd": None,
                "availabilityInstaller": "АКЦІЯ!",
                "priceSourceCash": "install",
                "priceSourceRetail": "install",
            }
        }
        etu = _parse_etu_sheet_csv(_ETU_CSV)
        _merge_etu_items(by_article, etu, fx)
        row = by_article["SUN-50K-SG01HP3-EU-BM4"]
        # ETU prepaid 195000/45.3 ≈ 4304 > BIOM 3850 → keep BIOM cash
        self.assertEqual(row["installerCheapestUsd"], 3850.0)
        self.assertEqual(row["priceSourceCash"], "install")
        # ETU TOV 205000/45.3 ≈ 4525 < BIOM 5237 → take ETU retail
        self.assertAlmostEqual(row["retailUsd"], _uah_to_usd(205000.0, fx) or 0, places=2)
        self.assertEqual(row["priceSourceRetail"], "etu")
        self.assertIsNotNone(row["retailVatUsd"])

    def test_merge_unlocks_no_arrival_when_etu_has_price(self) -> None:
        """BIOM «дані про приходи відсутні» must not block SKUs ETU can supply."""
        fx = 45.3
        by_article = {
            "BOS-G-PACK5.1": {
                "article": "BOS-G-Pack5.1",
                "name": "BIOM BOS-G",
                "installerCheapestUsd": 710.0,
                "installerUsd": 710.0,
                "retailUsd": 817.0,
                "retailVatUsd": 923.21,
                "availability": "дані про приходи відсутні",
                "availabilityInstaller": "дані про приходи відсутні",
                "priceSourceCash": "install",
                "priceSourceRetail": "install",
            }
        }
        etu = _parse_etu_sheet_csv(_ETU_CSV)
        _merge_etu_items(by_article, etu, fx)
        row = by_article["BOS-G-PACK5.1"]
        # Cheaper BIOM cash stays
        self.assertEqual(row["installerCheapestUsd"], 710.0)
        self.assertEqual(row["priceSourceCash"], "install")
        # Availability comes from ETU so the UI can select 5 kWh HV
        self.assertIn("Енерготренди", row["availabilityInstaller"])
        self.assertNotRegex(row["availabilityInstaller"], r"приход")


if __name__ == "__main__":
    unittest.main()
