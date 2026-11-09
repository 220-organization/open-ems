"""Sigenergy 50 kW / 60 kWh catalog overlay for /order-bess."""

from __future__ import annotations

import unittest

from app.routers.bess_order import _SIGENERGY_AVAIL, _merge_sigenergy_catalog


class TestSigenergyCatalog(unittest.TestCase):
    def test_overlay_sets_ex_vat_cash_and_ten_day_lead_time(self) -> None:
        items: dict = {}
        _merge_sigenergy_catalog(items)
        inv = items["SIGENPV50M1-HYB"]
        bat = items["SIGENSTACKBAT12.0"]
        self.assertEqual(inv["installerCheapestUsd"], 4633.20)
        self.assertEqual(inv["retailVatUsd"], 5559.84)
        self.assertEqual(inv["availability"], _SIGENERGY_AVAIL)
        self.assertEqual(bat["installerCheapestUsd"], 1853.28)
        self.assertEqual(bat["availabilityInstaller"], "10 днів")
        # 1 inverter + 5×12 kWh + 1C controller + 1C base, cash (ex VAT).
        total = (
            inv["installerCheapestUsd"]
            + bat["installerCheapestUsd"] * 5
            + items["SIGENSTACKBCM2-1C-BST"]["installerCheapestUsd"]
            + items["SIGENSTACKBASEMAIN-1C"]["installerCheapestUsd"]
        )
        self.assertAlmostEqual(total, 21312.72, places=2)

    def test_sigenstor_ec_6_sp_single_phase_price(self) -> None:
        items: dict = {}
        _merge_sigenergy_catalog(items)
        inv = items["SIGENSTOREC6.0SP"]
        self.assertEqual(inv["installerCheapestUsd"], 1548.30)
        self.assertEqual(inv["retailVatUsd"], 1857.96)
        self.assertIn("1 фаза", inv["name"])
        self.assertEqual(inv["availability"], _SIGENERGY_AVAIL)


if __name__ == "__main__":
    unittest.main()
