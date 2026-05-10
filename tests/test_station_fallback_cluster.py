"""Cluster-aware Deye aggregation: /station/latest fallback must not multiply plant totals.

Covers two layers:

* ``_fill_missing_metrics_from_station_latest`` — plant fallback only fills POWER on ONE
  representative serial per station (so cluster snapshot persistence stores plant totals once).
* ``hourly_inverter_history_for_kyiv_day_cluster`` — bucket-level dedup of identical
  ``(pv, load, grid, battery)`` tuples (handles legacy duplicated rows already in the DB).
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional
from unittest.mock import patch

from app import deye_api
from app.deye_api import _fill_missing_metrics_from_station_latest


@dataclass
class _StubInverterRow:
    device_sn: str
    label: str
    pin_code: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    station_id: Optional[str]


_PLANT_TUPLE = (90.0, 12000.0, 25750.0, 13940.0, -2040.0, 50.0)


async def _fake_fetch_station_latest_metrics(
    client, headers, base, station_id  # noqa: ARG001 — match real signature
):
    """Plant aggregate /station/latest returns SoC + plant totals (battery, load, pv, grid, freq)."""
    return _PLANT_TUPLE


class TestFillMissingMetricsFromStationLatest(unittest.IsolatedAsyncioTestCase):
    async def test_plant_fallback_fills_only_one_representative_serial(self) -> None:
        """1 MWh-class station: 3 cluster serials, all missing /device/latest → only smallest sn gets plant power."""
        rows = [
            _StubInverterRow("2509280353", "BIG-A", None, None, None, "ST-1"),
            _StubInverterRow("2509280400", "BIG-B", None, None, None, "ST-1"),
            _StubInverterRow("2509280450", "BIG-C", None, None, None, "ST-1"),
        ]
        merged = {sn: (None, None, None, None, None, None) for sn in (
            "2509280353",
            "2509280400",
            "2509280450",
        )}
        marks: set[str] = set()

        with patch.object(deye_api, "_list_inverter_rows", return_value=rows), patch.object(
            deye_api, "_fetch_station_latest_metrics", new=_fake_fetch_station_latest_metrics
        ):
            await _fill_missing_metrics_from_station_latest(
                client=None, headers={}, base="", merged_fetch=merged, station_fallback_marks=marks
            )

        rep = "2509280353"
        self.assertEqual(merged[rep][0], 90.0, "rep gets SoC fallback")
        self.assertEqual(merged[rep][1], 12000.0, "rep gets battery fallback")
        self.assertEqual(merged[rep][2], 25750.0, "rep gets load fallback")
        self.assertEqual(merged[rep][3], 13940.0, "rep gets PV fallback")
        self.assertEqual(merged[rep][4], -2040.0, "rep gets grid fallback")
        self.assertEqual(marks, {rep}, "only rep marked as station fallback")

        for slave in ("2509280400", "2509280450"):
            self.assertEqual(merged[slave][0], 90.0, "slaves still get SoC fallback (per-device meaningful)")
            self.assertIsNone(merged[slave][1], "slaves keep None battery — avoids cluster doubling")
            self.assertIsNone(merged[slave][2], "slaves keep None load")
            self.assertIsNone(merged[slave][3], "slaves keep None pv")
            self.assertIsNone(merged[slave][4], "slaves keep None grid")

    async def test_skips_power_fallback_when_any_serial_has_device_data(self) -> None:
        """Mixed cluster: serial A has /device/latest power → don't overlay plant total on B."""
        rows = [
            _StubInverterRow("AAA", "INV-A", None, None, None, "ST-2"),
            _StubInverterRow("BBB", "INV-B", None, None, None, "ST-2"),
        ]
        merged = {
            "AAA": (None, 1000.0, 500.0, 7000.0, -200.0, 50.0),  # device-level power present
            "BBB": (None, None, None, None, None, None),
        }
        marks: set[str] = set()

        with patch.object(deye_api, "_list_inverter_rows", return_value=rows), patch.object(
            deye_api, "_fetch_station_latest_metrics", new=_fake_fetch_station_latest_metrics
        ):
            await _fill_missing_metrics_from_station_latest(
                client=None, headers={}, base="", merged_fetch=merged, station_fallback_marks=marks
            )

        self.assertEqual(merged["AAA"][1], 1000.0)
        self.assertEqual(merged["BBB"][0], 90.0, "B still gets SoC fallback")
        self.assertIsNone(merged["BBB"][1], "B should NOT receive plant power when A has per-inverter power")
        self.assertIsNone(merged["BBB"][2])
        self.assertIsNone(merged["BBB"][3])
        self.assertIsNone(merged["BBB"][4])
        self.assertEqual(marks, set(), "no station-fallback marks when per-inverter mode applies")

    async def test_single_serial_station_still_gets_full_fallback(self) -> None:
        rows = [_StubInverterRow("LONE", "Solo", None, None, None, "ST-3")]
        merged = {"LONE": (None, None, None, None, None, None)}
        marks: set[str] = set()

        with patch.object(deye_api, "_list_inverter_rows", return_value=rows), patch.object(
            deye_api, "_fetch_station_latest_metrics", new=_fake_fetch_station_latest_metrics
        ):
            await _fill_missing_metrics_from_station_latest(
                client=None, headers={}, base="", merged_fetch=merged, station_fallback_marks=marks
            )

        self.assertEqual(merged["LONE"], _PLANT_TUPLE)
        self.assertEqual(marks, {"LONE"})


