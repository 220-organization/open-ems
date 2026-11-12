"""Sigenergy 50 kW / 60 kWh catalog overlay for /order-bess."""

from __future__ import annotations

import unittest

from app.routers.bess_order import _SIGENERGY_AVAIL, _merge_sigenergy_catalog


class TestSigenergyCatalog(unittest.TestCase):
    def test_overlay_sets_ex_vat_cash_and_ten_day_lead_time(self) -> None:
        items: dict = {}
        _merge_sigenergy_catalog(items)
        inv = items["SIGENPV50M1-HYB"]
        bat = items["SIGENSTACKBAT12.06"]
        self.assertEqual(inv["installerCheapestUsd"], 3742)
        self.assertEqual(inv["retailUsd"], 4633)
        self.assertEqual(inv["retailVatUsd"], 5560)
        self.assertEqual(inv["availability"], _SIGENERGY_AVAIL)
        self.assertEqual(inv["imageUrl"], "/static/bess/sigen-ci-hyb.jpg")
        self.assertEqual(bat["installerCheapestUsd"], 1496)
        self.assertEqual(bat["availabilityInstaller"], "10 днів")
        self.assertEqual(items["SIGENSTACKCOVER"]["installerCheapestUsd"], 206)
        self.assertEqual(items["SIGENSTACKBCCABLES4M"]["installerCheapestUsd"], 206)
        self.assertEqual(
            items["SIGENCOMMUNICATIONMODULE"]["installerCheapestUsd"], 101
        )
        self.assertEqual(
            items["SIGENSTACKBCM2-0.5C-BST"]["installerCheapestUsd"], 3119
        )
        # 1 inverter + 4×12 kWh (datasheet minimum) + 1C controller + 1C base, installer purchase.
        total = (
            inv["installerCheapestUsd"]
            + bat["installerCheapestUsd"] * 4
            + items["SIGENSTACKBCM2-1C-BST"]["installerCheapestUsd"]
            + items["SIGENSTACKBASEMAIN-1C"]["installerCheapestUsd"]
        )
        self.assertAlmostEqual(total, 15712, places=2)

    def test_sigenstor_ec_6_sp_single_phase_price(self) -> None:
        items: dict = {}
        _merge_sigenergy_catalog(items)
        inv = items["SIGENSTOREC6.0SP"]
        self.assertEqual(inv["installerCheapestUsd"], 1309)
        self.assertEqual(inv["retailUsd"], 1621)
        self.assertEqual(inv["retailVatUsd"], 1945)
        self.assertEqual(inv["imageUrl"], "/static/bess/sigen-stor-ec-sp.jpg")
        self.assertIn("1 фаза", inv["name"])
        self.assertEqual(inv["availability"], _SIGENERGY_AVAIL)


if __name__ == "__main__":
    unittest.main()
