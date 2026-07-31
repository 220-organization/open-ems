"""GridLab External BESS API — devices, live power-flow, meters, history (no secrets in browser)."""

from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.db import get_db
from app.gridlab_api import (
    GridLabApiError,
    GridLabAuthError,
    GridLabUpstreamHttpError,
    get_meters,
    get_status,
    gridlab_configured,
    gridlab_missing_env_names,
)
from app.gridlab_history_service import sync_all_history
from app.gridlab_power_service import (
    build_live_power_flow,
    hourly_device_history_for_kyiv_day,
    run_gridlab_power_snapshot,
    select_site_meters,
)
from app.models import GridLabHourlyFlow, GridLabHourlyMeter, GridLabHourlySoc

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/gridlab", tags=["gridlab"])

_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


class HistorySyncBody(BaseModel):
    dateFrom: str = Field(..., min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")
    dateTo: str = Field(..., min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")


def _log_gridlab_route_error(context: str, exc: BaseException) -> None:
    if isinstance(exc, GridLabAuthError):
        logger.warning("%s — GridLab auth failed: %s", context, exc)
        return
    if isinstance(exc, GridLabApiError):
        logger.warning("%s — GridLab API error: %s", context, exc)
        return
    if isinstance(exc, GridLabUpstreamHttpError):
        logger.warning("%s — GridLab upstream HTTP: %s", context, exc)
        return
    if isinstance(exc, httpx.RequestError):
        logger.warning("%s — GridLab request error: %s", context, exc)
        return
    logger.exception("%s — failed: %s", context, exc)


@router.get("/devices")
async def get_devices_route():
    if not gridlab_configured():
        missing = gridlab_missing_env_names()
        logger.warning(
            "GET /api/gridlab/devices — not configured (missing: %s)",
            ", ".join(missing) if missing else "GRIDLAB_*",
        )
        return JSONResponse(
            content={"configured": False, "items": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        status = await get_status(use_cache=True)
        item = {
            "deviceId": int(status.get("device_id") or settings.GRIDLAB_DEVICE_ID),
            "name": str(status.get("name") or "").strip() or f"GridLab BESS {settings.GRIDLAB_DEVICE_ID}",
            "socPercent": status.get("soc_percent"),
            "isOnline": status.get("is_online"),
            "powerKw": status.get("power_kw"),
            "stale": bool(status.get("stale")),
            "dataAgeSeconds": status.get("data_age_seconds"),
        }
        logger.info("GET /api/gridlab/devices — OK, device %s", item["deviceId"])
        return JSONResponse(
            content={"configured": True, "items": [item]},
            headers=_NO_STORE_CACHE,
        )
    except GridLabAuthError as exc:
        logger.warning("GET /api/gridlab/devices — login failed (graceful empty list)")
        return JSONResponse(
            content={
                "configured": True,
                "items": [],
                "gridlabAuthFailed": True,
                "reason": "login_failed",
                "detail": str(exc)[:400],
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_gridlab_route_error("GET /api/gridlab/devices", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/soc")
async def get_soc_route(
    deviceId: int = Query(
        ...,
        ge=1,
        description="GridLab device id (from GET /api/gridlab/devices)",
    ),
):
    """Live SoC percent for SOC dynamic pricing (same contract shape as GET /api/deye/soc)."""
    if not gridlab_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "socPercent": None},
            headers=_NO_STORE_CACHE,
        )
    if int(deviceId) != int(settings.GRIDLAB_DEVICE_ID):
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "device_not_allowed",
                "deviceId": deviceId,
                "socPercent": None,
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        status = await get_status(use_cache=True)
        soc_raw = status.get("soc_percent")
        soc_percent = None
        if soc_raw is not None:
            try:
                soc_f = float(soc_raw)
                if 0.0 <= soc_f <= 100.0:
                    soc_percent = int(round(soc_f))
            except (TypeError, ValueError):
                soc_percent = None
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "deviceId": int(status.get("device_id") or settings.GRIDLAB_DEVICE_ID),
                "socPercent": soc_percent,
                "stale": bool(status.get("stale")),
                "dataAgeSeconds": status.get("data_age_seconds"),
            },
            headers=_NO_STORE_CACHE,
        )
    except GridLabAuthError as exc:
        _log_gridlab_route_error("GET /api/gridlab/soc", exc)
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "gridlab_login_failed",
                "detail": str(exc)[:400],
                "deviceId": deviceId,
                "socPercent": None,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_gridlab_route_error("GET /api/gridlab/soc", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/solar-insolation")
async def get_solar_insolation_route(
    lat: float = Query(..., ge=-90, le=90, description="EV port latitude (WGS84)"),
    lon: float = Query(..., ge=-180, le=180, description="EV port longitude (WGS84)"),
):
    """
    Today + tomorrow insolation (0–100 %) from Open-Meteo for the given coordinates.

    GridLab has no plant GPS in the upstream API, so the driver app passes the EV port
    latitude/longitude (already public on the station map).
    """
    from app.solar_forecast_open_meteo import fetch_today_tomorrow_insolation_forecast

    if not gridlab_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "today": None, "tomorrow": None},
            headers=_NO_STORE_CACHE,
        )
    payload = await fetch_today_tomorrow_insolation_forecast(float(lat), float(lon))
    if payload is None:
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "today": None,
                "tomorrow": None,
                "detail": "forecast_unavailable",
            },
            headers=_NO_STORE_CACHE,
        )
    return JSONResponse(
        content={"ok": True, "configured": True, **payload},
        headers=_NO_STORE_CACHE,
    )


