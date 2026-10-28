"""Today/tomorrow insolation forecast via Open-Meteo (server-side; coordinates stay on server)."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
_MET_NORWAY_FORECAST = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
_MET_USER_AGENT = "OpenEMS/1.0 https://220-km.com"

# Daily mean cloud cover (0–100): at or above ⇒ "cloudy" icon for today.
_CLOUD_COVER_MEAN_CLOUDY_THRESHOLD = 45.0
# Forecasts barely move within a few hours. Caching keeps the free daily quota.
_FORECAST_CACHE_SEC = 6 * 60 * 60.0

_open_meteo_blocked_until = 0.0
_open_meteo_limit_logged = False
_forecast_cache: dict[tuple, tuple[float, Any]] = {}
_forecast_inflight: dict[tuple, asyncio.Task] = {}
_forecast_guard = asyncio.Lock()


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
    data = await _get_open_meteo(params)
    if data is None:
        return await _met_daily_insolation(lat, lon, day_index)
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
    data = await _get_open_meteo(params)
    if data is None:
        return await _cached_forecast("met-daily", lat, lon, lambda: _met_today_tomorrow(lat, lon))
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


def _get_zoned_hour_key(dt: datetime, tz: ZoneInfo) -> Optional[str]:
    return dt.strftime("%Y-%m-%dT%H")


def _get_zoned_date_key(dt: datetime, tz: ZoneInfo) -> Optional[str]:
    return dt.strftime("%Y-%m-%d")


def _add_days_to_date_key(date_key: str, days: int) -> Optional[str]:
    if not isinstance(date_key, str) or len(date_key) != 10:
        return None
    try:
        year, month, day = (int(x) for x in date_key.split("-"))
        next_day = datetime(year, month, day, tzinfo=ZoneInfo("UTC")) + timedelta(days=days)
        return next_day.strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _parse_hourly_insolation_for_date(
    data: dict,
    date_key: str,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Normalize Open-Meteo hourly shortwave radiation into one local calendar day."""
    hourly = data.get("hourly")
    tz_name = data.get("timezone")
    if not isinstance(hourly, dict) or not isinstance(tz_name, str) or not tz_name.strip():
        return None
    times = hourly.get("time")
    radiation = hourly.get("shortwave_radiation")
    if not isinstance(times, list) or not isinstance(radiation, list) or not date_key:
        return None
    try:
        tz = ZoneInfo(tz_name.strip())
    except Exception:
        return None

    local_now = now if now is not None else datetime.now(tz)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=tz)
    else:
        local_now = local_now.astimezone(tz)

    today_key = _get_zoned_date_key(local_now, tz)
    current_hour_key = _get_zoned_hour_key(local_now, tz)
    is_today = date_key == today_key

    hours: list[dict[str, Any]] = []
    for index, time_iso in enumerate(times):
        if not isinstance(time_iso, str) or not time_iso.startswith(date_key):
            continue
        try:
            hour = int(time_iso[11:13])
        except (TypeError, ValueError):
            continue
        if not 0 <= hour <= 23:
            continue
        raw = radiation[index] if index < len(radiation) else None
        try:
            radiation_wm2 = max(0.0, float(raw)) if raw is not None else 0.0
        except (TypeError, ValueError):
            radiation_wm2 = 0.0
        hour_key = time_iso[:13]
        hours.append(
            {
                "hour": hour,
                "radiationWm2": radiation_wm2,
                "isCurrent": is_today and hour_key == current_hour_key,
                "isPast": is_today and hour_key < current_hour_key,
            }
        )

    if not hours:
        return None

    max_radiation = max((entry["radiationWm2"] for entry in hours), default=1.0)
    max_radiation = max(max_radiation, 1.0)
    return {
        "timeZone": tz_name,
        "date": date_key,
        "hours": [
            {
                "hour": entry["hour"],
                "levelPct": int(round((entry["radiationWm2"] / max_radiation) * 100)),
                "isCurrent": entry["isCurrent"],
                "isPast": entry["isPast"],
            }
            for entry in hours
        ],
        "maxRadiationWm2": max_radiation,
    }


