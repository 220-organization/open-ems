"""Insolation from cloud cover when Open-Meteo is over its daily limit."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.solar_forecast_open_meteo import (
    _sun_is_up,
    hourly_bars_from_clouds,
    insolation_pct_from_clouds,
)


def _local(hour: int, day: int = 28) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=timezone(timedelta(hours=2)))


class TestCloudInsolation(unittest.TestCase):
    def test_noon_is_day_and_evening_is_night(self) -> None:
        self.assertTrue(_sun_is_up(47.7, _local(12)))
        self.assertFalse(_sun_is_up(47.7, _local(21)))

    def test_daylight_mean_ignores_night_cloud(self) -> None:
        samples = [
            (_local(12), 20.0),
            (_local(13), 40.0),
            (_local(21), 100.0),
        ]
        pct = insolation_pct_from_clouds(
            samples,
            47.7,
            "2026-10-28",
            now=_local(12),
            zero_at_night=False,
        )
        # 20% and 40% cloud, diffuse curve, night ignored. Mean of 83 and 66 rounds to 74.
        self.assertEqual(pct, 74)

    def test_today_is_zero_after_sunset(self) -> None:
        samples = [(_local(12), 10.0), (_local(13), 10.0)]
        pct = insolation_pct_from_clouds(
            samples,
            47.7,
            "2026-10-28",
            now=_local(21),
            zero_at_night=True,
        )
        self.assertEqual(pct, 0)

    def test_hourly_bars_keep_a_daytime_shape(self) -> None:
        samples = [(_local(h), 90.0 if h == 12 else 10.0) for h in (9, 12, 15, 21)]
        bars = hourly_bars_from_clouds(samples, 47.7, "2026-10-28", _local(13), timezone(timedelta(hours=2)))
        self.assertIsNotNone(bars)
        by_hour = {row["hour"]: row["levelPct"] for row in bars["hours"]}
        self.assertEqual(by_hour[21], 0)
        self.assertGreater(by_hour[9], by_hour[12])
        self.assertGreater(by_hour[9], 80)
