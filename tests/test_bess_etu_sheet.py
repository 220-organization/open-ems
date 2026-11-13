"""Energotrendy Ukrainy (ETU) UAH price-list parser + SKU canonicalization."""

from __future__ import annotations

import unittest

from app.routers.bess_order import (
    _canonical_article,
    _merge_etu_items,
    _parse_etu_sheet_csv,
    _uah_to_usd,
    _with_promo_arrival,
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
        # Prepaid list price is always kept, even when BIOM cash wins.
        self.assertAlmostEqual(row["etuUsd"], _uah_to_usd(195000.0, fx) or 0, places=2)
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
        # Cheaper BIOM cash stays on installer columns; NL list price is separate.
        self.assertEqual(row["installerCheapestUsd"], 710.0)
        self.assertEqual(row["priceSourceCash"], "install")
        self.assertAlmostEqual(row["etuUsd"], _uah_to_usd(38500.0, fx) or 0, places=2)
        # Availability comes from ETU so the UI can select 5 kWh HV
        self.assertIn("Енерготренди", row["availabilityInstaller"])
        self.assertNotRegex(row["availabilityInstaller"], r"приход")

    def test_order_price_columns_and_arrival_window(self) -> None:
        csv_text = """\
"Прайс лист 11/11 Доступні до замовлення з поставкою в Київ 9-12 листопада  Низьковольні інвертори:  12k lp1, 10k lp3, 15k, 20к
Акумулятори:  pro c, f12 max, f16, f16max
6K інвертори будуть доступні під замовлення з поставкою на 24-27 листопада","К-сть фаз ","Потужність/ємність ","Модель ","Опис передплата 100%","Ціна під замовлення, грн","Ціна під замовлення, грн",""
"Deye","Однофазні","5KW","SUN-5K-SG05LP1-EU-AM2-P","DEYE низьковольтний однофазний інвертор","","",""
"Deye","Однофазні","6KW","SUN-6K-SG06LP1-EU-BM2","DEYE низьковольтний однофазний інвертор","39500","43000","24-27 листопада"
"Deye","Однофазні","12kw","SUN-12K-SG02LP1-EU-AM3","DEYE низьковольтний однофазний інвертор 12kw","73500","76000",""
"Deye","Низьковольний","12 KWH","DEYE SE-F12-С","Низьковольтна DEYE 12 kwh","","",""
"Deye","Низьковольний","12 KWH","DEYE SE-F12-MAX","Низьковольтна DEYE 12 kwh","77000","84000",""
"Deye","Низьковольний","5 KWH","SE-F5 Pro C","Низьковольтна універсальна","38000","38000",""
"""
        items = _parse_etu_sheet_csv(csv_text)
        by_art = {row["article"]: row for row in items.values()}
        self.assertNotIn("SUN-5K-SG05LP1-EU-AM2-P", by_art)
        self.assertNotIn("SE-F12-C", by_art)
        six = by_art["SUN-6K-SG06LP1-EU-BM2"]
        self.assertEqual(six["prepaidUah"], 39500.0)
        self.assertEqual(six["tovUah"], 43000.0)
        self.assertEqual(six["availability"], "24-27 листопада")
        twelve = by_art["SUN-12K-SG02LP1-EU"]
        self.assertEqual(twelve["availability"], "9-12 листопада")
        self.assertEqual(by_art["SE-F12-MAX"]["availability"], "9-12 листопада")
        self.assertEqual(by_art["SE-F5-PRO-C"]["availability"], "9-12 листопада")

    def test_promo_arrival_replaces_installer_window(self) -> None:
        self.assertEqual(_with_promo_arrival("10.12", "20.12.-30.12"), ("10.12", "10.12"))
        self.assertEqual(_with_promo_arrival("в наявності", "25.11.-30.11"), ("в наявності", "в наявності"))
        self.assertEqual(
            _with_promo_arrival("", "20.12.-30.12"),
            ("", "20.12.-30.12"),
        )
        self.assertEqual(
            _with_promo_arrival("закінчились", "дані про приходи відсутні"),
            ("закінчились", "закінчились"),
        )

    def test_merge_keeps_biom_date_when_biom_price_wins(self) -> None:
        fx = 45.3
        by_article = {
            "SUN-6K-SG06LP1-EU-BM2": {
                "article": "SUN-6K-SG06LP1-EU-BM2",
                "installerCheapestUsd": 740.0,
                "installerUsd": 740.0,
                "retailUsd": 815.0,
                "availability": "10.12",
                "availabilityInstaller": "10.12",
                "priceSourceCash": "install",
            }
        }
        etu = {
            "SUN6KSG06LP1EUBM2": {
                "article": "SUN-6K-SG06LP1-EU-BM2",
                "name": "6K",
                "brand": "deye",
                "prepaidUah": 39500.0,
                "tovUah": 43000.0,
                "availability": "24-27 листопада",
            }
        }
        _merge_etu_items(by_article, etu, fx)
        row = by_article["SUN-6K-SG06LP1-EU-BM2"]
        self.assertEqual(row["availability"], "10.12")
        self.assertEqual(row["availabilityInstaller"], "10.12")
        self.assertEqual(row["installerCheapestUsd"], 740.0)
        self.assertEqual(row["priceSourceCash"], "install")

    def test_merge_uses_etu_date_when_etu_price_wins(self) -> None:
        fx = 45.3
        by_article = {
            "SUN-12K-SG02LP1-EU": {
                "article": "SUN-12K-SG02LP1-EU",
                "installerCheapestUsd": 2000.0,
                "installerUsd": 2000.0,
                "retailUsd": 2200.0,
                "availability": "дані про приходи відсутні",
                "availabilityInstaller": "дані про приходи відсутні",
                "priceSourceCash": "install",
                "priceSourceRetail": "install",
            }
        }
        etu = {
            "SUN12KSG02LP1EU": {
                "article": "SUN-12K-SG02LP1-EU",
                "name": "12K",
                "brand": "deye",
                "prepaidUah": 73500.0,
                "tovUah": 76000.0,
                "availability": "9-12 листопада",
            }
        }
        _merge_etu_items(by_article, etu, fx)
        row = by_article["SUN-12K-SG02LP1-EU"]
        self.assertEqual(row["priceSourceCash"], "etu")
        self.assertEqual(row["availability"], "9-12 листопада")
        self.assertEqual(row["availabilityInstaller"], "9-12 листопада")


if __name__ == "__main__":
    unittest.main()