async def fetch_hourly_insolation_by_day(lat: float, lon: float) -> Optional[dict[str, Any]]:
    """
    Hourly shortwave-radiation bars for local today and tomorrow (Open-Meteo ``timezone=auto``).

    Coordinates stay server-side; response contains only normalized bar levels (0–100 per day).
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "shortwave_radiation",
        "forecast_days": 2,
        "timezone": "auto",
    }
    data = await _get_open_meteo(params)
    if data is None:
        return await _cached_forecast("met-hourly", lat, lon, lambda: _met_hourly(lat, lon))

    if not isinstance(data, dict):
        return None
    tz_name = data.get("timezone")
    if not isinstance(tz_name, str) or not tz_name.strip():
        return None
    try:
        tz = ZoneInfo(tz_name.strip())
    except Exception:
        return None

    local_now = datetime.now(tz)
    today_key = _get_zoned_date_key(local_now, tz)
    tomorrow_key = _add_days_to_date_key(today_key, 1) if today_key else None
    if not today_key or not tomorrow_key:
        return None

    today = _parse_hourly_insolation_for_date(data, today_key, local_now)
    tomorrow = _parse_hourly_insolation_for_date(data, tomorrow_key, local_now)
    if today is None and tomorrow is None:
        return None

    return {"today": today, "tomorrow": tomorrow}


def _coords_key(kind: str, lat: float, lon: float) -> tuple:
    return (kind, round(float(lat), 2), round(float(lon), 2))


def _tz_for_longitude(lon: float) -> timezone:
    hours = max(-12, min(14, int(round(float(lon) / 15.0))))
    return timezone(timedelta(hours=hours))


def _sun_is_up(lat_deg: float, when: datetime) -> bool:
    """True when a simple solar elevation at ``when`` (already in local time) is above the horizon."""
    lat = math.radians(float(lat_deg))
    decl = math.radians(23.44 * math.sin(math.radians((360.0 / 365.0) * (when.timetuple().tm_yday - 81))))
    hour = when.hour + when.minute / 60.0 + when.second / 3600.0
    hour_angle = math.radians(15.0 * (hour - 12.0))
    sin_elev = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
    return sin_elev > 0.0


def _block_open_meteo(body: str) -> None:
    global _open_meteo_blocked_until, _open_meteo_limit_logged
    now = datetime.now(timezone.utc)
    if "Daily API request limit" in body:
        until = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    else:
        until = now + timedelta(minutes=10)
    _open_meteo_blocked_until = until.timestamp()
    if not _open_meteo_limit_logged:
        _open_meteo_limit_logged = True
        logger.warning(
            "Open-Meteo is rate limited; insolation uses MET Norway until %s",
            until.isoformat(),
        )


async def _get_open_meteo(params: dict[str, Any]) -> Optional[dict[str, Any]]:
    if time.time() < _open_meteo_blocked_until:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(_OPEN_METEO_FORECAST, params=params)
            if response.status_code == 429:
                _block_open_meteo(response.text or "")
                return None
            response.raise_for_status()
            data = response.json()
    except Exception:
        logger.exception("Open-Meteo forecast request failed")
        return None
    return data if isinstance(data, dict) else None


async def _cached_forecast(kind: str, lat: float, lon: float, loader) -> Any:
    key = _coords_key(kind, lat, lon)
    now = time.monotonic()
    cached = _forecast_cache.get(key)
    if cached is not None and now - cached[0] < _FORECAST_CACHE_SEC:
        return cached[1]
    async with _forecast_guard:
        cached = _forecast_cache.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < _FORECAST_CACHE_SEC:
            return cached[1]
        task = _forecast_inflight.get(key)
        if task is None:
            task = asyncio.create_task(loader())
            _forecast_inflight[key] = task
    try:
        value = await task
    finally:
        async with _forecast_guard:
            if _forecast_inflight.get(key) is task:
                _forecast_inflight.pop(key, None)
    if value is not None:
        _forecast_cache[key] = (time.monotonic(), value)
    return value


def _cloud_samples(payload: dict[str, Any], tz: timezone) -> list[tuple[datetime, float]]:
    series = (payload.get("properties") or {}).get("timeseries")
    if not isinstance(series, list):
        return []
    samples: list[tuple[datetime, float]] = []
    for row in series:
        if not isinstance(row, dict):
            continue
        raw_time = row.get("time")
        details = ((row.get("data") or {}).get("instant") or {}).get("details") or {}
        cloud = details.get("cloud_area_fraction") if isinstance(details, dict) else None
        if not isinstance(raw_time, str) or cloud is None:
            continue
        try:
            moment = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).astimezone(tz)
            cover = max(0.0, min(100.0, float(cloud)))
        except (TypeError, ValueError):
            continue
        samples.append((moment, cover))
    return samples


def _daylight_pct(cloud_cover: float) -> float:
    """Diffuse light stays visible under full cloud; clear sky is 100."""
    cover = max(0.0, min(100.0, float(cloud_cover)))
    return 15.0 + 85.0 * (1.0 - cover / 100.0)


def insolation_pct_from_clouds(
    samples: list[tuple[datetime, float]],
    lat: float,
    date_key: str,
    *,
    now: datetime,
    zero_at_night: bool,
) -> Optional[int]:
    """Daylight-hour mean of cloud-adjusted sun, 0 after sunset when ``zero_at_night``."""
    daylight = [
        (moment, cover)
        for moment, cover in samples
        if moment.strftime("%Y-%m-%d") == date_key and _sun_is_up(lat, moment)
    ]
    if not daylight:
        return 0 if zero_at_night else None
    mean_clear = sum(_daylight_pct(cover) for _, cover in daylight) / len(daylight)
    pct = int(round(max(0.0, min(100.0, mean_clear))))
    if zero_at_night and not _sun_is_up(lat, now):
        return 0
    return pct


def hourly_bars_from_clouds(
    samples: list[tuple[datetime, float]],
    lat: float,
    date_key: str,
    now: datetime,
    tz: timezone,
) -> Optional[dict[str, Any]]:
    by_hour: dict[int, tuple[datetime, float]] = {}
    for moment, cover in samples:
        if moment.strftime("%Y-%m-%d") != date_key:
            continue
        by_hour[moment.hour] = (moment, cover)
    if not by_hour:
        return None
    levels: list[tuple[int, float, datetime]] = []
    for hour in sorted(by_hour):
        moment, cover = by_hour[hour]
        clear = 0.0 if not _sun_is_up(lat, moment) else _daylight_pct(cover)
        levels.append((hour, clear, moment))
    peak = max((level for _, level, _ in levels), default=0.0)
    local_now = now.astimezone(tz)
    today_key = local_now.strftime("%Y-%m-%d")
    hours = []
    for hour, level, moment in levels:
        level_pct = 0 if not _sun_is_up(lat, moment) else int(round(level))
        hours.append(
            {
                "hour": hour,
                "levelPct": level_pct,
                "isCurrent": date_key == today_key and hour == local_now.hour,
                "isPast": date_key == today_key and hour < local_now.hour,
            }
        )
    return {"timeZone": str(tz), "date": date_key, "hours": hours, "maxRadiationWm2": peak}


async def _fetch_met_norway(lat: float, lon: float) -> Optional[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                _MET_NORWAY_FORECAST,
                params={"lat": f"{float(lat):.4f}", "lon": f"{float(lon):.4f}"},
                headers={"User-Agent": _MET_USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        logger.warning("MET Norway forecast request failed")
        return None
    return data if isinstance(data, dict) else None


async def _met_cloud_bundle(lat: float, lon: float) -> Optional[dict[str, Any]]:
    async def load() -> Optional[dict[str, Any]]:
        payload = await _fetch_met_norway(lat, lon)
        if payload is None:
            return None
        tz = _tz_for_longitude(lon)
        samples = _cloud_samples(payload, tz)
        if not samples:
            return None
        return {"samples": samples, "tz": tz}

    return await _cached_forecast("met-raw", lat, lon, load)


async def _met_today_tomorrow(lat: float, lon: float) -> Optional[dict[str, Any]]:
    bundle = await _met_cloud_bundle(lat, lon)
    if bundle is None:
        return None
    tz: timezone = bundle["tz"]
    samples = bundle["samples"]
    now = datetime.now(tz)
    today_key = now.strftime("%Y-%m-%d")
    tomorrow_key = _add_days_to_date_key(today_key, 1)
    if not tomorrow_key:
        return None
    today_pct = insolation_pct_from_clouds(samples, lat, today_key, now=now, zero_at_night=True)
    tomorrow_pct = insolation_pct_from_clouds(
        samples, lat, tomorrow_key, now=now, zero_at_night=False
    )
    if today_pct is None or tomorrow_pct is None:
        return None
    daylight = [
        cover
        for moment, cover in samples
        if moment.strftime("%Y-%m-%d") == today_key and _sun_is_up(lat, moment)
    ]
    cloudy = (sum(daylight) / len(daylight)) >= _CLOUD_COVER_MEAN_CLOUDY_THRESHOLD if daylight else None
    return {
        "today": {"insolationPct": today_pct, "cloudy": cloudy, "date": today_key},
        "tomorrow": {"insolationPct": tomorrow_pct, "date": tomorrow_key},
    }


async def _met_hourly(lat: float, lon: float) -> Optional[dict[str, Any]]:
    bundle = await _met_cloud_bundle(lat, lon)
    if bundle is None:
        return None
    tz = bundle["tz"]
    samples = bundle["samples"]
    now = datetime.now(tz)
    today_key = now.strftime("%Y-%m-%d")
    tomorrow_key = _add_days_to_date_key(today_key, 1)
    if not tomorrow_key:
        return None
    today = hourly_bars_from_clouds(samples, lat, today_key, now, tz)
    tomorrow = hourly_bars_from_clouds(samples, lat, tomorrow_key, now, tz)
    if today is None and tomorrow is None:
        return None
    return {"today": today, "tomorrow": tomorrow}


async def _met_daily_insolation(
    lat: float, lon: float, day_index: int
) -> tuple[Optional[int], Optional[str]]:
    bundle = await _met_cloud_bundle(lat, lon)
    if bundle is None:
        return None, None
    tz = bundle["tz"]
    now = datetime.now(tz)
    today_key = now.strftime("%Y-%m-%d")
    date_key = today_key if int(day_index) <= 0 else _add_days_to_date_key(today_key, int(day_index))
    if not date_key:
        return None, None
    pct = insolation_pct_from_clouds(
        bundle["samples"],
        lat,
        date_key,
        now=now,
        zero_at_night=int(day_index) <= 0,
    )
    return pct, date_key
