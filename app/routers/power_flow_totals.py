"""Power-flow totals: fleet or per-device grid export (kWh) + DAM month tariff comparison."""

from __future__ import annotations

import logging
import math
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


async def _peak_dam_cumulative_export_kwh_for_device(
    session: AsyncSession, device_sn: str
) -> dict[str, Any]:
    """
    Sum ``export_session_kwh`` over all peak-DAM auto-discharge rows for this inverter (all time).
    JSON key remains ``peakDamLastSession`` / ``exportSessionKwh`` for API compatibility.
    """
    sn = (device_sn or "").strip()
    if not sn:
        return {}
    r = await session.execute(
        select(func.coalesce(func.sum(DeyePeakAutoDischargeFired.export_session_kwh), 0.0)).where(
            DeyePeakAutoDischargeFired.device_sn == sn,
            DeyePeakAutoDischargeFired.export_session_kwh.isnot(None),
        )
    )
    total = float(r.scalar_one() or 0.0)
    return {
        "exportSessionKwh": total,
        "allTimePeakExportTotal": True,
    }


async def _manual_discharge_cumulative_export_kwh_for_device(
    session: AsyncSession, device_sn: str
) -> dict[str, Any]:
    """
    Sum ``export_session_kwh`` over all manual discharge rows for this inverter (all time).
    JSON key remains ``manualDischargeLastSession`` / ``exportSessionKwh`` for API compatibility.
    """
    sn = (device_sn or "").strip()
    if not sn:
        return {}
    r = await session.execute(
        select(func.coalesce(func.sum(DeyeManualDischargeSession.export_session_kwh), 0.0)).where(
            DeyeManualDischargeSession.device_sn == sn,
            DeyeManualDischargeSession.export_session_kwh.isnot(None),
        )
    )
    total = float(r.scalar_one() or 0.0)
    return {
        "exportSessionKwh": total,
        "allTimeManualExportTotal": True,
    }


async def _fleet_sum_all_peak_dam_export_kwh(session: AsyncSession) -> float:
    """Sum ``export_session_kwh`` over every peak-DAM fired row (all inverters, all time)."""
    r = await session.execute(
        select(func.coalesce(func.sum(DeyePeakAutoDischargeFired.export_session_kwh), 0.0)).where(
            DeyePeakAutoDischargeFired.export_session_kwh.isnot(None),
        )
    )
    return float(r.scalar_one() or 0.0)


async def _fleet_sum_all_manual_discharge_export_kwh(session: AsyncSession) -> float:
    """Sum ``export_session_kwh`` over every manual discharge row (all inverters, all time)."""
    r = await session.execute(
        select(func.coalesce(func.sum(DeyeManualDischargeSession.export_session_kwh), 0.0)).where(
            DeyeManualDischargeSession.export_session_kwh.isnot(None),
        )
    )
    return float(r.scalar_one() or 0.0)


def _clamp_session_cumulative_to_total_export(payload: dict[str, Any]) -> None:
    """
    Peak / manual cumulative kWh come from session tables; total export is the plain sample sum.
    Session aggregates can drift from samples after partial deletes or bad seeds — never show
    session totals above total grid export (subset invariant).
    """
    total = payload.get("totalExportKwh")
    if total is None:
        return
    try:
        t = float(total)
    except (TypeError, ValueError):
        return
    if not math.isfinite(t) or t < 0:
        return

    for key in ("peakDamLastSession", "manualDischargeLastSession"):
        block = payload.get(key)
        if not isinstance(block, dict):
            continue
        raw = block.get("exportSessionKwh")
        if not isinstance(raw, (int, float)):
            continue
        p = float(raw)
        if not math.isfinite(p) or p < 0:
            continue
        if p > t:
            block["exportSessionKwh"] = t


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

    ``peakDamLastSession`` (name kept for compatibility) carries **cumulative** peak auto-discharge export kWh:
    sum of every ``export_session_kwh`` in ``deye_peak_auto_discharge_fired`` for the device, or fleet-wide sum
    of all such rows when ``deviceSn`` is omitted. Values are **capped** at ``totalExportKwh`` when session sums
    exceed the plain sample total (inconsistent DB / seeds).

    ``manualDischargeLastSession`` (name kept for compatibility) is **cumulative** manual UI/API discharge export kWh:
    sum of every ``export_session_kwh`` in ``deye_manual_discharge_session``, same device vs fleet-wide pattern.
    Also capped at ``totalExportKwh`` when above the sample total.
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
            peak_cum = await _peak_dam_cumulative_export_kwh_for_device(db, device_sn)
            if peak_cum:
                payload["peakDamLastSession"] = peak_cum
        except Exception as exc:
            logger.exception("landing-totals peak DAM cumulative kWh: %s", exc)
        try:
            manual_cum = await _manual_discharge_cumulative_export_kwh_for_device(db, device_sn)
            if manual_cum:
                payload["manualDischargeLastSession"] = manual_cum
        except Exception as exc:
            logger.exception("landing-totals manual discharge cumulative kWh: %s", exc)
    else:
        try:
            peak_sum = await _fleet_sum_all_peak_dam_export_kwh(db)
            payload["peakDamLastSession"] = {
                "exportSessionKwh": peak_sum,
                "fleetAggregate": True,
                "allTimePeakExportTotal": True,
            }
        except Exception as exc:
            logger.exception("landing-totals fleet peak DAM cumulative kWh: %s", exc)
        try:
            manual_sum = await _fleet_sum_all_manual_discharge_export_kwh(db)
            payload["manualDischargeLastSession"] = {
                "exportSessionKwh": manual_sum,
                "fleetAggregate": True,
                "allTimeManualExportTotal": True,
            }
        except Exception as exc:
            logger.exception("landing-totals fleet manual discharge cumulative kWh: %s", exc)

    _clamp_session_cumulative_to_total_export(payload)

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


