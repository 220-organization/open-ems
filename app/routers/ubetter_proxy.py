"""Ubetter EMS Open API — device list + realtime summary (no secrets in browser)."""

import logging
from datetime import date as date_cls
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.ubetter_api import (
    UbetterApiError,
    UbetterAuthError,
    UbetterUpstreamHttpError,
    get_device_summary,
    get_energy,
    get_power_flow,
    get_run_strategy,
    list_devices,
    start_manual_charge,
    start_manual_discharge,
    ubetter_configured,
    ubetter_missing_env_names,
)
from app.ubetter_power_service import hourly_device_history_for_kyiv_day, run_ubetter_power_snapshot

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/ubetter", tags=["ubetter"])

_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


class UbetterChargeBody(BaseModel):
    sn: str = Field(..., min_length=1, max_length=128)
    chargeSocPercent: int = Field(..., ge=1, le=100, description="Target SoC % when charging")
    dischargeSocPercent: int = Field(10, ge=0, le=99, description="Discharge floor SoC % (limits)")
    powerKw: Optional[float] = Field(None, gt=0, le=500)


class UbetterDischargeBody(BaseModel):
    sn: str = Field(..., min_length=1, max_length=128)
    dischargeSocPercent: int = Field(..., ge=0, le=99, description="Target SoC % when discharging")
    chargeSocPercent: int = Field(95, ge=1, le=100, description="Charge ceiling SoC % (limits)")
    powerKw: Optional[float] = Field(None, gt=0, le=500)


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


@router.get("/run-strategy")
async def get_run_strategy_route(
    sn: str = Query(..., min_length=1, max_length=128, description="Device serial number"),
):
    if not ubetter_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        body = await get_run_strategy(sn)
        return JSONResponse(content=body, headers=_NO_STORE_CACHE)
    except UbetterAuthError as exc:
        _log_ubetter_route_error("GET /api/ubetter/run-strategy", exc)
        return JSONResponse(
            content={"ok": False, "configured": True, "reason": "ubetter_login_failed", "detail": str(exc)[:400]},
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_ubetter_route_error("GET /api/ubetter/run-strategy", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/charge")
async def post_charge_route(body: UbetterChargeBody):
    """Manual charge via Open API run-strategy (strategy=0, chargeCtrl=1)."""
    if not ubetter_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        result = await start_manual_charge(
            body.sn,
            charge_soc_percent=body.chargeSocPercent,
            discharge_soc_percent=body.dischargeSocPercent,
            power_kw=body.powerKw,
        )
        status = 200 if result.get("ok") else 409
        return JSONResponse(content=result, status_code=status, headers=_NO_STORE_CACHE)
    except UbetterAuthError as exc:
        _log_ubetter_route_error("POST /api/ubetter/charge", exc)
        return JSONResponse(
            content={"ok": False, "configured": True, "reason": "ubetter_login_failed", "detail": str(exc)[:400]},
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_ubetter_route_error("POST /api/ubetter/charge", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/discharge")
async def post_discharge_route(body: UbetterDischargeBody):
    """Manual discharge via Open API run-strategy (strategy=0, chargeCtrl=2)."""
    if not ubetter_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        result = await start_manual_discharge(
            body.sn,
            discharge_soc_percent=body.dischargeSocPercent,
            charge_soc_percent=body.chargeSocPercent,
            power_kw=body.powerKw,
        )
        status = 200 if result.get("ok") else 409
        return JSONResponse(content=result, status_code=status, headers=_NO_STORE_CACHE)
    except UbetterAuthError as exc:
        _log_ubetter_route_error("POST /api/ubetter/discharge", exc)
        return JSONResponse(
            content={"ok": False, "configured": True, "reason": "ubetter_login_failed", "detail": str(exc)[:400]},
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_ubetter_route_error("POST /api/ubetter/discharge", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/soc-history-day")
async def get_soc_history_day_route(
    sn: str = Query(
        ...,
        min_length=1,
        max_length=128,
        description="Ubetter device serial number",
    ),
    date: str = Query(
        ...,
        min_length=10,
        max_length=10,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Calendar day YYYY-MM-DD (Europe/Kyiv boundaries)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Mean SoC / grid / PV / load per Kyiv hour from ubetter_power_sample (5-min buckets)."""
    if not ubetter_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "sn": sn,
                "date": date,
                "hourlySocPercent": [None] * 24,
                "hourlyGridPowerW": [None] * 24,
                "hourlyGridFrequencyHz": [None] * 24,
                "hourlyPvKwh": [None] * 24,
                "hourlyLoadKwh": [None] * 24,
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        trade_day = date_cls.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD") from exc
    try:
        hourly_soc, hourly_grid_w, hourly_grid_hz, hourly_pv_kwh, hourly_load_kwh = (
            await hourly_device_history_for_kyiv_day(db, sn, trade_day)
        )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "sn": sn,
                "date": date,
                "hourlySocPercent": hourly_soc,
                "hourlyGridPowerW": hourly_grid_w,
                "hourlyGridFrequencyHz": hourly_grid_hz,
                "hourlyPvKwh": hourly_pv_kwh,
                "hourlyLoadKwh": hourly_load_kwh,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("GET /api/ubetter/soc-history-day — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/power-snapshot")
async def post_power_snapshot_route(db: AsyncSession = Depends(get_db)):
    """Manual trigger: fetch live Ubetter metrics and upsert current 5-min bucket."""
    if not ubetter_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        n = await run_ubetter_power_snapshot(db)
        await db.commit()
        return JSONResponse(content={"ok": True, "configured": True, "rowsUpserted": n}, headers=_NO_STORE_CACHE)
    except Exception as exc:
        logger.exception("POST /api/ubetter/power-snapshot — failed: %s", exc)
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
