"""ENTSO-E DAM (EUR/MWh) — DB-backed chart API; optional sync from Transparency REST API."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.db import get_db
from app.entsoe_dam_service import (
    BRUSSELS,
    delivery_tomorrow_brussels,
    entsoe_dam_configured,
    get_hourly_entsoe_eur_mwh,
    list_zone_catalog,
    resolve_zone_eic,
    sync_entsoe_all_configured_zones,
    sync_entsoe_zone_to_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dam/entsoe", tags=["dam-entsoe"])

_NO_STORE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


def _has_any_entsoe_hourly(hourly: list[Optional[float]]) -> bool:
    return any(x is not None for x in hourly)


def _brussels_today() -> date:
    return datetime.now(BRUSSELS).date()


async def _hourly_entsoe_chart_payload(
    db: AsyncSession,
    day: date,
    zone_eic: str,
) -> tuple[list[Optional[float]], list[Optional[float]], bool]:
    """Read DB; optional lazy ENTSO-E sync. Returns (eur_mwh hourly, eur_per_kwh hourly, lazy_sync_triggered)."""
    hourly_mwh = await get_hourly_entsoe_eur_mwh(db, day, zone_eic)
    lazy_sync_triggered = False
    if (
        not _has_any_entsoe_hourly(hourly_mwh)
        and entsoe_dam_configured()
        and settings.ENTSOE_CHART_DAY_LAZY_FETCH
        and day <= delivery_tomorrow_brussels()
    ):
        n = await sync_entsoe_zone_to_db(db, zone_eic, day)
        if n > 0:
            await db.commit()
            lazy_sync_triggered = True
        hourly_mwh = await get_hourly_entsoe_eur_mwh(db, day, zone_eic)
    hourly_eur_per_kwh: list[Optional[float]] = []
    for m in hourly_mwh:
        if m is None:
            hourly_eur_per_kwh.append(None)
        else:
            hourly_eur_per_kwh.append(float(m) / 1000.0)
    return hourly_mwh, hourly_eur_per_kwh, lazy_sync_triggered


@router.get("/zones")
async def entsoe_zones() -> JSONResponse:
    """Configured bidding zones (aliases + EIC + IANA timezone for delivery windows)."""
    return JSONResponse(
        content={
            "ok": True,
            "zones": list_zone_catalog(),
            "configured": entsoe_dam_configured(),
        },
        headers=_NO_STORE,
    )


@router.post("/sync")
async def entsoe_sync_now(
    db: AsyncSession = Depends(get_db),
    delivery: Optional[date] = Query(default=None, alias="delivery"),
) -> JSONResponse:
    """
    Fetch day-ahead prices from ENTSO-E for all ENTSOE_DAM_ZONE_EICS and upsert entsoe_dam_price.
    Requires ENTSOE_SECURITY_TOKEN and ENTSOE_DAM_MANUAL_SYNC_ENABLED=1.
    """
    if not settings.ENTSOE_DAM_MANUAL_SYNC_ENABLED:
        return JSONResponse(
            content={
                "ok": False,
                "configured": entsoe_dam_configured(),
                "rows": 0,
                "detail": "Manual ENTSO-E sync disabled (set ENTSOE_DAM_MANUAL_SYNC_ENABLED=1)",
            },
            status_code=403,
            headers=_NO_STORE,
        )
    if not entsoe_dam_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "rows": 0, "detail": "ENTSOE_SECURITY_TOKEN not set"},
            headers=_NO_STORE,
        )
    day = delivery or delivery_tomorrow_brussels()
    try:
        n = await sync_entsoe_all_configured_zones(db, day)
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "deliveryDay": day.isoformat(),
                "rows": n,
            },
            headers=_NO_STORE,
        )
    except Exception as exc:
        logger.exception("ENTSO-E sync failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync-zone")
async def entsoe_sync_one_zone(
    db: AsyncSession = Depends(get_db),
    zone: str = Query(..., description="Alias (ES, PL) or full EIC"),
    delivery: Optional[date] = Query(default=None, alias="delivery"),
) -> JSONResponse:
    """Sync a single zone (same manual gate as POST /sync)."""
    if not settings.ENTSOE_DAM_MANUAL_SYNC_ENABLED:
        return JSONResponse(
            content={"ok": False, "detail": "ENTSOE_DAM_MANUAL_SYNC_ENABLED=0"},
            status_code=403,
            headers=_NO_STORE,
        )
    if not entsoe_dam_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "detail": "ENTSOE_SECURITY_TOKEN not set"},
            headers=_NO_STORE,
        )
    ze = resolve_zone_eic(zone)
    if ze is None:
        return JSONResponse(
            content={"ok": False, "detail": f"Unknown zone: {zone!r}; use /api/dam/entsoe/zones"},
            status_code=400,
            headers=_NO_STORE,
        )
    day = delivery or delivery_tomorrow_brussels()
    try:
        n = await sync_entsoe_zone_to_db(db, ze, day)
        await db.commit()
        return JSONResponse(
            content={
                "ok": True,
                "deliveryDay": day.isoformat(),
                "zoneEic": ze,
                "rows": n,
            },
            headers=_NO_STORE,
        )
    except Exception as exc:
        logger.exception("ENTSO-E zone sync failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/chart-day")
async def entsoe_chart_day(
    date_param: Optional[date] = Query(default=None, alias="date"),
    zone: str = Query("ES", description="Alias (ES, PL) or bidding-zone EIC"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Hourly DAM EUR/MWh from DB (periods 1..24).

    When the DB has no rows for this delivery day and ENTSOE_CHART_DAY_LAZY_FETCH is enabled, pulls ENTSO-E once
    (same as POST /sync-zone for that day) so charts backfill without a manual sync. Skips delivery days after
    ``delivery_tomorrow_brussels()`` (no published day-ahead yet).
    """
    day = date_param or _brussels_today()
    ze = resolve_zone_eic(zone)
    if ze is None:
        return JSONResponse(
            content={
                "ok": False,
                "detail": f"Unknown zone: {zone!r}",
                "date": day.isoformat(),
            },
            status_code=400,
            headers=_NO_STORE,
        )
    hourly_mwh, hourly_eur_per_kwh, lazy_sync_triggered = await _hourly_entsoe_chart_payload(db, day, ze)

    return JSONResponse(
        content={
            "ok": True,
            "date": day.isoformat(),
            "zoneEic": ze,
            "hourlyPriceDamEurMwh": hourly_mwh,
            "hourlyPriceDamEurPerKwh": hourly_eur_per_kwh,
            "entsoeConfigured": entsoe_dam_configured(),
            "lazySyncTriggered": lazy_sync_triggered,
        },
        headers=_NO_STORE,
    )