async def _hourly_export_bars_kyiv(
    session: AsyncSession,
    *,
    device_sn: Optional[str],
    days: int,
    hourly_scope: str,
) -> dict[str, Any]:
    """
    Per Kyiv calendar hour: grid export kWh from 5‑min samples (|W|/12000 when grid_power_w < 0).

    ``hourly_scope``: ``total`` — all grid export; ``peak`` — only buckets inside peak-DAM auto session
    windows; ``manual`` — only buckets inside manual discharge session windows.
    DAM UAH/kWh joined on Kyiv day/hour.
    """
    today = _kyiv_today()
    d_end = today
    d_start = today - timedelta(days=max(1, days) - 1)
    zone = settings.OREE_COMPARE_ZONE_EIC
    sn = (device_sn or "").strip()
    use_device = bool(sn)

    if hourly_scope == "peak":
        sql = """
            WITH session_windows AS (
                SELECT
                    f.device_sn,
                    f.export_session_start_at,
                    f.export_session_end_at
                FROM deye_peak_auto_discharge_fired f
                WHERE f.export_session_start_at IS NOT NULL
                  AND f.export_session_end_at IS NOT NULL
                  AND (:use_device = false OR f.device_sn = :sn)
            ),
            hourly AS (
                SELECT
                    ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) AS kyiv_day,
                    (EXTRACT(HOUR FROM (s.bucket_start AT TIME ZONE 'Europe/Kiev'))::int) AS kyiv_hour,
                    SUM(
                        CASE WHEN s.grid_power_w < 0
                        THEN ABS(s.grid_power_w)::double precision / 12000.0
                        ELSE 0 END
                    ) AS export_kwh
                FROM deye_soc_sample s
                INNER JOIN session_windows w
                    ON s.device_sn = w.device_sn
                   AND s.bucket_start >= w.export_session_start_at
                   AND s.bucket_start <= w.export_session_end_at
                WHERE ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) >= :d_start
                  AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) <= :d_end
                  AND (:use_device = false OR s.device_sn = :sn)
                GROUP BY 1, 2
            )
            SELECT
                h.kyiv_day,
                h.kyiv_hour,
                h.export_kwh,
                (p.price_uah_mwh / 1000.0) AS dam_uah_per_kwh
            FROM hourly h
            LEFT JOIN oree_dam_price p ON p.trade_day = h.kyiv_day
                AND p.zone_eic = :zone
                AND p.period = h.kyiv_hour + 1
            WHERE h.export_kwh > 1e-9
            ORDER BY h.kyiv_day, h.kyiv_hour
        """
    elif hourly_scope == "manual":
        sql = """
            WITH session_windows AS (
                SELECT
                    m.device_sn,
                    m.export_session_start_at,
                    m.export_session_end_at
                FROM deye_manual_discharge_session m
                WHERE m.export_session_start_at IS NOT NULL
                  AND m.export_session_end_at IS NOT NULL
                  AND (:use_device = false OR m.device_sn = :sn)
            ),
            hourly AS (
                SELECT
                    ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) AS kyiv_day,
                    (EXTRACT(HOUR FROM (s.bucket_start AT TIME ZONE 'Europe/Kiev'))::int) AS kyiv_hour,
                    SUM(
                        CASE WHEN s.grid_power_w < 0
                        THEN ABS(s.grid_power_w)::double precision / 12000.0
                        ELSE 0 END
                    ) AS export_kwh
                FROM deye_soc_sample s
                INNER JOIN session_windows w
                    ON s.device_sn = w.device_sn
                   AND s.bucket_start >= w.export_session_start_at
                   AND s.bucket_start <= w.export_session_end_at
                WHERE ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) >= :d_start
                  AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) <= :d_end
                  AND (:use_device = false OR s.device_sn = :sn)
                GROUP BY 1, 2
            )
            SELECT
                h.kyiv_day,
                h.kyiv_hour,
                h.export_kwh,
                (p.price_uah_mwh / 1000.0) AS dam_uah_per_kwh
            FROM hourly h
            LEFT JOIN oree_dam_price p ON p.trade_day = h.kyiv_day
                AND p.zone_eic = :zone
                AND p.period = h.kyiv_hour + 1
            WHERE h.export_kwh > 1e-9
            ORDER BY h.kyiv_day, h.kyiv_hour
        """
    else:
        sql = """
            WITH hourly AS (
                SELECT
                    ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) AS kyiv_day,
                    (EXTRACT(HOUR FROM (s.bucket_start AT TIME ZONE 'Europe/Kiev'))::int) AS kyiv_hour,
                    SUM(
                        CASE WHEN s.grid_power_w < 0
                        THEN ABS(s.grid_power_w)::double precision / 12000.0
                        ELSE 0 END
                    ) AS export_kwh
                FROM deye_soc_sample s
                WHERE ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) >= :d_start
                  AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) <= :d_end
                  AND (:use_device = false OR s.device_sn = :sn)
                GROUP BY 1, 2
            )
            SELECT
                h.kyiv_day,
                h.kyiv_hour,
                h.export_kwh,
                (p.price_uah_mwh / 1000.0) AS dam_uah_per_kwh
            FROM hourly h
            LEFT JOIN oree_dam_price p ON p.trade_day = h.kyiv_day
                AND p.zone_eic = :zone
                AND p.period = h.kyiv_hour + 1
            WHERE h.export_kwh > 1e-9
            ORDER BY h.kyiv_day, h.kyiv_hour
        """
    r = await session.execute(
        text(sql),
        {
            "d_start": d_start,
            "d_end": d_end,
            "use_device": use_device,
            "sn": sn,
            "zone": zone,
        },
    )
    rows = r.mappings().all()
    bars: list[dict[str, Any]] = []
    for row in rows:
        kd = row["kyiv_day"]
        kh = int(row["kyiv_hour"])
        ek = float(row["export_kwh"] or 0.0)
        dam = row["dam_uah_per_kwh"]
        bars.append(
            {
                "dayIso": kd.isoformat() if hasattr(kd, "isoformat") else str(kd),
                "hour": kh,
                "exportKwh": ek,
                "damUahPerKwh": float(dam) if dam is not None else None,
            }
        )
    return {
        "exportScope": "device" if use_device else "fleet",
        **({"deviceSn": sn} if use_device else {}),
        "zoneEic": zone,
        "kyivDayStart": d_start.isoformat(),
        "kyivDayEnd": d_end.isoformat(),
        "days": max(1, days),
        "hourlyScope": hourly_scope,
        "bars": bars,
    }


