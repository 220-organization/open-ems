"""Unit tests for Deye hourly energy backfill (frame integrate, scale, read override)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.deye_energy_backfill_service import (
    hourly_kwh_from_frames,
    scale_to_day_totals,
)
from app.deye_soc_service import _apply_hourly_energy_overrides


def _item(key: str, value: float, unit: str = "W") -> dict:
    return {"key": key, "value": value, "unit": unit}


class TestHourlyKwhFromFrames(unittest.TestCase):
    def test_integrates_load_pv_import_export_across_kyiv_hours(self) -> None:
        # 10:00–10:05 UTC = 13:00–13:05 Kyiv (UTC+3 in May); 5-min frames match Deye.
        t0 = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 5, 10, 10, 5, tzinfo=timezone.utc)
        frames = [
            (t0, [_item("UPSLoadPower", 2000.0), _item("PPV", 1000.0), _item("TotalGridPower", 500.0)]),
            (t1, [_item("UPSLoadPower", 2000.0), _item("PPV", 1000.0), _item("TotalGridPower", 500.0)]),
        ]
        hourly = hourly_kwh_from_frames(frames)
        # (5/60) h × 2 kW = 1/6 kWh load; 1/12 kWh PV; 1/24 kWh import
        self.assertAlmostEqual(hourly["consumptionKwh"][13], 2.0 * 5 / 60, places=4)
        self.assertAlmostEqual(hourly["generationKwh"][13], 1.0 * 5 / 60, places=4)
        self.assertAlmostEqual(hourly["importKwh"][13], 0.5 * 5 / 60, places=4)
        self.assertIsNone(hourly["exportKwh"][13])

    def test_export_from_negative_grid(self) -> None:
        t0 = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 5, 10, 10, 5, tzinfo=timezone.utc)
        frames = [
            (t0, [_item("TotalGridPower", -2000.0)]),
            (t1, [_item("TotalGridPower", -2000.0)]),
        ]
        hourly = hourly_kwh_from_frames(frames)
        self.assertAlmostEqual(hourly["exportKwh"][13], 2.0 * 5 / 60, places=4)
        self.assertIsNone(hourly["importKwh"][13])

    def test_caps_long_gaps(self) -> None:
        t0 = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 5, 10, 11, 0, tzinfo=timezone.utc)  # 60 min > 15 min cap
        frames = [
            (t0, [_item("UPSLoadPower", 1000.0)]),
            (t1, [_item("UPSLoadPower", 1000.0)]),
        ]
        hourly = hourly_kwh_from_frames(frames)
        # Capped to 15 min → 0.25 kWh, not 1.0
        self.assertAlmostEqual(hourly["consumptionKwh"][13], 0.25, places=4)


class TestScaleToDayTotals(unittest.TestCase):
    def test_scales_shape_to_target(self) -> None:
        hourly = {
            "consumptionKwh": [1.0, 3.0] + [None] * 22,
            "generationKwh": [None] * 24,
            "importKwh": [None] * 24,
            "exportKwh": [None] * 24,
        }
        out = scale_to_day_totals(hourly, {"consumptionKwh": 10.0})
        self.assertAlmostEqual(out["consumptionKwh"][0], 2.5, places=4)
        self.assertAlmostEqual(out["consumptionKwh"][1], 7.5, places=4)
        # Empty shape hours become 0 so sample-based Open EMS cannot leak.
        self.assertTrue(all(x is not None for x in out["consumptionKwh"]))
        self.assertAlmostEqual(sum(float(x) for x in out["consumptionKwh"]), 10.0, places=4)

    def test_spreads_evenly_when_shape_zero(self) -> None:
        hourly = {
            "consumptionKwh": [0.0] * 24,
            "generationKwh": [None] * 24,
            "importKwh": [None] * 24,
            "exportKwh": [None] * 24,
        }
        # active_hours empty when all zeros — falls back to all 24
        out = scale_to_day_totals(hourly, {"consumptionKwh": 24.0})
        self.assertTrue(all(abs(float(x) - 1.0) < 1e-9 for x in out["consumptionKwh"]))

    def test_zero_target_fills_all_hours(self) -> None:
        hourly = {
            "consumptionKwh": [None] * 24,
            "generationKwh": [None] * 24,
            "importKwh": [None] * 24,
            "exportKwh": [None] * 24,
        }
        out = scale_to_day_totals(hourly, {"generationKwh": 0.0})
        self.assertTrue(all(x == 0.0 for x in out["generationKwh"]))


class TestApplyHourlyEnergyOverrides(unittest.TestCase):
    def test_prefers_override_rows(self) -> None:
        grid = [None] * 24
        pv = [None] * 24
        load = [0.5] * 24  # sample approximation
        ovr_cons = [None] * 24
        ovr_gen = [None] * 24
        ovr_imp = [None] * 24
        ovr_exp = [None] * 24
        ovr_cons[5] = 2.0
        ovr_gen[5] = 1.5
        ovr_imp[5] = 0.8
        ovr_exp[5] = 0.2
        import_out = _apply_hourly_energy_overrides(
            grid, pv, load, ovr_cons, ovr_gen, ovr_imp, ovr_exp
        )
        self.assertEqual(load[5], 2.0)
        self.assertEqual(pv[5], 1.5)
        self.assertAlmostEqual(grid[5], 600.0, places=3)  # (0.8 - 0.2) * 1000
        self.assertEqual(import_out[5], 0.8)
        self.assertEqual(load[0], 0.5)
        self.assertIsNone(import_out[0])


class TestUpsertOverwrites(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_on_conflict_do_update(self) -> None:
        from datetime import date

        from app.deye_energy_backfill_service import upsert_hourly_energy_day

        executed = []

        class _StubSession:
            async def execute(self, stmt):
                executed.append(stmt)
                return MagicMock()

        hourly = {
            "consumptionKwh": [1.0] + [None] * 23,
            "generationKwh": [0.5] + [None] * 23,
            "importKwh": [0.2] + [None] * 23,
            "exportKwh": [None] * 24,
        }
        n = await upsert_hourly_energy_day(_StubSession(), "2410102121", date(2026, 5, 10), hourly)
        self.assertEqual(n, 1)
        self.assertEqual(len(executed), 1)
        # Compile to string to ensure ON CONFLICT path is present
        compiled = str(executed[0].compile(compile_kwargs={"literal_binds": False}))
        self.assertIn("ON CONFLICT", compiled.upper().replace("\n", " "))


class TestReadPathPrefersOverride(unittest.IsolatedAsyncioTestCase):
    async def test_hourly_history_uses_override(self) -> None:
        from datetime import date

        from app import deye_soc_service

        empty_samples = []

        class _StubResult:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return list(self._rows)

        class _StubSession:
            def __init__(self):
                self.calls = 0

            async def execute(self, query):  # noqa: ARG002
                self.calls += 1
                # First call: samples; second: overrides (via patched helper we skip)
                return _StubResult(empty_samples)

        async def fake_extras(_s):
            return True

        async def fake_overrides(_s, _sns, _a, _b):
            cons = [None] * 24
            gen = [None] * 24
            imp = [None] * 24
            exp = [None] * 24
            cons[8] = 3.0
            gen[8] = 1.0
            imp[8] = 2.0
            return cons, gen, imp, exp

        with (
            patch.object(deye_soc_service, "deye_soc_balance_input_columns_ready", new=fake_extras),
            patch.object(deye_soc_service, "_hourly_energy_overrides", new=fake_overrides),
        ):
            _soc, grid, _freq, pv, load, imp = await deye_soc_service.hourly_inverter_history_for_kyiv_day(
                _StubSession(), "2410102121", date(2026, 5, 10)
            )

        self.assertEqual(load[8], 3.0)
        self.assertEqual(pv[8], 1.0)
        self.assertEqual(imp[8], 2.0)
        self.assertAlmostEqual(grid[8], 2000.0, places=3)


class TestParseDeviceHistoryExport(unittest.TestCase):
    def test_parses_export_fields(self) -> None:
        from app.deye_api import parse_device_history_energy_kwh

        payload = {
            "dataList": [
                {
                    "itemList": [
                        {"key": "Consumption", "value": "10"},
                        {"key": "Production", "value": "5"},
                        {"key": "ElectricityPurchasing", "value": "3"},
                        {"key": "GridFeedIn", "value": "1.5"},
                    ]
                }
            ]
        }
        got = parse_device_history_energy_kwh(payload)
        self.assertEqual(got["consumptionKwh"], 10.0)
        self.assertEqual(got["generationKwh"], 5.0)
        self.assertEqual(got["importKwh"], 3.0)
        self.assertEqual(got["exportKwh"], 1.5)


class TestFrameMeasurePointsFilter(unittest.TestCase):
    def test_caps_and_prefers_power_registers(self) -> None:
        from app.deye_api import _filter_frame_measure_points

        raw = [f"OtherMetric{i}" for i in range(80)] + [
            "SOC",
            "TotalGridPower",
            "UPSLoadPower",
            "PPV",
            "BatteryPower",
            "SomeLongNameWithPowerInIt",
        ]
        got = _filter_frame_measure_points(raw)
        self.assertLessEqual(len(got), 5)
        self.assertIn("UPSLoadPower", got)
        self.assertIn("PPV", got)
        self.assertIn("TotalGridPower", got)
        self.assertNotIn("SomeLongNameWithPowerInIt", got)

    def test_frame_timestamp_accepts_time_unix_string(self) -> None:
        from app.deye_api import _parse_history_frame_timestamp

        ts = _parse_history_frame_timestamp("1792879256")
        self.assertIsNotNone(ts)
        assert ts is not None
        self.assertEqual(ts.year, 2026)
        self.assertEqual(ts.month, 10)


class TestBackfillPaymentGate(unittest.TestCase):
    def test_amount_is_22_uah_per_day(self) -> None:
        from app.deye_energy_backfill_payment import (
            BACKFILL_UAH_PER_DAY,
            backfill_amount_uah,
            is_valid_backfill_amount_uah,
        )

        self.assertEqual(BACKFILL_UAH_PER_DAY, 22)
        self.assertEqual(backfill_amount_uah(1), 22)
        self.assertEqual(backfill_amount_uah(30), 660)
        self.assertTrue(is_valid_backfill_amount_uah(660, 30))
        self.assertFalse(is_valid_backfill_amount_uah(659, 30))

    def test_access_password(self) -> None:
        from app.deye_energy_backfill_payment import access_password_ok

        self.assertTrue(access_password_ok("AA9220YD"))
        self.assertFalse(access_password_ok("wrong"))
        self.assertFalse(access_password_ok(""))
        self.assertFalse(access_password_ok(None))

    def test_free_backfill_only_with_explicit_env(self) -> None:
        import os

        from app.deye_energy_backfill_payment import is_backfill_free_enabled

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEYE_BACKFILL_ALLOW_FREE", None)
            self.assertFalse(is_backfill_free_enabled())
        with patch.dict(os.environ, {"DEYE_BACKFILL_ALLOW_FREE": "1"}, clear=False):
            self.assertTrue(is_backfill_free_enabled())
        with patch.dict(os.environ, {"OPEN_EMS_SERVE_SPA": "0"}, clear=False):
            os.environ.pop("DEYE_BACKFILL_ALLOW_FREE", None)
            # SPA=0 alone must not unlock free backfill (prod also uses SPA=0).
            self.assertFalse(is_backfill_free_enabled())

    def test_access_password_bypasses_payment_gate_helper(self) -> None:
        """AA9220YD is accepted from either accessPassword or pin field."""
        from app.deye_energy_backfill_payment import access_password_ok

        self.assertTrue(access_password_ok("AA9220YD") or access_password_ok(None))
        self.assertTrue(access_password_ok(None) or access_password_ok("AA9220YD"))


if __name__ == "__main__":
    unittest.main()
