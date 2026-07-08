"""Huawei FusionSolar Northbound — plant list + status (no secrets in browser)."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from zoneinfo import ZoneInfo
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.db import get_db, async_session_factory
from app.deye_inverter_pin import strip_inverter_pin_tokens_anywhere
from app.huawei_api import (
    HuaweiAuthError,
    HuaweiRateLimitNoCacheError,
    HuaweiUpstreamHttpError,
    get_plant_status,
    get_power_flow,
    huawei_configured,
    huawei_missing_env_names,
    list_stations,
)
from app.huawei_power_service import get_station_hourly_chart_from_db, run_huawei_power_snapshot
from app.huawei_station_energy_service import get_or_refresh_totals

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/huawei", tags=["huawei"])

_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}

# Debounce lazy snapshot triggers from GET /power-flow (one attempt per plant per interval).
_lazy_power_snapshot_at: dict[str, float] = {}


def _public_huawei_station_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Strip ``pin`` tokens from plant names for the browser (same convention as Deye labels)."""
    out: list[dict[str, Any]] = []
    for x in rows:
        code = str(x.get("stationCode") or "").strip()
        raw = str(x.get("stationName") or "")
        disp = strip_inverter_pin_tokens_anywhere(raw) or code
        item: dict[str, Any] = {"stationCode": code, "stationName": disp}
        pdn = str(x.get("plantDn") or "").strip()
        if pdn:
            item["plantDn"] = pdn
        out.append(item)
    return out


def _log_huawei_route_error(context: str, exc: BaseException) -> None:
    """Expected upstream outages (5xx, timeouts) — one warning line, no traceback."""
    if isinstance(exc, HuaweiAuthError):
        logger.warning("%s — Huawei auth failed: %s", context, exc)
        return
    if isinstance(exc, HuaweiUpstreamHttpError):
        logger.warning("%s — Huawei upstream HTTP: %s", context, exc)
        return
    if isinstance(exc, httpx.HTTPStatusError):
        resp = exc.response
        url = str(resp.request.url) if resp.request else "?"
        snippet = (resp.text or "").replace("\n", " ").strip()[:240]
        tail = snippet or (exc.args[0] if exc.args else "")
        logger.warning("%s — Huawei HTTP %s %s — %s", context, resp.status_code, url, tail)
        return
    if isinstance(exc, httpx.RequestError):
        logger.warning("%s — Huawei request error: %s", context, exc)
        return
    logger.exception("%s — failed: %s", context, exc)


