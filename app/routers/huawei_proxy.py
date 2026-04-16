"""Huawei FusionSolar Northbound — plant list + status (no secrets in browser)."""

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app import settings
from app.huawei_api import (
    HuaweiRateLimitNoCacheError,
    get_plant_status,
    get_power_flow,
    huawei_configured,
    huawei_missing_env_names,
    list_stations,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/huawei", tags=["huawei"])

_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


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
        logger.info("GET /api/huawei/stations — OK, %s plant(s)", len(items))
        return JSONResponse(
            content={"configured": True, "items": items},
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
        logger.exception("GET /api/huawei/stations — failed: %s", exc)
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
    except Exception as exc:
        logger.exception("GET /api/huawei/power-flow — failed: %s", exc)
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
        logger.exception("GET /api/huawei/plant-status — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
