"""EV driver GPS tracker: ingest pings, process stays/trips, public open-data aggregates."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.db import get_db
from app.ev_driver_geoip import client_ip_from_headers, resolve_ip_lat_lon
from app.ev_driver_track_service import (
    aggregate_charging_demand,
    aggregate_heatmap_points,
    aggregate_open_data_summary,
    aggregate_popular_routes,
)
from app.ev_driver_tracker_schemas import EvDriverPointsIn
from app.models import EvDriverGpsRaw

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ev-driver-tracker", tags=["ev-driver-tracker"])

_NO_STORE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}
_OPEN_CACHE: dict[str, tuple[float, Any]] = {}
_DRIVER_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def _cache_get(key: str) -> Optional[Any]:
    entry = _OPEN_CACHE.get(key)
    if not entry:
        return None
    ts, payload = entry
    if time.monotonic() - ts > settings.EV_TRACKER_OPEN_DATA_CACHE_SEC:
        return None
    return payload


def _cache_set(key: str, payload: Any) -> None:
    _OPEN_CACHE[key] = (time.monotonic(), payload)


def _ms_to_utc(ts_ms: int) -> Optional[datetime]:
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
    now = datetime.now(timezone.utc)
    if dt > now + timedelta(minutes=5):
        return None
    if dt < now - timedelta(days=30):
        return None
    return dt


@router.post("/points")
async def ingest_points(
    body: EvDriverPointsIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Accept batched driver GPS pings (gps, cookie, or ip-resolved fallback)."""
    if not _DRIVER_ID_RE.match(body.driverId):
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_driver_id"}, headers=_NO_STORE)

    client_ip = client_ip_from_headers(
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client else None,
    )
    ip_coords: Optional[tuple[float, float]] = None

    accepted = 0
    dropped = 0
    rows: list[dict[str, Any]] = []

    for pt in body.points:
        recorded_at = _ms_to_utc(pt.ts)
        if recorded_at is None:
            dropped += 1
            continue

        lat = pt.lat
        lon = pt.lng
        source = pt.source

        if lat is None or lon is None:
            if ip_coords is None:
                ip_coords = await resolve_ip_lat_lon(client_ip)
            if ip_coords is None:
                dropped += 1
                continue
            lat, lon = ip_coords
            source = "ip"

        rows.append(
            {
                "driver_id": body.driverId,
                "recorded_at": recorded_at,
                "lat": lat,
                "lon": lon,
                "source": source,
                "accuracy_m": pt.accuracyM,
                "processed": False,
            }
        )
        accepted += 1

    if rows:
        stmt = insert(EvDriverGpsRaw).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["driver_id", "recorded_at"])
        await db.execute(stmt)
        await db.commit()

    return JSONResponse(content={"ok": True, "accepted": accepted, "dropped": dropped}, headers=_NO_STORE)


@router.get("/heatmap-points")
async def heatmap_points(
    days: int = Query(default=90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    cache_key = f"heatmap:{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return JSONResponse(content=cached, headers=_NO_STORE)

    points = await aggregate_heatmap_points(db, days=days)
    payload = {"ok": True, "points": points}
    _cache_set(cache_key, payload)
    return JSONResponse(content=payload, headers=_NO_STORE)


@router.get("/popular-routes")
async def popular_routes(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    cache_key = f"routes:{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return JSONResponse(content=cached, headers=_NO_STORE)

    routes = await aggregate_popular_routes(db, days=days)
    payload = {"ok": True, "days": days, "routes": routes}
    _cache_set(cache_key, payload)
    return JSONResponse(content=payload, headers=_NO_STORE)


@router.get("/open-data/summary")
async def open_data_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    cache_key = f"summary:{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return JSONResponse(content=cached, headers=_NO_STORE)

    summary = await aggregate_open_data_summary(db, days=days)
    payload = {"ok": True, **summary}
    _cache_set(cache_key, payload)
    return JSONResponse(content=payload, headers=_NO_STORE)


@router.get("/open-data/charging-demand")
async def open_data_charging_demand(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    cache_key = f"charging:{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return JSONResponse(content=cached, headers=_NO_STORE)

    cells = await aggregate_charging_demand(db, days=days)
    payload = {"ok": True, "days": days, "cells": cells}
    _cache_set(cache_key, payload)
    return JSONResponse(content=payload, headers=_NO_STORE)
