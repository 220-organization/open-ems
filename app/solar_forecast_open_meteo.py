"""Tomorrow insolation forecast via Open-Meteo (server-side; coordinates stay on server)."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"


def _insolation_pct_from_daily_slice(
    daily: dict,
    day_index: int,
) -> tuple[Optional[int], Optional[str]]:
    times = daily.get("time")
    sun = daily.get("sunshine_duration")
    dayl = daily.get("daylight_duration")
    if not isinstance(times, list) or not isinstance(sun, list) or not isinstance(dayl, list):
        return None, None
    if len(times) <= day_index or len(sun) <= day_index or len(dayl) <= day_index:
        return None, None
    try:
        sun_s = float(sun[day_index])
        day_s = float(dayl[day_index])
    except (TypeError, ValueError, IndexError):
        return None, None
    if day_s <= 0 or sun_s < 0:
        return None, None
    pct = int(round(100.0 * min(sun_s, day_s) / day_s))
    pct = max(0, min(100, pct))
    date_str = str(times[day_index]) if times[day_index] is not None else None
    return pct, date_str


async def fetch_daily_insolation_percent(
    lat: float,
    lon: float,
    day_index: int = 0,
) -> tuple[Optional[int], Optional[str]]:
    """
    Insolation index (0–100) for a calendar day at coordinates (``timezone=auto``).

    ``day_index`` 0 = first day in the response (local today for that location).
    """
    need_days = max(1, int(day_index) + 1)
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "sunshine_duration,daylight_duration",
        "forecast_days": min(need_days, 16),
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(_OPEN_METEO_FORECAST, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("Open-Meteo forecast request failed (daily insolation)")
        return None, None
    daily = data.get("daily") if isinstance(data, dict) else None
    if not isinstance(daily, dict):
        return None, None
    return _insolation_pct_from_daily_slice(daily, day_index)


async def fetch_tomorrow_insolation_percent(lat: float, lon: float) -> tuple[Optional[int], Optional[str]]:
    """
    Forecast for the next calendar day at the given coordinates (Open-Meteo ``timezone=auto``).

    Returns (insolation_percent_0_100, date_yyyy_mm_dd) using
    sunshine_duration / daylight_duration for that day.
    """
    pct, date_str = await fetch_daily_insolation_percent(lat, lon, day_index=1)
    return pct, date_str
