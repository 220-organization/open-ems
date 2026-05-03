"""Power-flow totals: fleet or per-device grid export (kWh) + DAM month tariff comparison."""

from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deye_api import get_inverter_station_coordinates
from app.lost_solar_deye import (
    lost_solar_hourly_breakdown_one_kyiv_day,
    sum_lost_solar_all_sample_kyiv_days,
)
from app.models import DeyeManualDischargeSession, DeyePeakAutoDischargeFired, OreeDamPrice
from app.nbu_fx_service import fetch_usd_uah_rate_for_date
from app.oree_dam_service import KYIV, oree_dam_configured
from app import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/power-flow", tags=["power-flow"])

_NO_STORE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}

_REFERENCE_LCOE_TTL_SEC = 6 * 3600
_reference_lcoe_mono = 0.0
_reference_lcoe_body: Optional[dict[str, Any]] = None


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


async def _sum_huawei_export_kwh(session: AsyncSession, station_code: str) -> float:
    """
    Grid export (kWh) from 5‑min ``huawei_power_sample`` rows where ``grid_power_w < 0``,
    same |W|/12000 energy per bucket as Deye samples.
    """
    st = (station_code or "").strip()
    if not st:
        return 0.0
    r = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(
                CASE WHEN grid_power_w < 0 THEN ABS(grid_power_w)::double precision / 12000.0
                ELSE 0 END
            ), 0)::double precision
            FROM huawei_power_sample
            WHERE station_code = :st
            """
        ),
        {"st": st},
    )
    return float(r.scalar_one() or 0.0)


async def _sum_arbitrage_revenue_uah(
    session: AsyncSession,
    device_sn: Optional[str] = None,
    *,
    kyiv_day_ge: Optional[date] = None,
    kyiv_day_le: Optional[date] = None,
) -> float:
    """
    Total arbitrage (UAH) = sum over Kyiv calendar days of each day's net DAM cash from the grid.

    For every Kyiv (day, hour), aggregate import and export kWh from 5‑min ``deye_soc_sample`` rows
    (same W/12000 formula as elsewhere). Join OREE DAM for that Kyiv trade day and period (hour + 1).
    Per hour (same as the DAM chart «arbitrage for this day»)::

        + hourly_export_kWh × DAM_UAH_per_kWh  −  hourly_import_kWh × DAM_UAH_per_kWh

    Hours without a DAM price row are omitted. The grand total is ``Σ hour_uah``, which equals
    **Σ_daily (sum of hour_uah in that day)** — i.e. the sum of the same per‑day figure shown in the
    Power Flow DAM chart («DAM export value minus DAM import cost»), extended over all samples in range.

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
    device_pred = " AND s.device_sn = :sn" if sn else ""
    if sn:
        params["sn"] = sn

    sql = (
        """
        WITH hourly AS (
            SELECT
                ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) AS kyiv_day,
                (EXTRACT(HOUR FROM (s.bucket_start AT TIME ZONE 'Europe/Kiev'))::int) AS kyiv_hour,
                SUM(
                    CASE WHEN s.grid_power_w > 0 THEN s.grid_power_w::double precision / 12000.0 ELSE 0 END
                ) AS import_kwh,
                SUM(
                    CASE WHEN s.grid_power_w < 0 THEN ABS(s.grid_power_w)::double precision / 12000.0 ELSE 0 END
                ) AS export_kwh
            FROM deye_soc_sample s
            WHERE s.grid_power_w IS NOT NULL
              AND s.grid_power_w <> 0
        """
        + date_pred
        + device_pred
        + """
            GROUP BY 1, 2
        ),
        hour_net AS (
            SELECT
                h.kyiv_day,
                (h.export_kwh * (p.price_uah_mwh / 1000.0))
                - (h.import_kwh * (p.price_uah_mwh / 1000.0)) AS hour_uah
            FROM hourly h
            INNER JOIN oree_dam_price p ON p.trade_day = h.kyiv_day
                AND p.zone_eic = :zone
                AND p.period = h.kyiv_hour + 1
            WHERE h.import_kwh > 1e-18 OR h.export_kwh > 1e-18
        )
        SELECT COALESCE(SUM(hour_uah), 0)::double precision
        FROM hour_net
        """
    )
    r = await session.execute(text(sql), params)
    v = r.scalar_one()
    return float(v or 0.0)