@router.get("/power-flow")
async def get_power_flow_route(
    deviceId: int = Query(
        ...,
        ge=1,
        description="GridLab device id (from GET /api/gridlab/devices)",
    ),
):
    if not gridlab_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    if int(deviceId) != int(settings.GRIDLAB_DEVICE_ID):
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "device_not_allowed",
                "deviceId": deviceId,
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        body = await build_live_power_flow(use_cache=True)
        return JSONResponse(content=body, headers=_NO_STORE_CACHE)
    except GridLabAuthError as exc:
        _log_gridlab_route_error("GET /api/gridlab/power-flow", exc)
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "gridlab_login_failed",
                "detail": str(exc)[:400],
                "deviceId": deviceId,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_gridlab_route_error("GET /api/gridlab/power-flow", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/meters")
async def get_meters_route():
    if not gridlab_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured", "meters": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        payload = await get_meters(use_cache=True)
        meters_list = payload.get("meters") if isinstance(payload, dict) else []
        if not isinstance(meters_list, list):
            meters_list = []
        selected = select_site_meters(meters_list)
        items = []
        for m in meters_list:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            try:
                meter_id = int(mid)
            except (TypeError, ValueError):
                continue
            role_key = None
            sel = selected["selectedIds"]
            if sel.get("pcc") == meter_id:
                role_key = "pcc"
            elif sel.get("pv") == meter_id:
                role_key = "pv"
            elif sel.get("load") == meter_id:
                role_key = "load"
            elif meter_id in (sel.get("ev") or []):
                role_key = "ev"
            items.append(
                {
                    "id": meter_id,
                    "name": m.get("name"),
                    "role": m.get("role"),
                    "isVirtual": bool(m.get("is_virtual")),
                    "powerKw": m.get("power_kw"),
                    "kwhImport": m.get("kwh_import"),
                    "kwhExport": m.get("kwh_export"),
                    "stale": bool(m.get("stale")),
                    "dataAgeSeconds": m.get("data_age_seconds"),
                    "timestamp": m.get("timestamp"),
                    "selectedAs": role_key,
                }
            )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "deviceId": int(payload.get("device_id") or settings.GRIDLAB_DEVICE_ID)
                if isinstance(payload, dict)
                else settings.GRIDLAB_DEVICE_ID,
                "generatedAt": payload.get("generated_at") if isinstance(payload, dict) else None,
                "selectedMeterIds": selected["selectedIds"],
                "meters": items,
            },
            headers=_NO_STORE_CACHE,
        )
    except GridLabAuthError as exc:
        _log_gridlab_route_error("GET /api/gridlab/meters", exc)
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "reason": "gridlab_login_failed",
                "detail": str(exc)[:400],
                "meters": [],
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        _log_gridlab_route_error("GET /api/gridlab/meters", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/soc-history-day")
async def get_soc_history_day_route(
    deviceId: int = Query(..., ge=1, description="GridLab device id"),
    date: str = Query(
        ...,
        min_length=10,
        max_length=10,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Calendar day YYYY-MM-DD (Europe/Kyiv boundaries)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Mean SoC / grid / PV / load per Kyiv hour from gridlab_power_sample (5-min buckets)."""
    if not gridlab_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "deviceId": deviceId,
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
            await hourly_device_history_for_kyiv_day(db, int(deviceId), trade_day)
        )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "deviceId": deviceId,
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
        logger.exception("GET /api/gridlab/soc-history-day — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/history/soc")
async def get_history_soc_route(
    date_from: str = Query(..., min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(None, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
):
    if not gridlab_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "hours": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        d_from = date_cls.fromisoformat(date_from)
        d_to = date_cls.fromisoformat(date_to) if date_to else d_from
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date") from exc
    device_id = int(settings.GRIDLAB_DEVICE_ID)
    result = await db.execute(
        select(GridLabHourlySoc)
        .where(
            GridLabHourlySoc.device_id == device_id,
            GridLabHourlySoc.target_date >= d_from,
            GridLabHourlySoc.target_date <= d_to,
        )
        .order_by(GridLabHourlySoc.target_date, GridLabHourlySoc.hour)
    )
    rows = list(result.scalars().all())
    if not rows:
        # Lazy pull from upstream when DB empty for this range.
        try:
            await sync_all_history(db, d_from, d_to, device_id=device_id)
            result = await db.execute(
                select(GridLabHourlySoc)
                .where(
                    GridLabHourlySoc.device_id == device_id,
                    GridLabHourlySoc.target_date >= d_from,
                    GridLabHourlySoc.target_date <= d_to,
                )
                .order_by(GridLabHourlySoc.target_date, GridLabHourlySoc.hour)
            )
            rows = list(result.scalars().all())
        except Exception:
            logger.exception("GET /api/gridlab/history/soc — lazy sync failed")
    hours = [
        {
            "targetDate": r.target_date.isoformat(),
            "hour": int(r.hour),
            "socPercent": r.soc_percent,
            "timestamp": r.sample_ts.isoformat() if r.sample_ts else None,
        }
        for r in rows
    ]
    return JSONResponse(
        content={
            "ok": True,
            "configured": True,
            "deviceId": device_id,
            "dateFrom": d_from.isoformat(),
            "dateTo": d_to.isoformat(),
            "hours": hours,
        },
        headers=_NO_STORE_CACHE,
    )


@router.get("/history/meter/{meter_id}")
async def get_history_meter_route(
    meter_id: int,
    date_from: str = Query(..., min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(None, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
):
    if not gridlab_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "hours": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        d_from = date_cls.fromisoformat(date_from)
        d_to = date_cls.fromisoformat(date_to) if date_to else d_from
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date") from exc
    device_id = int(settings.GRIDLAB_DEVICE_ID)
    result = await db.execute(
        select(GridLabHourlyMeter)
        .where(
            GridLabHourlyMeter.device_id == device_id,
            GridLabHourlyMeter.meter_id == int(meter_id),
            GridLabHourlyMeter.target_date >= d_from,
            GridLabHourlyMeter.target_date <= d_to,
        )
        .order_by(GridLabHourlyMeter.target_date, GridLabHourlyMeter.hour)
    )
    rows = list(result.scalars().all())
    if not rows:
        try:
            from app.gridlab_history_service import sync_meter_history

            await sync_meter_history(db, d_from, d_to, device_id=device_id, meter_ids=[int(meter_id)])
            await db.commit()
            result = await db.execute(
                select(GridLabHourlyMeter)
                .where(
                    GridLabHourlyMeter.device_id == device_id,
                    GridLabHourlyMeter.meter_id == int(meter_id),
                    GridLabHourlyMeter.target_date >= d_from,
                    GridLabHourlyMeter.target_date <= d_to,
                )
                .order_by(GridLabHourlyMeter.target_date, GridLabHourlyMeter.hour)
            )
            rows = list(result.scalars().all())
        except Exception:
            logger.exception("GET /api/gridlab/history/meter — lazy sync failed")
    hours = [
        {
            "targetDate": r.target_date.isoformat(),
            "hour": int(r.hour),
            "energyImportKwh": r.energy_import_kwh,
            "energyExportKwh": r.energy_export_kwh,
            "avgPowerKw": r.avg_power_kw,
            "samples": r.samples,
        }
        for r in rows
    ]
    return JSONResponse(
        content={
            "ok": True,
            "configured": True,
            "deviceId": device_id,
            "meterId": int(meter_id),
            "dateFrom": d_from.isoformat(),
            "dateTo": d_to.isoformat(),
            "hours": hours,
        },
        headers=_NO_STORE_CACHE,
    )


@router.get("/history/flows")
async def get_history_flows_route(
    date_from: str = Query(..., min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(None, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
):
    if not gridlab_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "hours": []},
            headers=_NO_STORE_CACHE,
        )
    try:
        d_from = date_cls.fromisoformat(date_from)
        d_to = date_cls.fromisoformat(date_to) if date_to else d_from
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date") from exc
    device_id = int(settings.GRIDLAB_DEVICE_ID)
    result = await db.execute(
        select(GridLabHourlyFlow)
        .where(
            GridLabHourlyFlow.device_id == device_id,
            GridLabHourlyFlow.target_date >= d_from,
            GridLabHourlyFlow.target_date <= d_to,
        )
        .order_by(GridLabHourlyFlow.target_date, GridLabHourlyFlow.hour)
    )
    rows = list(result.scalars().all())
    if not rows:
        try:
            from app.gridlab_history_service import sync_flows_history

            await sync_flows_history(db, d_from, d_to, device_id=device_id)
            await db.commit()
            result = await db.execute(
                select(GridLabHourlyFlow)
                .where(
                    GridLabHourlyFlow.device_id == device_id,
                    GridLabHourlyFlow.target_date >= d_from,
                    GridLabHourlyFlow.target_date <= d_to,
                )
                .order_by(GridLabHourlyFlow.target_date, GridLabHourlyFlow.hour)
            )
            rows = list(result.scalars().all())
        except Exception:
            logger.exception("GET /api/gridlab/history/flows — lazy sync failed")
    hours = [
        {
            "targetDate": r.target_date.isoformat(),
            "hour": int(r.hour),
            "pvTotal": r.pv_total,
            "pvToBess": r.pv_to_bess,
            "pvToGrid": r.pv_to_grid,
            "gridToBess": r.grid_to_bess,
            "bessToGrid": r.bess_to_grid,
            "bessToLoad": r.bess_to_load,
            "gridToLoad": r.grid_to_load,
            "load": r.load,
            "losses": r.losses,
            "fiscalGridImport": r.fiscal_grid_import,
            "fiscalGridExport": r.fiscal_grid_export,
        }
        for r in rows
    ]
    return JSONResponse(
        content={
            "ok": True,
            "configured": True,
            "deviceId": device_id,
            "dateFrom": d_from.isoformat(),
            "dateTo": d_to.isoformat(),
            "hours": hours,
        },
        headers=_NO_STORE_CACHE,
    )


@router.post("/history/sync")
async def post_history_sync_route(body: HistorySyncBody, db: AsyncSession = Depends(get_db)):
    """Manual backfill of hourly SoC / meter / flows for a date range."""
    if not gridlab_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        d_from = date_cls.fromisoformat(body.dateFrom)
        d_to = date_cls.fromisoformat(body.dateTo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date") from exc
    if d_to < d_from:
        raise HTTPException(status_code=400, detail="dateTo must be >= dateFrom")
    try:
        counts = await sync_all_history(db, d_from, d_to)
        return JSONResponse(
            content={"ok": True, "configured": True, **counts},
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("POST /api/gridlab/history/sync — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/power-snapshot")
async def post_power_snapshot_route(db: AsyncSession = Depends(get_db)):
    """Manual trigger: fetch live GridLab metrics and upsert current 5-min bucket."""
    if not gridlab_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "reason": "not_configured"},
            headers=_NO_STORE_CACHE,
        )
    try:
        n = await run_gridlab_power_snapshot(db)
        await db.commit()
        return JSONResponse(
            content={"ok": True, "configured": True, "rowsUpserted": n},
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("POST /api/gridlab/power-snapshot — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
