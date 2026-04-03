"""Tomorrow insolation forecast via Open-Meteo (server-side; coordinates stay on server)."""

from __future__ import annotations

import logging
import httpx

logger = logging.getLogger(__name__)

_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"


async def fetch_tomorrow_insolation_percent(lat: float, lon: float) -> tuple[Optional[int], Optional[str]]:
    """
    Forecast for the next calendar day at the given coordinates (Open-Meteo ``timezone=auto``).

    Returns (insolation_percent_0_100, date_yyyy_mm_dd) using
    sunshine_duration / daylight_duration for that day.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "sunshine_duration,daylight_duration",
        "forecast_days": 2,
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(_OPEN_METEO_FORECAST, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("Open-Meteo forecast request failed")
        return None, None

    daily = data.get("daily") if isinstance(data, dict) else None
    if not isinstance(daily, dict):
        return None, None
    times = daily.get("time")
    sun = daily.get("sunshine_duration")
    dayl = daily.get("daylight_duration")
    if not isinstance(times, list) or len(times) < 2:
        return None, None
    if not isinstance(sun, list) or not isinstance(dayl, list):
        return None, None
    if len(sun) < 2 or len(dayl) < 2:
        return None, None

    # Index 0 = local today, 1 = local tomorrow (Open-Meteo convention for timezone=auto).
    try:
        sun_s = float(sun[1])
        day_s = float(dayl[1])
    except (TypeError, ValueError, IndexError):
        return None, None
    if day_s <= 0 or sun_s < 0:
        return None, None
    pct = int(round(100.0 * min(sun_s, day_s) / day_s))
    pct = max(0, min(100, pct))
    date_str = str(times[1]) if times[1] is not None else None
    return pct, date_str
