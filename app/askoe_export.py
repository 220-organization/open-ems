"""Paid ASKOE download: hourly consumption for the selected Kyiv period."""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.askoe_xlsx import build_askoe_xlsx
from app.deye_api import (
    fetch_device_day_frames,
    fetch_device_day_totals,
    station_cluster_device_sns,
)
from app.deye_energy_backfill_service import (
    hourly_kwh_from_frames,
    period_dates_kyiv,
    scale_to_day_totals,
)
from app.deye_soc_service import hourly_inverter_history_for_kyiv_day_cluster

ASKOE_PAYMENT_DESCRIPTION = "Open EMS · АСКОЕ споживання"


def _merge_hour(total: list[float], seen: list[bool], hours: list[Optional[float]]) -> None:
    for index, value in enumerate(hours[:24]):
        if value is None:
            continue
        total[index] += float(value)
        seen[index] = True


async def _cloud_consumption_hours(device_sn: str, day: date) -> list[Optional[float]]:
    """Hourly load kWh scaled so the day matches the Deye Cloud counter."""
    iso = day.isoformat()
    frames = await fetch_device_day_frames(device_sn, iso)
    totals = await fetch_device_day_totals(device_sn, iso)
    hourly = scale_to_day_totals(hourly_kwh_from_frames(frames), totals)
    return list(hourly["consumptionKwh"])


async def consumption_hours_kwh(
    session: AsyncSession,
    device_sn: str,
    days: list[date],
) -> list[list[Optional[float]]]:
    """24 Kyiv hours of load kWh per day.

    Prefer Deye Cloud daily counters (the energy card's Deye Cloud row), shaped by
    that day's power frames. If Cloud has no consumption, fall back to the Open EMS
    hourly series the card uses for the database row.
    """
    cluster = await station_cluster_device_sns(device_sn)
    sns = cluster or [device_sn]
    out: list[list[Optional[float]]] = []
    for day in days:
        total = [0.0] * 24
        seen = [False] * 24
        for sn in sns:
            try:
                hours = await _cloud_consumption_hours(sn, day)
            except Exception:
                hours = []
            _merge_hour(total, seen, hours)
        if not any(seen):
            history = await hourly_inverter_history_for_kyiv_day_cluster(session, sns, day)
            _merge_hour(total, seen, list(history[4]))
        out.append([total[index] if seen[index] else None for index in range(24)])
    return out


async def build_askoe_for_period(
    session: AsyncSession,
    device_sn: str,
    period: str,
    anchor: date,
) -> tuple[bytes, str, list[date]]:
    days = period_dates_kyiv(period, anchor)
    if not days:
        raise ValueError("no_days_in_period")
    hours = await consumption_hours_kwh(session, device_sn, days)
    blob = build_askoe_xlsx(
        serial=device_sn,
        days=days,
        hourly_kwh=hours,
        location="Deye",
        point=device_sn,
    )
    filename = f"askoe-{device_sn}-{days[0].isoformat()}-to-{days[-1].isoformat()}.xlsx"
    return blob, filename, days
