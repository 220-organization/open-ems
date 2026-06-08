"""BESS capacity estimate from deep-discharge energy balance."""

from __future__ import annotations

import unittest

from app.deye_battery_capacity_service import estimate_capacity_kwh_from_balance


class TestBatteryCapacityEstimate(unittest.TestCase):
    def test_deep_discharge_balance(self) -> None:
        # 50 kWh load, 5 kWh grid, 10 kWh solar → 35 kWh from battery; 70% → 50 kWh pack
        cap = estimate_capacity_kwh_from_balance(
            load_kwh=50.0,
            grid_import_kwh=5.0,
            solar_kwh=10.0,
            soc_start=80.0,
            soc_end=10.0,
            hit_target=True,
        )
        self.assertAlmostEqual(cap, 50.0, places=2)

    def test_rejects_shallow_soc_delta(self) -> None:
        self.assertIsNone(
            estimate_capacity_kwh_from_balance(
                load_kwh=20.0,
                grid_import_kwh=2.0,
                solar_kwh=1.0,
                soc_start=60.0,
                soc_end=55.0,
            )
        )

    def test_rejects_negative_battery_energy(self) -> None:
        self.assertIsNone(
            estimate_capacity_kwh_from_balance(
                load_kwh=5.0,
                grid_import_kwh=10.0,
                solar_kwh=2.0,
                soc_start=80.0,
                soc_end=20.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