@router.get("/chart-day-zones")
async def entsoe_chart_day_zones(
    date_param: Optional[date] = Query(default=None, alias="date"),
    zones: str = Query(
        "ES,PL",
        description="Comma-separated zone aliases (e.g. ES,PL)",
    ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Multiple zones in one response (OREE overlay: ES + PL). Same DB/lazy-sync rules as ``/chart-day`` per zone.
    """
    day = date_param or _brussels_today()
    aliases = [p.strip().upper() for p in zones.replace(" ", "").split(",") if p.strip()]
    if not aliases:
        return JSONResponse(
            content={"ok": False, "detail": "No zones in zones= parameter", "date": day.isoformat()},
            status_code=400,
            headers=_NO_STORE,
        )
    out_zones: dict[str, Any] = {}
    lazy_by_zone: dict[str, bool] = {}
    for alias in aliases:
        ze = resolve_zone_eic(alias)
        if ze is None:
            return JSONResponse(
                content={
                    "ok": False,
                    "detail": f"Unknown zone: {alias!r}",
                    "date": day.isoformat(),
                },
                status_code=400,
                headers=_NO_STORE,
            )
        mwh, eurk, lazy = await _hourly_entsoe_chart_payload(db, day, ze)
        lazy_by_zone[alias] = lazy
        out_zones[alias] = {
            "zoneEic": ze,
            "hourlyPriceDamEurMwh": mwh,
            "hourlyPriceDamEurPerKwh": eurk,
        }
    return JSONResponse(
        content={
            "ok": True,
            "date": day.isoformat(),
            "entsoeConfigured": entsoe_dam_configured(),
            "lazySyncTriggeredByZone": lazy_by_zone,
            "zones": out_zones,
        },
        headers=_NO_STORE,
    )
