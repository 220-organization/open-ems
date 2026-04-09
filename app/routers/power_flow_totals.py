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
from app.models import DeyeManualDischargeSession, DeyePeakAutoDischargeFired, OreeDamPrice
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
    Approximate export to grid (kWh) from 5‑min ``deye_soc_sample`` rows where ``grid_power_w < 0``.

    Plain SUM over samples only — **not** derived from peak-DAM or manual-discharge session tables.
    When ``device_sn`` is set, only rows for that inverter serial are summed; otherwise fleet-wide sum.
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


async def _sum_arbitrage_revenue_uah(
    session: AsyncSession,
    device_sn: Optional[str] = None,
    *,
    kyiv_day_ge: Optional[date] = None,
    kyiv_day_le: Optional[date] = None,
) -> float:
    """
    Arbitrage-style revenue (UAH) from grid samples × DAM hourly UAH/kWh (same zone as tariff compare).

    Per 5‑min row: import kWh (grid_power_w > 0) and export kWh (grid_power_w < 0) use the same
    bucket formula as total export (|W| / 12000). Each row is mapped to Kyiv calendar day and hour;
    DAM period 1–24 matches hour 0–23 (period = hour + 1). Sum over all rows:

        Σ (charge_kwh * dam_uah_kwh − discharge_kwh * dam_uah_kwh)

    Rows without a matching ``oree_dam_price`` for that Kyiv (day, hour) are omitted.
    Optional ``kyiv_day_ge`` / ``kyiv_day_le`` restrict by Kyiv calendar date (inclusive).
    """
    zone = settings.OREE_COMPARE_ZONE_EIC
    sn = (device_sn or "").strip()
    date_pred = ""
    params: dict[str, Any] = {"zone": zone}
    if kyiv_day_ge is not None:
        date_pred += " AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) >= :kyiv_d0"
        params["kyiv_d0"] = kyiv_day_ge
    if kyiv_day_le is not None:
        date_pred += " AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) <= :kyiv_d1"
        params["kyiv_d1"] = kyiv_day_le
    base_from = f"""
        FROM deye_soc_sample s
        INNER JOIN oree_dam_price p ON p.trade_day = ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date)
            AND p.zone_eic = :zone
            AND p.period = (EXTRACT(HOUR FROM (s.bucket_start AT TIME ZONE 'Europe/Kiev'))::int + 1)
        WHERE s.grid_power_w IS NOT NULL
          AND s.grid_power_w <> 0
          {date_pred}
    """
    if sn:
        sql = (
            """
            SELECT COALESCE(SUM(
                (
                    CASE WHEN s.grid_power_w > 0 THEN s.grid_power_w::double precision / 12000.0 ELSE 0 END
                    - CASE WHEN s.grid_power_w < 0 THEN ABS(s.grid_power_w)::double precision / 12000.0 ELSE 0 END
                ) * (p.price_uah_mwh / 1000.0)
            ), 0)::double precision
            """
            + base_from
            + " AND s.device_sn = :sn"
        )
        params["sn"] = sn
        r = await session.execute(text(sql), params)
    else:
        sql = (
            """
            SELECT COALESCE(SUM(
                (
                    CASE WHEN s.grid_power_w > 0 THEN s.grid_power_w::double precision / 12000.0 ELSE 0 END
                    - CASE WHEN s.grid_power_w < 0 THEN ABS(s.grid_power_w)::double precision / 12000.0 ELSE 0 END
                ) * (p.price_uah_mwh / 1000.0)
            ), 0)::double precision
            """
            + base_from
        )
        r = await session.execute(text(sql), params)
    v = r.scalar_one()
    return float(v or 0.0)


async def _arbitrage_kyiv_month_mom_fields(
    session: AsyncSession, device_sn: Optional[str]
) -> tuple[Optional[float], int, int]:
    """
    Month-over-month % for arbitrage: Kyiv current month MTD vs the same number of calendar days
    in the previous Kyiv month (day 1 .. min(today, prev_month_last)).
    Returns (pct_change, kyiv_year, kyiv_month) for the current month label; pct is None if undefined.
    """
    today = _kyiv_today()
    month_first = _month_first(today)
    mtd_days = (today - month_first).days + 1
    prev_start, prev_end = _prev_calendar_month(today)
    comp_end = prev_start + timedelta(days=mtd_days - 1)
    if comp_end > prev_end:
        comp_end = prev_end
    curr = await _sum_arbitrage_revenue_uah(
        session, device_sn, kyiv_day_ge=month_first, kyiv_day_le=today
    )
    prev_slice = await _sum_arbitrage_revenue_uah(
        session, device_sn, kyiv_day_ge=prev_start, kyiv_day_le=comp_end
    )
    pct: Optional[float] = None
    if prev_slice > 1e-9:
        pct = (curr - prev_slice) / prev_slice * 100.0
    return pct, today.year, today.month


async def _latest_peak_dam_session_for_device(
    session: AsyncSession, device_sn: str
) -> dict[str, Any]:
    """Most recent successful peak-DAM auto row with computed session export kWh (if present)."""
    sn = (device_sn or "").strip()
    if not sn:
        return {}
    r = await session.execute(
        select(DeyePeakAutoDischargeFired)
        .where(DeyePeakAutoDischargeFired.device_sn == sn)
        .order_by(DeyePeakAutoDischargeFired.success_at.desc())
        .limit(1)
    )
    row = r.scalar_one_or_none()
    if row is None or row.export_session_kwh is None:
        return {}
    out: dict[str, Any] = {
        "exportSessionKwh": float(row.export_session_kwh),
        "hitTarget": row.peak_discharge_hit_target,
        "tradeDay": row.trade_day.isoformat(),
        "peakHour": int(row.peak_hour),
    }
    if row.export_session_start_at is not None:
        out["sessionStartAt"] = row.export_session_start_at.isoformat()
    if row.export_session_end_at is not None:
        out["sessionEndAt"] = row.export_session_end_at.isoformat()
    return out


