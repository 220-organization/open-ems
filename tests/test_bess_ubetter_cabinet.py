"""Ubetter all-in-one cabinet row from the BIOM install sheet."""

from __future__ import annotations

import unittest

from app.routers.bess_order import _fill_missing_vat, _parse_sheet_csv

_CABINET_CSV = """\
Фото,Код,Артикул,Потужність,Ємність,MPPT,STS,Тип акумуляторів,Напруга вх/вих,Системи,Розміри,Вага,Інсталятор,"Інсталятор
(з ПДВ)",,Роздріб,"Роздріб
(з ПДВ)"
,28043,UBT-241KNFBN S125-A120P4,125кВт,241кВтг,120кВт (4 MPPT),170кВт,LiFePo4 (8000 циклів),AC230V/AC400V,AI EMS,1800x1250x2322,2310 кг,35900,40567,,41300,2662,в наявності
,1,SUN-TEST,6кВт,, , , , , , , ,100,113,,200,226,в наявності
"""


class TestUbetterCabinetSheet(unittest.TestCase):
    def test_cabinet_price_ignores_broken_vat_cell(self) -> None:
        _fx, items = _parse_sheet_csv(_CABINET_CSV, kind="install")
        _fill_missing_vat(items)
        row = items["UBT-241KNFBNS125-A120P4"]
        self.assertEqual(row["article"], "UBT-241KNFBN S125-A120P4")
        self.assertEqual(row["code"], "28043")
        self.assertIn("125кВт", row["name"])
        self.assertIn("241кВтг", row["name"])
        self.assertEqual(row["installerUsd"], 35900)
        self.assertEqual(row["installerCheapestUsd"], 35900)
        self.assertEqual(row["retailUsd"], 41300)
        self.assertEqual(row["retailVatUsd"], 49560)
        self.assertIn("наявності", row["availabilityInstaller"])
        # Sheet «Роздріб (з ПДВ)» is +13%; payers always get retail + 20%.
        other = items["SUN-TEST"]
        self.assertEqual(other["retailUsd"], 200)
        self.assertEqual(other["retailVatUsd"], 240)
        self.assertEqual(other["installerCheapestUsd"], 100)


if __name__ == "__main__":
    unittest.main()