@router.get("/export-hourly-bars")
async def export_hourly_bars(
    device_sn: Optional[str] = Query(
        default=None,
        alias="deviceSn",
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial — omit for fleet-wide hourly export.",
    ),
    days: int = Query(
        default=7,
        ge=1,
        le=120,
        description="Kyiv calendar days ending today (inclusive).",
    ),
    hourly_scope: str = Query(
        "total",
        alias="hourlyScope",
        pattern=r"^(total|peak|manual)$",
        description="total = all grid export; peak = peak-DAM auto session windows only; manual = manual discharge session windows only.",
    ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Hourly grid export (kWh) and DAM UAH/kWh for the last ``days`` Kyiv days: one bar per hour
    with export > 0. The UI charts revenue (kWh × DAM) per hour.

    ``hourlyScope`` selects which ``deye_soc_sample`` buckets to sum: all export, only peak-DAM
    auto-discharge sessions, or only manual discharge sessions.
    DAM UAH/kWh when present in ``oree_dam_price``.
    """
    try:
        payload = await _hourly_export_bars_kyiv(
            db,
            device_sn=device_sn,
            days=days,
            hourly_scope=hourly_scope,
        )
        payload["ok"] = True
        return JSONResponse(content=payload, headers=_NO_STORE)
    except Exception as exc:
        logger.exception("export-hourly-bars: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "export_hourly_bars_failed"},
            headers=_NO_STORE,
        )