async def _sum_arbitrage_revenue_uah_huawei(
    session: AsyncSession,
    station_code: str,
    *,
    kyiv_day_ge: Optional[date] = None,
    kyiv_day_le: Optional[date] = None,
) -> float:
    """
    Same hourly DAM net as ``_sum_arbitrage_revenue_uah``, but import/export from ``huawei_power_sample``.
    """
    zone = settings.OREE_COMPARE_ZONE_EIC
    st = (station_code or "").strip()
    if not st:
        return 0.0
    date_pred = ""
    params: dict[str, Any] = {"zone": zone, "st": st}
    if kyiv_day_ge is not None:
        date_pred += " AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) >= :kyiv_d0"
        params["kyiv_d0"] = kyiv_day_ge
    if kyiv_day_le is not None:
        date_pred += " AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) <= :kyiv_d1"
        params["kyiv_d1"] = kyiv_day_le

    sql = (
        """
        WITH hourly AS (
            SELECT
                ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) AS kyiv_day,
                (EXTRACT(HOUR FROM (s.bucket_start AT TIME ZONE 'Europe/Kiev'))::int) AS kyiv_hour,
                SUM(
                    CASE WHEN s.grid_power_w > 0 THEN s.grid_power_w::double precision / 12000.0 ELSE 0 END
                ) AS import_kwh,
                SUM(
                    CASE WHEN s.grid_power_w < 0 THEN ABS(s.grid_power_w)::double precision / 12000.0 ELSE 0 END
                ) AS export_kwh
            FROM huawei_power_sample s
            WHERE s.station_code = :st
              AND s.grid_power_w IS NOT NULL
              AND s.grid_power_w <> 0
        """
        + date_pred
        + """
            GROUP BY 1, 2
        ),
        hour_net AS (
            SELECT
                h.kyiv_day,
                (h.export_kwh * (p.price_uah_mwh / 1000.0))
                - (h.import_kwh * (p.price_uah_mwh / 1000.0)) AS hour_uah
            FROM hourly h
            INNER JOIN oree_dam_price p ON p.trade_day = h.kyiv_day
                AND p.zone_eic = :zone
                AND p.period = h.kyiv_hour + 1
            WHERE h.import_kwh > 1e-18 OR h.export_kwh > 1e-18
        )
        SELECT COALESCE(SUM(hour_uah), 0)::double precision
        FROM hour_net
        """
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


async def _arbitrage_kyiv_month_mom_fields_huawei(
    session: AsyncSession, station_code: str
) -> tuple[Optional[float], int, int]:
    today = _kyiv_today()
    month_first = _month_first(today)
    mtd_days = (today - month_first).days + 1
    prev_start, prev_end = _prev_calendar_month(today)
    comp_end = prev_start + timedelta(days=mtd_days - 1)
    if comp_end > prev_end:
        comp_end = prev_end
    curr = await _sum_arbitrage_revenue_uah_huawei(
        session, station_code, kyiv_day_ge=month_first, kyiv_day_le=today
    )
    prev_slice = await _sum_arbitrage_revenue_uah_huawei(
        session, station_code, kyiv_day_ge=prev_start, kyiv_day_le=comp_end
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


async def _device_import_weighted_dam_mtd_kyiv(
    session: AsyncSession, device_sn: str
) -> tuple[float, Optional[float]]:
    """
    Kyiv calendar month-to-date: grid import kWh from 5‑min samples (grid_power_w > 0, W/12000)
    joined to OREE DAM UAH/kWh for that sample's Kyiv day and hour.

    Returns (import_kwh_matched, weighted_avg_dam_uah_per_kwh). Averages only buckets with a DAM row
    (INNER JOIN). Weighted avg is None when import_kwh_matched is negligible.
    """
    sn = (device_sn or "").strip()
    if not sn:
        return 0.0, None
    today = _kyiv_today()
    first_mtd = _month_first(today)
    zone = settings.OREE_COMPARE_ZONE_EIC
    sql = """
        SELECT
            COALESCE(SUM(
                CASE WHEN s.grid_power_w > 0 THEN s.grid_power_w::double precision / 12000.0 ELSE 0 END
            ), 0)::double precision AS import_kwh,
            COALESCE(SUM(
                (CASE WHEN s.grid_power_w > 0 THEN s.grid_power_w::double precision / 12000.0 ELSE 0 END)
                * (p.price_uah_mwh / 1000.0)
            ), 0)::double precision AS cost_uah
        FROM deye_soc_sample s
        INNER JOIN oree_dam_price p ON p.trade_day = ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date)
            AND p.zone_eic = :zone
            AND p.period = (EXTRACT(HOUR FROM (s.bucket_start AT TIME ZONE 'Europe/Kiev'))::int + 1)
        WHERE s.device_sn = :sn
          AND s.grid_power_w IS NOT NULL
          AND s.grid_power_w > 0
          AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) >= :d0
          AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) <= :d1
    """
    r = await session.execute(text(sql), {"sn": sn, "zone": zone, "d0": first_mtd, "d1": today})
    row = r.one()
    import_kwh = float(row[0] or 0.0)
    cost_uah = float(row[1] or 0.0)
    if import_kwh <= 1e-12:
        return import_kwh, None
    return import_kwh, cost_uah / import_kwh


async def _huawei_station_import_weighted_dam_mtd_kyiv(
    session: AsyncSession, station_code: str
) -> tuple[float, Optional[float]]:
    """
    Same semantics as ``_device_import_weighted_dam_mtd_kyiv`` for Deye, but using ``huawei_power_sample``
    for one FusionSolar plant (``station_code``). Grid import: ``grid_power_w > 0`` (W/12000 per bucket).
    """
    st = (station_code or "").strip()
    if not st:
        return 0.0, None
    today = _kyiv_today()
    first_mtd = _month_first(today)
    zone = settings.OREE_COMPARE_ZONE_EIC
    sql = """
        SELECT
            COALESCE(SUM(
                CASE WHEN s.grid_power_w > 0 THEN s.grid_power_w::double precision / 12000.0 ELSE 0 END
            ), 0)::double precision AS import_kwh,
            COALESCE(SUM(
                (CASE WHEN s.grid_power_w > 0 THEN s.grid_power_w::double precision / 12000.0 ELSE 0 END)
                * (p.price_uah_mwh / 1000.0)
            ), 0)::double precision AS cost_uah
        FROM huawei_power_sample s
        INNER JOIN oree_dam_price p ON p.trade_day = ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date)
            AND p.zone_eic = :zone
            AND p.period = (EXTRACT(HOUR FROM (s.bucket_start AT TIME ZONE 'Europe/Kiev'))::int + 1)
        WHERE s.station_code = :st
          AND s.grid_power_w IS NOT NULL
          AND s.grid_power_w > 0
          AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) >= :d0
          AND ((s.bucket_start AT TIME ZONE 'Europe/Kiev')::date) <= :d1
    """
    r = await session.execute(text(sql), {"st": st, "zone": zone, "d0": first_mtd, "d1": today})
    row = r.one()
    import_kwh = float(row[0] or 0.0)
    cost_uah = float(row[1] or 0.0)
    if import_kwh <= 1e-12:
        return import_kwh, None
    return import_kwh, cost_uah / import_kwh


async def _finalize_landing_response(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    deye_device_sn_for_import_mtd: Optional[str] = None,
    huawei_station_code_for_import_mtd: Optional[str] = None,
) -> JSONResponse:
    """Attach Kyiv DAM month comparison and optional per-device import-weighted DAM MTD (Deye or Huawei)."""
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
        cur_avg = await _avg_dam_uah_per_kwh(session, zone, first_mtd, today)
        prev_avg = await _avg_dam_uah_per_kwh(session, zone, prev_start, prev_end)
        dam["currentAvgUahPerKwh"] = cur_avg
        dam["prevAvgUahPerKwh"] = prev_avg
        if cur_avg is not None and prev_avg is not None and prev_avg > 0:
            dam["pctChangeVsPrevMonth"] = (cur_avg - prev_avg) / prev_avg * 100.0
    except Exception as exc:
        logger.exception("landing-totals DAM averages: %s", exc)
        dam["detail"] = "dam_avg_failed"

    sn_imp = (deye_device_sn_for_import_mtd or "").strip()
    hw_imp = (huawei_station_code_for_import_mtd or "").strip()
    if oree_dam_configured():
        if sn_imp:
            try:
                imp_kwh, wavg = await _device_import_weighted_dam_mtd_kyiv(session, sn_imp)
                dam["currentMonthDeviceGridImportKwhMtd"] = imp_kwh
                dam["currentMonthDeviceImportWeightedAvgDamUahPerKwhMtd"] = wavg
            except Exception as exc:
                logger.exception("landing-totals device import weighted DAM: %s", exc)
                dam["currentMonthDeviceGridImportKwhMtd"] = None
                dam["currentMonthDeviceImportWeightedAvgDamUahPerKwhMtd"] = None
                dam["deviceImportDamDetail"] = "device_import_dam_failed"
        elif hw_imp:
            try:
                imp_kwh, wavg = await _huawei_station_import_weighted_dam_mtd_kyiv(session, hw_imp)
                dam["currentMonthDeviceGridImportKwhMtd"] = imp_kwh
                dam["currentMonthDeviceImportWeightedAvgDamUahPerKwhMtd"] = wavg
            except Exception as exc:
                logger.exception("landing-totals Huawei station import weighted DAM: %s", exc)
                dam["currentMonthDeviceGridImportKwhMtd"] = None
                dam["currentMonthDeviceImportWeightedAvgDamUahPerKwhMtd"] = None
                dam["deviceImportDamDetail"] = "huawei_station_import_dam_failed"

    return JSONResponse(content=payload, headers=_NO_STORE)


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
    huawei_station_code: Optional[str] = Query(
        default=None,
        alias="huaweiStationCode",
        min_length=1,
        max_length=64,
        pattern=r"^[\w\-.=]+$",
        description="Optional Huawei FusionSolar plant code — when set, totals use huawei_power_sample only.",
    ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    ``totalExportKwh`` is the plain sum of grid export energy from 5‑min ``deye_soc_sample`` rows (all inverters,
    or one device when ``deviceSn`` is set). It does **not** use peak-DAM or manual-discharge session aggregates.
    Also DAM average UAH/kWh for Kyiv current month MTD vs previous full calendar month (OREE_COMPARE_ZONE_EIC).
    When ``deviceSn`` is set, ``dam.currentMonthDeviceImportWeightedAvgDamUahPerKwhMtd`` is the volume-weighted
    OREE DAM UAH/kWh over **grid import** 5‑min samples (``grid_power_w > 0``) for Kyiv MTD, joined to hourly DAM
    (same join as arbitrage). ``dam.currentMonthDeviceGridImportKwhMtd`` is the matched import kWh sum.
    ``arbitrageRevenueUah`` is the sum over Kyiv days of per‑day net (export − import) × DAM UAH/kWh on
    hourly buckets from ``deye_soc_sample``, matching the DAM chart «arbitrage for this day» summed across days.
    ``arbitrageKyivMonthMomPct`` compares current Kyiv month MTD arbitrage to the same calendar-day span
    in the previous Kyiv month (``arbitrageKyivMonthMomYear`` / ``arbitrageKyivMonthMomMonth`` label the month).

    ``peakDamLastSession`` (name kept for compatibility) carries **cumulative** peak auto-discharge export kWh:
    sum of every ``export_session_kwh`` in ``deye_peak_auto_discharge_fired`` for the device, or fleet-wide sum
    of all such rows when ``deviceSn`` is omitted. Values are **capped** at ``totalExportKwh`` when session sums
    exceed the plain sample total (inconsistent DB / seeds).

    ``manualDischargeLastSession`` (name kept for compatibility) is **cumulative** manual UI/API discharge export kWh:
    sum of every ``export_session_kwh`` in ``deye_manual_discharge_session``, same device vs fleet-wide pattern.
    Also capped at ``totalExportKwh`` when above the sample total.

    When ``deviceSn`` is set, ``lostSolarKwhTotal`` is the sum of per-day clipped-PV estimates (same model as the
    DAM chart) over every Kyiv calendar day that has ``deye_soc_sample`` rows for that device. Missing or failed
    aggregate yields ``0.0``.

    When ``huaweiStationCode`` is set, ``totalExportKwh`` and arbitrage come from ``huawei_power_sample`` for that
    plant; peak/manual session fields are omitted. ``dam.currentMonthDeviceImportWeightedAvgDamUahPerKwhMtd`` uses
    the same import-weighted hourly DAM join over ``huawei_power_sample`` (``grid_power_w > 0``) Kyiv MTD as for
    Deye. ``deviceSn`` must not be sent together with ``huaweiStationCode``.
    """
    hw = (huawei_station_code or "").strip()
    sn_req = (device_sn or "").strip()
    if hw and sn_req:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "landing_totals_device_sn_and_huawei_mutually_exclusive"},
            headers=_NO_STORE,
        )

    if hw:
        payload: dict[str, Any] = {"ok": True, "exportScope": "huawei", "huaweiStationCode": hw}
        try:
            payload["totalExportKwh"] = await _sum_huawei_export_kwh(db, hw)
        except Exception as exc:
            logger.exception("landing-totals Huawei export sum: %s", exc)
            payload["totalExportKwh"] = None
            payload["exportError"] = "export_sum_failed"
        try:
            payload["arbitrageRevenueUah"] = await _sum_arbitrage_revenue_uah_huawei(db, hw)
        except Exception as exc:
            logger.exception("landing-totals Huawei arbitrage sum: %s", exc)
            payload["arbitrageRevenueUah"] = None
            payload["arbitrageError"] = "arbitrage_sum_failed"
        try:
            mom_pct, mom_y, mom_m = await _arbitrage_kyiv_month_mom_fields_huawei(db, hw)
            payload["arbitrageKyivMonthMomPct"] = mom_pct
            payload["arbitrageKyivMonthMomYear"] = mom_y
            payload["arbitrageKyivMonthMomMonth"] = mom_m
        except Exception as exc:
            logger.exception("landing-totals Huawei arbitrage MoM: %s", exc)
            payload["arbitrageKyivMonthMomPct"] = None
            payload["arbitrageKyivMonthMomYear"] = None
            payload["arbitrageKyivMonthMomMonth"] = None
        return await _finalize_landing_response(
            db, payload, deye_device_sn_for_import_mtd=None, huawei_station_code_for_import_mtd=hw
        )

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
        lat: Optional[float] = None
        lon: Optional[float] = None
        try:
            lat, lon = await get_inverter_station_coordinates(device_sn.strip())
        except Exception as exc:
            logger.warning(
                "landing-totals lost solar total: station coords unavailable (%s); using synthetic clear-sky weights",
                exc,
            )
        try:
            lost_total = await sum_lost_solar_all_sample_kyiv_days(
                db, device_sn.strip(), lat=lat, lon=lon
            )
            # Always a number so the landing counter shows a total (0 when no computable days).
            payload["lostSolarKwhTotal"] = float(lost_total) if lost_total is not None else 0.0
        except Exception as exc:
            logger.exception("landing-totals lost solar total: %s", exc)
            payload["lostSolarKwhTotal"] = 0.0
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

    deye_sn_mtd = device_sn.strip() if device_sn else None
    return await _finalize_landing_response(
        db, payload, deye_device_sn_for_import_mtd=deye_sn_mtd
    )


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


async def _lost_solar_hourly_bars_kyiv(
    session: AsyncSession,
    *,
    device_sn: str,
    days: int,
) -> dict[str, Any]:
    sn = (device_sn or "").strip()
    if not sn:
        return {
            "chartKind": "lost_solar",
            "deviceSn": "",
            "zoneEic": settings.OREE_COMPARE_ZONE_EIC,
            "kyivDayStart": _kyiv_today().isoformat(),
            "kyivDayEnd": _kyiv_today().isoformat(),
            "days": max(1, days),
            "bars": [],
        }

    lat: Optional[float] = None
    lon: Optional[float] = None
    try:
        lat, lon = await get_inverter_station_coordinates(sn)
    except Exception as exc:
        logger.warning("lost-solar-hourly-bars: station coords unavailable (%s); using synthetic clear-sky weights", exc)

    end = _kyiv_today()
    n = max(1, min(31, int(days)))
    d_start = end - timedelta(days=n - 1)
    zone = settings.OREE_COMPARE_ZONE_EIC

    bars_raw: list[tuple[date, int, float]] = []
    for k in range(n):
        d = end - timedelta(days=k)
        br = await lost_solar_hourly_breakdown_one_kyiv_day(session, sn, d, lat=lat, lon=lon)
        if not br:
            continue
        for hour, lkwh in br:
            if lkwh > 1e-9:
                bars_raw.append((d, int(hour), float(lkwh)))

    bars_raw.sort(key=lambda x: (x[0], x[1]))

    dam_map: dict[tuple[date, int], Optional[float]] = {}
    if bars_raw:
        r = await session.execute(
            text(
                """
                SELECT trade_day, period, (price_uah_mwh / 1000.0) AS dam_uah_per_kwh
                FROM oree_dam_price
                WHERE zone_eic = :zone
                  AND trade_day >= :d_start
                  AND trade_day <= :d_end
                """
            ),
            {"zone": zone, "d_start": d_start, "d_end": end},
        )
        for row in r.mappings().all():
            td = row["trade_day"]
            if hasattr(td, "date"):
                td = td.date()
            period = int(row["period"])
            dam_map[(td, period)] = float(row["dam_uah_per_kwh"]) if row["dam_uah_per_kwh"] is not None else None

    bars: list[dict[str, Any]] = []
    for kd, kh, lkwh in bars_raw:
        if hasattr(kd, "date"):
            kd = kd.date()
        dam = dam_map.get((kd, kh + 1))
        bars.append(
            {
                "dayIso": kd.isoformat() if hasattr(kd, "isoformat") else str(kd),
                "hour": kh,
                "lostSolarKwh": lkwh,
                "damUahPerKwh": dam,
            }
        )

    return {
        "chartKind": "lost_solar",
        "deviceSn": sn,
        "zoneEic": zone,
        "kyivDayStart": d_start.isoformat(),
        "kyivDayEnd": end.isoformat(),
        "days": n,
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
    Hourly grid export (kWh) for the last ``days`` Kyiv days: one bar per hour with export > 0.

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


@router.get("/lost-solar-hourly-bars")
async def lost_solar_hourly_bars(
    device_sn: str = Query(
        ...,
        alias="deviceSn",
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial (lost solar is computed only for Deye device samples).",
    ),
    days: int = Query(
        default=7,
        ge=1,
        le=31,
        description="Kyiv calendar days ending today (inclusive).",
    ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Hourly clipped-PV (kWh) for the last ``days`` Kyiv days: one bar per hour with estimated loss > 0.
    DAM UAH/kWh when present in ``oree_dam_price`` (hour ``period`` = Kyiv hour + 1, same as export bars).
    """
    try:
        payload = await _lost_solar_hourly_bars_kyiv(db, device_sn=device_sn, days=days)
        payload["ok"] = True
        return JSONResponse(content=payload, headers=_NO_STORE)
    except Exception as exc:
        logger.exception("lost-solar-hourly-bars: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "lost_solar_hourly_bars_failed"},
            headers=_NO_STORE,
        )


@router.get("/reference-lcoe")
async def reference_lcoe() -> JSONResponse:
    """
    Illustrative UAH/kWh for Power-flow nodes: LiFePO4 (8000 equiv. cycles) and tier-1 PV (20y),
    from reference USD CAPEX assumptions × NBU UAH/USD. Tune via POWER_FLOW_* env vars — not a site quote.
    """
    global _reference_lcoe_mono, _reference_lcoe_body
    now = time.monotonic()
    if _reference_lcoe_body is not None and now - _reference_lcoe_mono < _REFERENCE_LCOE_TTL_SEC:
        return JSONResponse(content=_reference_lcoe_body, headers=_NO_STORE)

    today = date.today()
    uah_per_usd = await fetch_usd_uah_rate_for_date(today)
    if uah_per_usd is None or not math.isfinite(uah_per_usd) or uah_per_usd <= 0:
        err: dict[str, Any] = {"ok": False, "detail": "nbu_usd_unavailable"}
        return JSONResponse(content=err, headers=_NO_STORE)

    from app.ref_battery_lcoe import compute_reference_battery_uah_per_kwh

    battery_uah = await compute_reference_battery_uah_per_kwh(today)
    if battery_uah is None:
        err = {"ok": False, "detail": "nbu_usd_unavailable"}
        return JSONResponse(content=err, headers=_NO_STORE)

    dod = float(settings.POWER_FLOW_BATTERY_USABLE_DOD)
    cyc = max(1, int(settings.POWER_FLOW_BATTERY_EQUIV_CYCLES))
    pack = float(settings.POWER_FLOW_REF_LIFEPO4_USD_PER_KWH)
    bop = float(settings.POWER_FLOW_BATTERY_BOP_MULT)

    pv_w = float(settings.POWER_FLOW_REF_PV_USD_PER_W)
    years = max(1, int(settings.POWER_FLOW_PV_LIFE_YEARS))
    yld = float(settings.POWER_FLOW_PV_YIELD_KWH_PER_KW_YEAR)
    denom_pv = max(1e-12, yld * float(years))
    solar_uah = (pv_w * 1000.0 * uah_per_usd) / denom_pv

    body: dict[str, Any] = {
        "ok": True,
        "nbuUahPerUsd": round(uah_per_usd, 4),
        "batteryAmortizedUahPerKwh": round(battery_uah, 4),
        "solarAmortizedUahPerKwh": round(solar_uah, 4),
        "assumptions": {
            "lifepo4RefUsdPerKwhNominal": pack,
            "batteryBopMultiplier": bop,
            "batteryUsableDod": dod,
            "batteryEquivCycles": cyc,
            "pvInstalledUsdPerW": pv_w,
            "pvLifetimeYears": years,
            "pvYieldKwhPerKwYear": yld,
        },
    }
    _reference_lcoe_mono = now
    _reference_lcoe_body = body
    return JSONResponse(content=body, headers=_NO_STORE)
