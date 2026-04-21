"""Huawei FusionSolar Northbound — plant list + status (no secrets in browser)."""

import logging
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from zoneinfo import ZoneInfo
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.db import get_db
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

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/huawei", tags=["huawei"])

_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


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


@router.post("/power-snapshot")
async def post_power_snapshot(session: AsyncSession = Depends(get_db)):
    """
    Run one Huawei power DB snapshot (same as the background task): fetch live power per plant and upsert
    ``huawei_power_sample`` for the current 5-minute bucket. Use when hourly chart is empty until samples exist.
    """
    if not huawei_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        n = await run_huawei_power_snapshot(session)
        await session.commit()
        return JSONResponse(
            content={"ok": True, "configured": True, "plantsUpdated": int(n)},
            headers=_NO_STORE_CACHE,
        )
    except HuaweiAuthError as exc:
        await session.rollback()
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
        await session.rollback()
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