class TestHourlyClusterDedup(unittest.IsolatedAsyncioTestCase):
    """``hourly_inverter_history_for_kyiv_day_cluster`` must dedupe identical bucket tuples."""

    async def test_duplicate_station_fallback_rows_dedupe_per_bucket(self) -> None:
        from app import deye_soc_service

        sns = ["AAA", "BBB", "CCC"]

        # 13:00 Kyiv (UTC+3) → 10:00 UTC bucket
        bucket = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)

        # Every cluster serial recorded the same plant aggregate (legacy /station/latest fallback rows).
        plant_pv = 13_940.0
        plant_load = 25_750.0
        plant_grid = -2_040.0
        plant_bat = 12_000.0

        rows = [
            (sn, bucket, 90.0, plant_grid, 50.0, plant_load, plant_pv, plant_pv, plant_bat)
            for sn in sns
        ]

        class _StubResult:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return list(self._rows)

        async def fake_extras_ready(_session):
            return True

        async def fake_execute(_query):
            return _StubResult(rows)

        class _StubSession:
            async def execute(self, query):
                return await fake_execute(query)

        with patch.object(
            deye_soc_service, "deye_soc_balance_input_columns_ready", new=fake_extras_ready
        ):
            soc, grid, freq, pv_kwh, load_kwh = (
                await deye_soc_service.hourly_inverter_history_for_kyiv_day_cluster(
                    _StubSession(), sns, date(2026, 5, 10)
                )
            )

        h_kyiv = 13
        self.assertEqual(soc[h_kyiv], 90.0, "SoC averaged across cluster, not summed")
        self.assertAlmostEqual(grid[h_kyiv], plant_grid, places=3, msg="grid is plant total, not 3 × plant")
        self.assertAlmostEqual(
            pv_kwh[h_kyiv], plant_pv / 1000.0, places=3, msg="PV kWh is plant total, not 3 × plant"
        )
        self.assertAlmostEqual(
            load_kwh[h_kyiv], plant_load / 1000.0, places=3, msg="Load kWh is plant total, not 3 × plant"
        )
        # Other hours stay None
        self.assertIsNone(grid[0])
        self.assertIsNone(grid[h_kyiv - 1])

    async def test_distinct_per_inverter_rows_still_sum(self) -> None:
        """Per-inverter mode (each /device/latest returns distinct watts) must still SUM to plant total."""
        from app import deye_soc_service

        sns = ["AAA", "BBB"]
        bucket = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)

        rows = [
            ("AAA", bucket, 90.0, -1_000.0, 50.0, 12_000.0, 7_000.0, 7_000.0, 6_000.0),
            ("BBB", bucket, 92.0, -1_040.0, 50.05, 13_750.0, 6_940.0, 6_940.0, 6_000.0),
        ]

        class _StubResult:
            def all(self):
                return list(rows)

        class _StubSession:
            async def execute(self, query):  # noqa: ARG002 — single query stub
                return _StubResult()

        async def fake_extras_ready(_session):
            return True

        with patch.object(
            deye_soc_service, "deye_soc_balance_input_columns_ready", new=fake_extras_ready
        ):
            soc, grid, freq, pv_kwh, load_kwh = (
                await deye_soc_service.hourly_inverter_history_for_kyiv_day_cluster(
                    _StubSession(), sns, date(2026, 5, 10)
                )
            )

        h_kyiv = 13
        self.assertAlmostEqual(soc[h_kyiv], 91.0, places=3, msg="SoC averaged across distinct values")
        self.assertAlmostEqual(grid[h_kyiv], -2_040.0, places=3, msg="grid summed (-1000 + -1040)")
        self.assertAlmostEqual(
            pv_kwh[h_kyiv], (7_000.0 + 6_940.0) / 1000.0, places=3, msg="PV kWh summed"
        )
        self.assertAlmostEqual(
            load_kwh[h_kyiv], (12_000.0 + 13_750.0) / 1000.0, places=3, msg="Load kWh summed"
        )


if __name__ == "__main__":
    unittest.main()
