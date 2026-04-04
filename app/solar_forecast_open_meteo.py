"""Today/tomorrow insolation forecast via Open-Meteo (server-side; coordinates stay on server)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"

# Daily mean cloud cover (0–100): at or above ⇒ "cloudy" icon for today.
_CLOUD_COVER_MEAN_CLOUDY_THRESHOLD = 45.0


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


def _is_local_night_now(
    data_root: dict,
    daily: dict,
    day_index: int = 0,
) -> Optional[bool]:
    """
    True if current local time at the station is before today's sunrise or after today's sunset.

    Uses Open-Meteo ``timezone`` plus daily ``sunrise`` / ``sunset`` (local wall time).
    Returns None if data is missing (caller keeps daytime insolation %).
    """
    tz_name = data_root.get("timezone")
    if not isinstance(tz_name, str) or not tz_name.strip():
        return None
    sunrise = daily.get("sunrise")
    sunset = daily.get("sunset")
    if not isinstance(sunrise, list) or not isinstance(sunset, list):
        return None
    if len(sunrise) <= day_index or len(sunset) <= day_index:
        return None
    try:
        tz = ZoneInfo(tz_name.strip())
    except Exception:
        return None
    try:
        sr_raw = str(sunrise[day_index]).strip()
        ss_raw = str(sunset[day_index]).strip()
        sr_naive = datetime.fromisoformat(sr_raw.replace("Z", ""))
        ss_naive = datetime.fromisoformat(ss_raw.replace("Z", ""))
        sr = sr_naive.replace(tzinfo=tz)
        ss = ss_naive.replace(tzinfo=tz)
    except (ValueError, TypeError, OSError):
        return None
    now = datetime.now(tz)
    if now < sr or now > ss:
        return True
    return False


def _cloudy_from_daily_mean(daily: dict, day_index: int) -> Optional[bool]:
    """True if mean cloud cover for that day is high; None if metric missing."""
    clouds = daily.get("cloud_cover_mean")
    if not isinstance(clouds, list) or len(clouds) <= day_index:
        return None
    try:
        v = float(clouds[day_index])
    except (TypeError, ValueError, IndexError):
        return None
    return v >= _CLOUD_COVER_MEAN_CLOUDY_THRESHOLD


async def fetch_today_tomorrow_insolation_forecast(
    lat: float,
    lon: float,
) -> Optional[dict[str, Any]]:
    """
    Single Open-Meteo request: insolation % for today and tomorrow, plus cloudy flag for today.

    ``today.insolationPct`` is forced to **0** when local time at the plant is night
    (before sunrise or after sunset for that day).

    Returns None if the request fails or insolation cannot be parsed for both days.
    Structure::

        {
          "today": {"insolationPct": int, "cloudy": bool | null, "date": str | null},
          "tomorrow": {"insolationPct": int, "date": str | null},
        }
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "sunshine_duration,daylight_duration,cloud_cover_mean,sunrise,sunset",
        "forecast_days": 3,
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(_OPEN_METEO_FORECAST, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("Open-Meteo forecast request failed (today/tomorrow insolation)")
        return None
    daily = data.get("daily") if isinstance(data, dict) else None
    if not isinstance(daily, dict):
        return None

    t_pct, t_date = _insolation_pct_from_daily_slice(daily, 0)
    m_pct, m_date = _insolation_pct_from_daily_slice(daily, 1)
    if t_pct is None or m_pct is None:
        return None

    today_cloudy: Optional[bool] = _cloudy_from_daily_mean(daily, 0)
    today_pct_out = t_pct
    night = _is_local_night_now(data, daily, 0)
    if night is True:
        today_pct_out = 0

    return {
        "today": {
            "insolationPct": today_pct_out,
            "cloudy": today_cloudy,
            "date": t_date,
        },
        "tomorrow": {
            "insolationPct": m_pct,
            "date": m_date,
        },
    }
