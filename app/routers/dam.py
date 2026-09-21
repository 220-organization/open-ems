"""DAM (OREE) hourly prices from open-ems DB; chart-day is DB-only unless lazy sync is explicitly enabled."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app import settings
from app.dam_prices_xlsx import build_hourly_dam_prices_xlsx, dam_xlsx_filename
from app.entsoe_dam_service import BRUSSELS, list_entsoe_dam_prices_for_year, resolve_zone_eic
from app.oree_dam_service import (
    KYIV,
    ensure_dam_indexes_for_day,
    get_hourly_dam_with_optional_sync,
    get_lazy_oree_chart_meta,
    list_oree_dam_prices_for_year,
    oree_dam_configured,
    sync_dam_prices_to_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dam", tags=["dam"])

_NO_STORE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


def _kyiv_today() -> date:
    return datetime.now(KYIV).date()


_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _allowed_xlsx_years(market: str) -> tuple[int, int]:
    tz = BRUSSELS if market == "entsoe" else KYIV
    current = datetime.now(tz).date().year
    return current - 1, current


@router.post("/sync")
async def dam_sync_now(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """
    Fetch DAM from OREE API and upsert into oree_dam_price (requires OREE_API_KEY).

    Disabled unless OREE_DAM_MANUAL_SYNC_ENABLED=1 — normal flow is daily background sync only.
    """
    if not settings.OREE_DAM_MANUAL_SYNC_ENABLED:
        return JSONResponse(
            content={
                "ok": False,
                "configured": oree_dam_configured(),
                "rows": 0,
                "detail": "Manual DAM sync is disabled (set OREE_DAM_MANUAL_SYNC_ENABLED=1 to enable POST /api/dam/sync)",
            },
            status_code=403,
            headers=_NO_STORE,
        )
    if not oree_dam_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "rows": 0, "detail": "OREE_API_KEY not set"},
            headers=_NO_STORE,
        )
    try:
        n = await sync_dam_prices_to_db(db)
        return JSONResponse(
            content={"ok": True, "configured": True, "rows": n},
            headers=_NO_STORE,
        )
    except Exception as exc:
        logger.exception("DAM sync failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/chart-day")
async def dam_chart_day(
    date_param: Optional[date] = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    DAM chart hourly prices: read from DB only (UAH/kWh = MWh/1000).

    OREE is not called from this endpoint when OREE_DAM_LAZY_FETCH_MAX=0. Default is 5 on-demand pulls
    per trade day when DB is empty for Kyiv tomorrow. Otherwise populate prices via the daily scheduler
    (OREE_DAM_DAILY_SYNC_* Europe/Kyiv) or manual POST /api/dam/sync if enabled.
    """
    day = date_param or _kyiv_today()
    zone = settings.OREE_COMPARE_ZONE_EIC

    hourly_mwh, sync_triggered = await get_hourly_dam_with_optional_sync(db, day, zone)
    lazy_oree = await get_lazy_oree_chart_meta(db, day)
    hourly_dam_uah_per_kwh: list[Optional[float]] = []
    for m in hourly_mwh:
        if m is None:
            hourly_dam_uah_per_kwh.append(None)
        else:
            hourly_dam_uah_per_kwh.append(float(m) / 1000.0)

    return JSONResponse(
        content={
            "ok": True,
            "date": day.isoformat(),
            "zoneEic": zone,
            "hourlyPriceDamUahMwh": hourly_mwh,
            "hourlyPriceDamUahPerKwh": hourly_dam_uah_per_kwh,
            "oreeConfigured": oree_dam_configured(),
            "syncTriggered": sync_triggered,
            "lazyOree": lazy_oree,
        },
        headers=_NO_STORE,
    )


@router.get("/damindexes")
async def dam_damindexes(
    date_param: Optional[date] = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    DAM price indices (DAY/NIGHT/PEAK/HPEAK/BASE) for `date` (YYYY-MM-DD), default Kyiv today.
    Reads `oree_dam_index` first; if empty, calls OREE /damindexes and upserts, then returns.
    Response `data` matches OREE shape (prices in UAH/MWh strings); UI converts to UAH/kWh.
    """
    day = date_param or _kyiv_today()
    if not oree_dam_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "detail": "OREE_API_KEY not set",
                "data": None,
                "date": day.isoformat(),
            },
            headers=_NO_STORE,
        )
    try:
        data, source = await ensure_dam_indexes_for_day(db, day)
        if data is None:
            return JSONResponse(
                content={
                    "ok": False,
                    "configured": True,
                    "detail": "No DAM index data for this date.",
                    "data": None,
                    "date": day.isoformat(),
                },
                headers=_NO_STORE,
            )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "date": day.isoformat(),
                "source": source,
                "data": data,
            },
            headers=_NO_STORE,
        )
    except Exception as exc:
        logger.exception("damindexes failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/prices.xlsx")
async def dam_prices_xlsx(
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    market: str = Query(default="oree", description="oree or entsoe"),
    zone: str = Query(default="ES", description="ENTSO-E alias when market=entsoe"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Hourly DAM prices for a calendar year as Excel (.xlsx).

    ``year`` defaults to the current year in the market timezone (Kyiv / Brussels).
    Only the current year and the previous year are allowed.
    OREE export is UAH/kWh; ENTSO-E export is EUR/kWh. One row per trade day, hours 00:00–23:00.
    """
    m = (market or "oree").strip().lower()
    if m not in ("oree", "entsoe"):
        return JSONResponse(
            content={"ok": False, "detail": "market must be oree or entsoe"},
            status_code=400,
            headers=_NO_STORE,
        )
    prev_y, cur_y = _allowed_xlsx_years(m)
    y = int(year) if year is not None else cur_y
    if y not in (prev_y, cur_y):
        return JSONResponse(
            content={
                "ok": False,
                "detail": f"year must be {prev_y} or {cur_y}",
                "year": y,
            },
            status_code=400,
            headers=_NO_STORE,
        )

    if m == "entsoe":
        ze = resolve_zone_eic(zone)
        if ze is None:
            return JSONResponse(
                content={"ok": False, "detail": f"Unknown zone: {zone!r}"},
                status_code=400,
                headers=_NO_STORE,
            )
        rows = await list_entsoe_dam_prices_for_year(db, y, ze)
        xlsx = build_hourly_dam_prices_xlsx(
            rows,
            year=y,
            market_label="ENTSO-E",
            zone_label=f"{zone.strip().upper()} ({ze})",
            unit_label="EUR/kWh",
        )
        filename = dam_xlsx_filename("entsoe", y, zone.strip().upper())
    else:
        ze = settings.OREE_COMPARE_ZONE_EIC
        rows = await list_oree_dam_prices_for_year(db, y, ze)
        xlsx = build_hourly_dam_prices_xlsx(
            rows,
            year=y,
            market_label="Ukraine (OREE)",
            zone_label=ze,
            unit_label="UAH/kWh",
        )
        filename = dam_xlsx_filename("oree", y)

    return Response(
        content=xlsx,
        media_type=_XLSX_MEDIA,
        headers={
            **_NO_STORE,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
