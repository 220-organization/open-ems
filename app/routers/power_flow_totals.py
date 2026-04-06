"""Power-flow totals: fleet or per-device grid export (kWh) + DAM month tariff comparison."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import OreeDamPrice
from app.oree_dam_service import KYIV, oree_dam_configured
from app import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/power-flow", tags=["power-flow"])

_NO_STORE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


def _kyiv_today() -> date:
    return datetime.now(KYIV).date()


def _month_first(d: date) -> date:
    return date(d.year, d.month, 1)


def _prev_calendar_month(ref: date) -> tuple[date, date]:
    first_this = _month_first(ref)
    last_prev = first_this - timedelta(days=1)
    first_prev = _month_first(last_prev)
    return first_prev, last_prev


async def _sum_export_kwh(session: AsyncSession, device_sn: Optional[str] = None) -> float:
    """
    Approximate export to grid (kWh) from 5‑min samples where grid_power_w < 0.
    When ``device_sn`` is set, only rows for that inverter serial are summed.
    """
    sn = (device_sn or "").strip()
    if sn:
        r = await session.execute(
            text(
                """
                SELECT COALESCE(SUM(
                    CASE WHEN grid_power_w < 0 THEN ABS(grid_power_w)::double precision / 12000.0
                    ELSE 0 END
                ), 0)::double precision
                FROM deye_soc_sample
                WHERE device_sn = :sn
                """
            ),
            {"sn": sn},
        )
    else:
        r = await session.execute(
            text(
                """
                SELECT COALESCE(SUM(
                    CASE WHEN grid_power_w < 0 THEN ABS(grid_power_w)::double precision / 12000.0
                    ELSE 0 END
                ), 0)::double precision
                FROM deye_soc_sample
                """
            )
        )
    v = r.scalar_one()
    return float(v or 0.0)


async def _avg_dam_uah_per_kwh(
    session: AsyncSession, zone: str, start: date, end: date
) -> Optional[float]:
    r = await session.execute(
        select(func.avg(OreeDamPrice.price_uah_mwh), func.count()).where(
            OreeDamPrice.zone_eic == zone,
            OreeDamPrice.trade_day >= start,
            OreeDamPrice.trade_day <= end,
        )
    )
    avg_mwh, cnt = r.one()
    if (cnt or 0) == 0 or avg_mwh is None:
        return None
    return float(avg_mwh) / 1000.0


@router.get("/landing-totals")
async def landing_totals(
    device_sn: Optional[str] = Query(
        default=None,
        alias="deviceSn",
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Optional Deye inverter serial — when set, totalExportKwh is for this device only.",
    ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Grid export (kWh) from 5‑min DB samples: all inverters, or one device when ``deviceSn`` is set.
    Also DAM average UAH/kWh for Kyiv current month MTD vs previous full calendar month (OREE_COMPARE_ZONE_EIC).
    """
    payload: dict[str, Any] = {"ok": True, "exportScope": "device" if device_sn else "fleet"}
    if device_sn:
        payload["deviceSn"] = device_sn.strip()
    try:
        payload["totalExportKwh"] = await _sum_export_kwh(db, device_sn)
    except Exception as exc:
        logger.exception("landing-totals export sum: %s", exc)
        payload["totalExportKwh"] = None
        payload["exportError"] = "export_sum_failed"

    today = _kyiv_today()
    zone = settings.OREE_COMPARE_ZONE_EIC
    dam: dict[str, Any] = {
        "configured": oree_dam_configured(),
        "zoneEic": zone,
        "currentMonthStart": None,
        "currentMonthEnd": None,
        "currentAvgUahPerKwh": None,
        "prevMonthStart": None,
        "prevMonthEnd": None,
        "prevAvgUahPerKwh": None,
        "pctChangeVsPrevMonth": None,
    }
    payload["dam"] = dam

    if not oree_dam_configured():
        return JSONResponse(content=payload, headers=_NO_STORE)

    first_mtd = _month_first(today)
    dam["currentMonthStart"] = first_mtd.isoformat()
    dam["currentMonthEnd"] = today.isoformat()
    prev_start, prev_end = _prev_calendar_month(today)
    dam["prevMonthStart"] = prev_start.isoformat()
    dam["prevMonthEnd"] = prev_end.isoformat()

    try:
        cur_avg = await _avg_dam_uah_per_kwh(db, zone, first_mtd, today)
        prev_avg = await _avg_dam_uah_per_kwh(db, zone, prev_start, prev_end)
        dam["currentAvgUahPerKwh"] = cur_avg
        dam["prevAvgUahPerKwh"] = prev_avg
        if cur_avg is not None and prev_avg is not None and prev_avg > 0:
            dam["pctChangeVsPrevMonth"] = (cur_avg - prev_avg) / prev_avg * 100.0
    except Exception as exc:
        logger.exception("landing-totals DAM averages: %s", exc)
        dam["detail"] = "dam_avg_failed"

    return JSONResponse(content=payload, headers=_NO_STORE)