async def _latest_manual_discharge_session_for_device(
    session: AsyncSession, device_sn: str
) -> dict[str, Any]:
    """Most recent manual discharge row with computed session export kWh (if present)."""
    sn = (device_sn or "").strip()
    if not sn:
        return {}
    r = await session.execute(
        select(DeyeManualDischargeSession)
        .where(DeyeManualDischargeSession.device_sn == sn)
        .order_by(DeyeManualDischargeSession.success_at.desc())
        .limit(1)
    )
    row = r.scalar_one_or_none()
    if row is None or row.export_session_kwh is None:
        return {}
    out: dict[str, Any] = {
        "exportSessionKwh": float(row.export_session_kwh),
        "hitTarget": row.discharge_hit_target,
    }
    if row.export_session_start_at is not None:
        out["sessionStartAt"] = row.export_session_start_at.isoformat()
    if row.export_session_end_at is not None:
        out["sessionEndAt"] = row.export_session_end_at.isoformat()
    return out


async def _fleet_latest_peak_export_kwh_sum(session: AsyncSession) -> float:
    """
    Sum of ``export_session_kwh`` from each inverter's most recent peak-DAM fired row
    (``DISTINCT ON (device_sn) … ORDER BY success_at DESC``). Missing/null rows contribute 0.
    """
    r = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(x.export_session_kwh), 0)::double precision
            FROM (
                SELECT DISTINCT ON (device_sn) export_session_kwh
                FROM deye_peak_auto_discharge_fired
                WHERE export_session_kwh IS NOT NULL
                ORDER BY device_sn, success_at DESC
            ) AS x
            """
        )
    )
    v = r.scalar_one()
    return float(v or 0.0)


async def _fleet_latest_manual_export_kwh_sum(session: AsyncSession) -> float:
    """Same pattern as peak, over ``deye_manual_discharge_session``."""
    r = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(x.export_session_kwh), 0)::double precision
            FROM (
                SELECT DISTINCT ON (device_sn) export_session_kwh
                FROM deye_manual_discharge_session
                WHERE export_session_kwh IS NOT NULL
                ORDER BY device_sn, success_at DESC
            ) AS x
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
    ``totalExportKwh`` is the plain sum of grid export energy from 5‑min ``deye_soc_sample`` rows (all inverters,
    or one device when ``deviceSn`` is set). It does **not** use peak-DAM or manual-discharge session aggregates.
    Also DAM average UAH/kWh for Kyiv current month MTD vs previous full calendar month (OREE_COMPARE_ZONE_EIC).
    ``arbitrageRevenueUah`` uses the same DAM hourly prices joined on Kyiv day/hour per sample.
    ``arbitrageKyivMonthMomPct`` compares current Kyiv month MTD arbitrage to the same calendar-day span
    in the previous Kyiv month (``arbitrageKyivMonthMomYear`` / ``arbitrageKyivMonthMomMonth`` label the month).
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

    try:
        payload["arbitrageRevenueUah"] = await _sum_arbitrage_revenue_uah(db, device_sn)
    except Exception as exc:
        logger.exception("landing-totals arbitrage sum: %s", exc)
        payload["arbitrageRevenueUah"] = None
        payload["arbitrageError"] = "arbitrage_sum_failed"

    try:
        mom_pct, mom_y, mom_m = await _arbitrage_kyiv_month_mom_fields(db, device_sn)
        payload["arbitrageKyivMonthMomPct"] = mom_pct
        payload["arbitrageKyivMonthMomYear"] = mom_y
        payload["arbitrageKyivMonthMomMonth"] = mom_m
    except Exception as exc:
        logger.exception("landing-totals arbitrage MoM: %s", exc)
        payload["arbitrageKyivMonthMomPct"] = None
        payload["arbitrageKyivMonthMomYear"] = None
        payload["arbitrageKyivMonthMomMonth"] = None

    if device_sn:
        try:
            peak_last = await _latest_peak_dam_session_for_device(db, device_sn)
            if peak_last:
                payload["peakDamLastSession"] = peak_last
        except Exception as exc:
            logger.exception("landing-totals peak DAM session: %s", exc)
        try:
            manual_last = await _latest_manual_discharge_session_for_device(db, device_sn)
            if manual_last:
                payload["manualDischargeLastSession"] = manual_last
        except Exception as exc:
            logger.exception("landing-totals manual discharge session: %s", exc)
    else:
        try:
            peak_sum = await _fleet_latest_peak_export_kwh_sum(db)
            payload["peakDamLastSession"] = {
                "exportSessionKwh": peak_sum,
                "fleetAggregate": True,
            }
        except Exception as exc:
            logger.exception("landing-totals fleet peak DAM sum: %s", exc)
        try:
            manual_sum = await _fleet_latest_manual_export_kwh_sum(db)
            payload["manualDischargeLastSession"] = {
                "exportSessionKwh": manual_sum,
                "fleetAggregate": True,
            }
        except Exception as exc:
            logger.exception("landing-totals fleet manual discharge sum: %s", exc)

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