@router.get("/stations")
async def get_stations():
    if not huawei_configured():
        missing = huawei_missing_env_names()
        logger.warning(
            "GET /api/huawei/stations — not configured (missing: %s)",
            ", ".join(missing) if missing else "HUAWEI_*",
        )
        return JSONResponse(
            content={"configured": False, "items": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        items = await list_stations()
        public_items = _public_huawei_station_rows(items)
        logger.info("GET /api/huawei/stations — OK, %s plant(s)", len(public_items))
        return JSONResponse(
            content={"configured": True, "items": public_items},
            headers=_NO_STORE_CACHE,
        )
    except HuaweiAuthError as exc:
        logger.warning("GET /api/huawei/stations — Northbound login failed (graceful empty list)")
        return JSONResponse(
            content={
                "configured": True,
                "items": [],
                "huaweiAuthFailed": True,
                "reason": "login_failed",
                "detail": str(exc)[:400],
            },
            headers=_NO_STORE_CACHE,
        )
    except HuaweiRateLimitNoCacheError:
        # 200 so the UI stays usable (Deye path); client shows northboundRateLimited hint.
        logger.warning("GET /api/huawei/stations — Northbound rate limit, empty list (graceful)")
        return JSONResponse(
            content={
                "configured": True,
                "items": [],
                "northboundRateLimited": True,
                "retryAfterSec": settings.HUAWEI_STATION_LIST_COOLDOWN_AFTER_407_SEC,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_huawei_route_error("GET /api/huawei/stations", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _run_power_snapshot_background(only_station: Optional[str]) -> None:
    try:
        async with async_session_factory() as session:
            n, debug = await run_huawei_power_snapshot(session, only_station=only_station)
            await session.commit()
        if n:
            logger.info("Huawei power snapshot background: %s plant row(s) upserted", n)
        elif debug:
            logger.info("Huawei power snapshot background: no rows — %s", debug)
    except Exception:
        logger.exception("Huawei power snapshot background failed")


def _maybe_schedule_lazy_power_snapshot(station_code: str) -> None:
    """When UI has no fresh sample, kick the background snapshot task (debounced per plant)."""
    st = (station_code or "").strip()
    if not st or not settings.HUAWEI_POWER_SNAPSHOT_ENABLED:
        return
    now = time.time()
    debounce = max(120.0, float(settings.HUAWEI_POWER_SNAPSHOT_INTERVAL_SEC) * 0.5)
    last = _lazy_power_snapshot_at.get(st, 0.0)
    if now - last < debounce:
        return
    _lazy_power_snapshot_at[st] = now
    asyncio.create_task(_run_power_snapshot_background(st))


@router.post("/power-snapshot")
async def post_power_snapshot(
    stationCodes: Optional[str] = Query(
        None,
        max_length=512,
        description="Optional single plant stationCode; default round-robin one plant per call.",
    ),
    wait: bool = Query(
        False,
        description="When true, block until snapshot finishes (may take several minutes).",
    ),
):
    """
    Run one Huawei power DB snapshot (same as the background task): fetch live power for one plant
    and upsert ``huawei_power_sample`` for the current 5-minute bucket.

    Default returns immediately (202) — Northbound spacing can take 2–4 minutes per plant.
    """
    if not huawei_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    only = None
    if stationCodes and str(stationCodes).strip():
        only = str(stationCodes).split(",")[0].strip()
    if not wait:
        asyncio.create_task(_run_power_snapshot_background(only))
        return JSONResponse(
            status_code=202,
            content={
                "ok": True,
                "configured": True,
                "accepted": True,
                "stationCode": only,
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        async with async_session_factory() as session:
            n, debug = await run_huawei_power_snapshot(session, only_station=only)
            await session.commit()
        content: dict[str, Any] = {"ok": True, "configured": True, "plantsUpdated": int(n)}
        if n == 0 and debug:
            content["snapshotDebug"] = debug
        return JSONResponse(
            content=content,
            headers=_NO_STORE_CACHE,
        )
    except HuaweiAuthError as exc:
        _log_huawei_route_error("POST /api/huawei/power-snapshot", exc)
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "huawei_login_failed",
                "detail": str(exc)[:400],
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_huawei_route_error("POST /api/huawei/power-snapshot", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/station-hourly")
async def get_station_hourly_route(
    stationCodes: str = Query(
        ...,
        min_length=1,
        max_length=512,
        description="Plant stationCode",
    ),
    date: Optional[str] = Query(
        None,
        min_length=10,
        max_length=10,
        description="YYYY-MM-DD (Kyiv calendar day). Default: today in Europe/Kyiv.",
    ),
    session: AsyncSession = Depends(get_db),
):
    """Hourly kWh from DB (5-minute power samples); populated by background Huawei snapshot task."""
    if not huawei_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    day = date or datetime.now(ZoneInfo("Europe/Kyiv")).date().isoformat()
    try:
        body = await get_station_hourly_chart_from_db(session, stationCodes, day)
        return JSONResponse(content=body, headers=_NO_STORE_CACHE)
    except Exception as exc:
        _log_huawei_route_error("GET /api/huawei/station-hourly", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/power-flow")
async def get_power_flow_route(
    stationCodes: str = Query(
        ...,
        min_length=1,
        max_length=512,
        description="Plant stationCode (e.g. from GET /api/huawei/stations)",
    ),
):
    """Instantaneous PV / grid / load (W) via getDevRealKpi (meter + inverter)."""
    if not huawei_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        body = await get_power_flow(stationCodes)
        if not body.get("ok") and body.get("reason") == "awaiting_fresh_sample":
            st = (stationCodes or "").split(",")[0].strip()
            _maybe_schedule_lazy_power_snapshot(st)
        if not body.get("ok") and body.get("reason") == "rate_limit":
            logger.warning("GET /api/huawei/power-flow — rate limit, no cache")
        return JSONResponse(content=body, headers=_NO_STORE_CACHE)
    except HuaweiAuthError as exc:
        _log_huawei_route_error("GET /api/huawei/power-flow", exc)
        st = (stationCodes or "").split(",")[0].strip()
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "huawei_login_failed",
                "detail": str(exc)[:400],
                "stationCode": st or None,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_huawei_route_error("GET /api/huawei/power-flow", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/plant-status")
async def get_plant_status_route(
    stationCodes: str = Query(
        ...,
        min_length=1,
        max_length=2000,
        description="Comma-separated station/plant codes from GET /api/huawei/stations",
    ),
):
    if not huawei_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "items": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        items = await get_plant_status(stationCodes)
        return JSONResponse(
            content={"ok": True, "configured": True, "items": items},
            headers=_NO_STORE_CACHE,
        )
    except HuaweiAuthError as exc:
        _log_huawei_route_error("GET /api/huawei/plant-status", exc)
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "items": [],
                "reason": "huawei_login_failed",
                "detail": str(exc)[:400],
            },
            headers=_NO_STORE_CACHE,
        )
    except HuaweiRateLimitNoCacheError:
        logger.warning("GET /api/huawei/plant-status — Northbound rate limit, empty list (graceful)")
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "items": [],
                "northboundRateLimited": True,
                "retryAfterSec": settings.HUAWEI_STATION_LIST_COOLDOWN_AFTER_407_SEC,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_huawei_route_error("GET /api/huawei/plant-status", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/station-energy")
async def get_station_energy_route(
    stationCodes: str = Query(
        ...,
        min_length=1,
        max_length=512,
        description="Plant stationCode (single code; comma list reserved for future).",
    ),
    period: str = Query(
        "day",
        pattern="^(day|month|year)$",
        description="Aggregation period: day | month | year",
    ),
    date: Optional[str] = Query(
        None,
        min_length=10,
        max_length=10,
        description="YYYY-MM-DD Kyiv calendar date (selects the period). Default: today Europe/Kyiv.",
    ),
    session: AsyncSession = Depends(get_db),
):
    """
    Station energy KPIs (getKpiStationDay/Month/Year) — DB-backed cache.

    UI reads from `huawei_station_energy_totals`; on miss / stale row the route lazily refreshes
    from FusionSolar Northbound and upserts. Background scheduler keeps rows fresh.
    """
    station_code = (stationCodes or "").split(",")[0].strip()
    if not station_code:
        return JSONResponse(
            content={"ok": False, "reason": "missing_station"},
            headers=_NO_STORE_CACHE,
        )
    date_iso = date or datetime.now(ZoneInfo("Europe/Kyiv")).date().isoformat()
    try:
        body = await get_or_refresh_totals(session, station_code, period, date_iso)
        body.setdefault("configured", huawei_configured())
        return JSONResponse(content=body, headers=_NO_STORE_CACHE)
    except HuaweiAuthError as exc:
        _log_huawei_route_error("GET /api/huawei/station-energy", exc)
        return JSONResponse(
            content={"ok": False, "configured": True, "reason": "huawei_login_failed", "detail": str(exc)[:400]},
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_huawei_route_error("GET /api/huawei/station-energy", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
