"""Ubetter EMS Open API — device list + realtime summary (no secrets in browser)."""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.ubetter_api import (
    UbetterApiError,
    UbetterAuthError,
    UbetterUpstreamHttpError,
    get_device_summary,
    get_energy,
    get_power_flow,
    list_devices,
    ubetter_configured,
    ubetter_missing_env_names,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/ubetter", tags=["ubetter"])

_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


def _log_ubetter_route_error(context: str, exc: BaseException) -> None:
    if isinstance(exc, UbetterAuthError):
        logger.warning("%s — Ubetter auth failed: %s", context, exc)
        return
    if isinstance(exc, UbetterApiError):
        logger.warning("%s — Ubetter API error: %s", context, exc)
        return
    if isinstance(exc, UbetterUpstreamHttpError):
        logger.warning("%s — Ubetter upstream HTTP: %s", context, exc)
        return
    if isinstance(exc, httpx.RequestError):
        logger.warning("%s — Ubetter request error: %s", context, exc)
        return
    logger.exception("%s — failed: %s", context, exc)


@router.get("/devices")
async def get_devices_route():
    if not ubetter_configured():
        missing = ubetter_missing_env_names()
        logger.warning(
            "GET /api/ubetter/devices — not configured (missing: %s)",
            ", ".join(missing) if missing else "UBETTER_*",
        )
        return JSONResponse(
            content={"configured": False, "items": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        items = await list_devices()
        logger.info("GET /api/ubetter/devices — OK, %s device(s)", len(items))
        return JSONResponse(
            content={"configured": True, "items": items},
            headers=_NO_STORE_CACHE,
        )
    except UbetterAuthError as exc:
        logger.warning("GET /api/ubetter/devices — login failed (graceful empty list)")
        return JSONResponse(
            content={
                "configured": True,
                "items": [],
                "ubetterAuthFailed": True,
                "reason": "login_failed",
                "detail": str(exc)[:400],
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_ubetter_route_error("GET /api/ubetter/devices", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/power-flow")
async def get_power_flow_route(
    sn: str = Query(
        ...,
        min_length=1,
        max_length=128,
        description="Device serial number from GET /api/ubetter/devices",
    ),
):
    if not ubetter_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        body = await get_power_flow(sn)
        return JSONResponse(content=body, headers=_NO_STORE_CACHE)
    except UbetterAuthError as exc:
        _log_ubetter_route_error("GET /api/ubetter/power-flow", exc)
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "ubetter_login_failed",
                "detail": str(exc)[:400],
                "sn": (sn or "").strip() or None,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_ubetter_route_error("GET /api/ubetter/power-flow", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/device-summary")
async def get_device_summary_route(
    sn: str = Query(
        ...,
        min_length=1,
        max_length=128,
        description="Device serial number",
    ),
):
    if not ubetter_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        body = await get_device_summary(sn)
        return JSONResponse(content=body, headers=_NO_STORE_CACHE)
    except UbetterAuthError as exc:
        _log_ubetter_route_error("GET /api/ubetter/device-summary", exc)
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "ubetter_login_failed",
                "detail": str(exc)[:400],
                "sn": (sn or "").strip() or None,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_ubetter_route_error("GET /api/ubetter/device-summary", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/energy")
async def get_energy_route(
    sn: str = Query(..., min_length=1, max_length=128, description="Device serial number"),
    year: Optional[str] = Query(None, min_length=4, max_length=4, description="Year, e.g. 2026"),
    month: Optional[str] = Query(None, min_length=2, max_length=2, description="Month, e.g. 06"),
):
    if not ubetter_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        body = await get_energy(sn, year=year, month=month)
        return JSONResponse(content=body, headers=_NO_STORE_CACHE)
    except UbetterAuthError as exc:
        _log_ubetter_route_error("GET /api/ubetter/energy", exc)
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "ubetter_login_failed",
                "detail": str(exc)[:400],
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_ubetter_route_error("GET /api/ubetter/energy", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
