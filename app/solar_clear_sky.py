"""
Clear-sky solar elevation shape for Kyiv-calendar hourly buckets (plant GPS, mid-hour sample).

Used to extrapolate expected PV after the battery reaches 100% SoC (clipping) without exposing
coordinates to the browser.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


def _sun_elevation_deg(lat_deg: float, lon_deg: float, dt_utc: datetime) -> float:
    """Approximate solar elevation (degrees above horizon) for UTC instant; east longitude positive."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(timezone.utc)

    lat = math.radians(lat_deg)
    n = int(dt_utc.timetuple().tm_yday)
    decl = math.radians(23.45) * math.sin(math.radians(360.0 / 365.0 * (284 + n)))
    utc_decimal = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    b = math.radians(360.0 * (n - 81) / 364.0)
    eot_min = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    solar_time_h = utc_decimal + lon_deg / 15.0 + eot_min / 60.0
    ha = math.radians(15.0 * (solar_time_h - 12.0))
    sin_el = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(ha)
    sin_el = max(-1.0, min(1.0, sin_el))
    return math.degrees(math.asin(sin_el))


def kyiv_day_hourly_clear_sky_weights(lat_deg: float, lon_deg: float, trade_day: date) -> list[float]:
    """
    24 non-negative weights for Kyiv wall hours 0..23 (display hours 1..24).

    Weight ~ sin(elevation) at the half-hour of each bucket,0 at/below horizon.
    """
    w: list[float] = []
    for h in range(24):
        t_kyiv = datetime(
            trade_day.year,
            trade_day.month,
            trade_day.day,
            h,
            30,
            0,
            tzinfo=KYIV,
        )
        t_utc = t_kyiv.astimezone(timezone.utc)
        el = _sun_elevation_deg(lat_deg, lon_deg, t_utc)
        rad = math.radians(el)
        s = math.sin(rad) if el > 0 else 0.0
        w.append(max(0.0, s))
    return w
