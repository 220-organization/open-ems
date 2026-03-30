"""Expose Deye inverter list for the Power flow UI (server-side token; no secrets in browser)."""

import logging
from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deye_api import (
    deye_configured,
    deye_missing_env_names,
    fetch_device_soc_percent,
    get_live_metrics_cached,
    get_soc_map_cached,
    list_inverter_devices,
)
from app.deye_soc_service import hourly_inverter_history_for_kyiv_day

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/deye", tags=["deye"])

_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}

_MAX_INVERTER_SOCS = 200


class InverterSocsBody(BaseModel):
    deviceSns: list[str] = Field(default_factory=list, max_length=_MAX_INVERTER_SOCS)


@router.get("/inverters")
async def get_inverters():
    """
    Inverters under your Deye Cloud plants (Open API /station/listWithDevice).
    Requires DEYE_* env vars; returns empty list when not configured.
    """
    if not deye_configured():
        missing = deye_missing_env_names()
        logger.warning(
            "GET /api/deye/inverters — not configured (missing: %s)",
            ", ".join(missing) if missing else "DEYE_*",
        )
        return JSONResponse(
            content={"configured": False, "items": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        items = await list_inverter_devices()
        logger.info("GET /api/deye/inverters — OK, %s inverter(s)", len(items))
        return JSONResponse(
            content={"configured": True, "items": items},
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("GET /api/deye/inverters — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/soc")
async def get_inverter_soc(
    deviceSn: str = Query(
        ...,
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial (same as dropdown deviceSn)",
    ),
):
    """Battery SoC % from POST /device/latest (Open API), when DEYE_* is configured."""
    if not deye_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "socPercent": None},
            headers=_NO_STORE_CACHE,
        )
    try:
        soc = await fetch_device_soc_percent(deviceSn)
        if soc is None:
            return JSONResponse(
                content={
                    "ok": False,
                    "configured": True,
                    "socPercent": None,
                    "detail": "SOC not available for this device",
                },
                headers=_NO_STORE_CACHE,
            )
        return JSONResponse(
            content={"ok": True, "configured": True, "socPercent": soc},
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("GET /api/deye/soc — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/soc-history-day")
async def get_soc_history_day(
    deviceSn: str = Query(
        ...,
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial",
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
    """
    Mean SoC % and mean grid power (W signed: + import, − export) per Kyiv local hour from deye_soc_sample.
    """
    if not deye_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "deviceSn": deviceSn,
                "date": date,
                "hourlySocPercent": [None] * 24,
                "hourlyGridPowerW": [None] * 24,
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        trade_day = date_cls.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD") from exc
    try:
        hourly_soc, hourly_grid_w = await hourly_inverter_history_for_kyiv_day(db, deviceSn, trade_day)
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "deviceSn": deviceSn,
                "date": date,
                "hourlySocPercent": hourly_soc,
                "hourlyGridPowerW": hourly_grid_w,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("GET /api/deye/soc-history-day — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/ess-power")
async def get_ess_power(
    deviceSn: str = Query(
        ...,
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial (selected in Power flow UI)",
    ),
):
    """
    Live metrics from POST /device/latest (same response): batteryPowerW signed (positive = discharge),
    loadPowerW non-negative (home/AC load), pvPowerW non-negative (PV production),
    gridPowerW signed (positive import from grid, negative export). Cached ~25s.
    """
    if not deye_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "batteryPowerW": None,
                "loadPowerW": None,
                "pvPowerW": None,
                "gridPowerW": None,
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        bat, load_w, pv_w, grid_w = await get_live_metrics_cached(deviceSn)
        logger.info(
            "GET /api/deye/ess-power — sn=%s batteryW=%s loadW=%s pvW=%s gridW=%s",
            deviceSn,
            bat,
            load_w,
            pv_w,
            grid_w,
        )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "batteryPowerW": bat,
                "loadPowerW": load_w,
                "pvPowerW": pv_w,
                "gridPowerW": grid_w,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("GET /api/deye/ess-power — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/inverter-socs")
async def post_inverter_socs(body: InverterSocsBody):
    """
    Battery SoC % for many inverters; server-side TTL memory cache (5 min), batched Deye calls.
    """
    if not deye_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "items": []},
            headers=_NO_STORE_CACHE,
        )
    sns: list[str] = []
    seen: set[str] = set()
    for s in body.deviceSns[:_MAX_INVERTER_SOCS]:
        sn = str(s or "").strip()
        if len(sn) < 6 or len(sn) > 32 or not sn.isdigit():
            continue
        if sn not in seen:
            seen.add(sn)
            sns.append(sn)
    if not sns:
        return JSONResponse(
            content={"ok": True, "configured": True, "items": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        m = await get_soc_map_cached(sns)
        items = [{"deviceSn": sn, "socPercent": m.get(sn)} for sn in sns]
        logger.info("POST /api/deye/inverter-socs — OK, %s serial(s)", len(sns))
        return JSONResponse(
            content={"ok": True, "configured": True, "items": items},
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("POST /api/deye/inverter-socs — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
