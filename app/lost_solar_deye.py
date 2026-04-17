"""
Lost solar (clipped PV) kWh for Deye — same heuristic as the DAM chart (clear-sky shape + first ~100% SoC hour).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.deye_soc_service import hourly_inverter_history_for_kyiv_day
from app.oree_dam_service import KYIV
from app.solar_clear_sky import kyiv_day_hourly_clear_sky_weights


def _synthetic_midday_clear_sky_weights_24() -> list[float]:
    w = [0.0] * 24
    for i in range(24):
        dist = abs(i + 0.5 - 12.5)
        if dist < 8.0:
            w[i] = max(0.0, 1.0 - (dist / 8.0) ** 2)
    return w


def _median_positive(nums: list[float]) -> Optional[float]:
    s = sorted(x for x in nums if x == x and x > 0)
    if not s:
        return None
    m = len(s) // 2
    if len(s) % 2:
        return float(s[m])
    return (float(s[m - 1]) + float(s[m])) / 2.0


def _is_soc_full_percent(soc: Optional[float]) -> bool:
    if soc is None:
        return False
    try:
        return float(soc) >= 99.5
    except (TypeError, ValueError):
        return False


def _lost_solar_kwh_from_hourly(
    hourly_soc: list[Optional[float]],
    hourly_pv_kwh: list[Optional[float]],
    weights: list[float],
) -> Optional[float]:
    if len(hourly_soc) != 24 or len(hourly_pv_kwh) != 24 or len(weights) != 24:
        return None
    i0 = -1
    for i in range(24):
        if _is_soc_full_percent(hourly_soc[i]):
            i0 = i
            break
    if i0 < 0:
        return None
    full_hours = sum(1 for i in range(24) if _is_soc_full_percent(hourly_soc[i]))
    if full_hours < 1:
        return None

    ratios: list[float] = []
    for i in range(i0):
        pv = hourly_pv_kwh[i]
        ww = weights[i]
        if pv is not None and float(pv) > 0 and ww > 1e-8:
            ratios.append(float(pv) / ww)
    scale = _median_positive(ratios)
    if scale is None:
        pv0 = hourly_pv_kwh[i0]
        ww0 = weights[i0]
        if pv0 is not None and float(pv0) > 0 and ww0 > 1e-8:
            scale = float(pv0) / ww0
    if scale is None or scale <= 0:
        return None

    total = 0.0
    for i in range(i0, 24):
        if not _is_soc_full_percent(hourly_soc[i]):
            continue
        predicted = scale * weights[i]
        pv = hourly_pv_kwh[i]
        actual = float(pv) if pv is not None and float(pv) > 0 else 0.0
        diff = predicted - actual
        if diff > 0:
            total += diff
    return total


async def lost_solar_kwh_one_kyiv_day(
    session: AsyncSession,
    device_sn: str,
    trade_day: date,
    *,
    lat: Optional[float],
    lon: Optional[float],
) -> Optional[float]:
    sn = (device_sn or "").strip()
    if not sn:
        return None
    hourly_soc, _grid, _freq, hourly_pv_kwh, _load = await hourly_inverter_history_for_kyiv_day(
        session, sn, trade_day
    )
    if lat is not None and lon is not None:
        weights = kyiv_day_hourly_clear_sky_weights(float(lat), float(lon), trade_day)
    else:
        weights = _synthetic_midday_clear_sky_weights_24()
    return _lost_solar_kwh_from_hourly(hourly_soc, hourly_pv_kwh, weights)


async def sum_lost_solar_last_n_kyiv_days(
    session: AsyncSession,
    device_sn: str,
    *,
    n_days: int = 7,
    lat: Optional[float],
    lon: Optional[float],
    end_day: Optional[date] = None,
) -> Optional[float]:
    """
    Sum lost-solar kWh over ``n_days`` Kyiv calendar days ending at ``end_day`` (default: Kyiv today).

    Returns ``None`` if no day returned a computable value; otherwise the sum (may be ``0.0``).
    """
    end = end_day or datetime.now(KYIV).date()
    total = 0.0
    any_computed = False
    n = max(1, min(31, int(n_days)))
    for k in range(n):
        d = end - timedelta(days=k)
        v = await lost_solar_kwh_one_kyiv_day(session, device_sn, d, lat=lat, lon=lon)
        if v is not None:
            any_computed = True
            total += float(v)
    return total if any_computed else None
