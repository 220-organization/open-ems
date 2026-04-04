"""Expose Deye inverter list for the Power flow UI (server-side token; no secrets in browser)."""

import logging
from datetime import date as date_cls
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deye_api import (
    assert_deye_write_pin,
    assert_inverter_owned,
    charge_soc_delta_then_zero_export_ct,
    deye_configured,
    deye_missing_env_names,
    discharge_soc_delta_then_zero_export_ct,
    fetch_device_soc_percent,
    get_inverter_station_coordinates,
    get_live_metrics_cached,
    get_soc_map_cached,
    list_inverter_devices,
)
from app.deye_low_dam_charge_service import (
    get_charge_soc_delta_stored,
    get_low_dam_charge_pref,
    set_low_dam_charge_from_ui,
)
from app.deye_peak_auto_service import (
    get_discharge_soc_delta_stored,
    get_peak_auto_pref,
    set_peak_auto_from_ui,
)
from app.deye_roi_capex_service import get_roi_capex, get_roi_capex_map_for_devices, upsert_roi_capex
from app.deye_roi_service import (
    compute_roi_pv_kwh_and_value_uah,
    compute_roi_pv_kwh_and_value_uah_previous_kyiv_month,
)
from app.deye_soc_service import hourly_inverter_history_for_kyiv_day
from app.solar_forecast_open_meteo import fetch_tomorrow_insolation_percent

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/deye", tags=["deye"])

_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}

_MAX_INVERTER_SOCS = 200

DischargeSocDeltaPctOption = Literal[2, 10, 20]
ChargeSocDeltaPctOption = Literal[10, 20, 50, 100]


class InverterSocsBody(BaseModel):
    deviceSns: list[str] = Field(default_factory=list, max_length=_MAX_INVERTER_SOCS)


class Discharge2PctBody(BaseModel):
    """socDeltaPercent: optional; when omitted, uses stored per-device prefs (2, 10, or 20).

    respondAfterStart: return immediately after the inverter accepts the command; polling + restore run in background.
    """

    deviceSn: str = Field(..., min_length=6, max_length=64)
    socDeltaPercent: Optional[DischargeSocDeltaPctOption] = None
    respondAfterStart: bool = False
    pin: Optional[str] = Field(default=None, max_length=12)


class PeakAutoDischargeBody(BaseModel):
    deviceSn: str = Field(..., min_length=6, max_length=64)
    enabled: bool
    dischargeSocDeltaPct: DischargeSocDeltaPctOption = 2
    pin: Optional[str] = Field(default=None, max_length=12)


class Charge2PctBody(BaseModel):
    """socDeltaPercent: optional; when omitted, uses stored per-device prefs (default 10)."""

    deviceSn: str = Field(..., min_length=6, max_length=64)
    socDeltaPercent: Optional[ChargeSocDeltaPctOption] = None
    respondAfterStart: bool = False
    pin: Optional[str] = Field(default=None, max_length=12)


class LowDamChargeBody(BaseModel):
    deviceSn: str = Field(..., min_length=6, max_length=64)
    enabled: bool
    chargeSocDeltaPct: ChargeSocDeltaPctOption = 10
    pin: Optional[str] = Field(default=None, max_length=12)


class RoiSettingsBody(BaseModel):
    deviceSn: str = Field(..., min_length=6, max_length=64)
    capexUsd: float = Field(..., gt=0, le=1e12)
    pin: Optional[str] = Field(default=None, max_length=12)


@router.get("/inverters")
async def get_inverters(db: AsyncSession = Depends(get_db)):
    """
    Inverters under your Deye Cloud plants (Open API /station/listWithDevice).
    Requires DEYE_* env vars; returns empty list when not configured.

    Each item may include ``capexUsd`` when ROI CAPEX is stored in ``deye_roi_capex`` (for dropdown).
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
        sns = [str(it.get("deviceSn") or "").strip() for it in items if it.get("deviceSn")]
        try:
            capex_map = await get_roi_capex_map_for_devices(db, sns)
            for it in items:
                sn = str(it.get("deviceSn") or "").strip()
                if sn:
                    it["capexUsd"] = capex_map.get(sn)
        except Exception:
            logger.exception("GET /api/deye/inverters — CAPEX merge failed; returning without capexUsd")
            for it in items:
                it["capexUsd"] = None
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

    For configured balance-site serials (see app.deye_flow_balance), hourly grid is derived from stored
    load/PV/battery samples when all three exist: grid = load − 2×PV − battery (same as Power flow).
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
                "hourlyGridFrequencyHz": [None] * 24,
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        trade_day = date_cls.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD") from exc
    try:
        hourly_soc, hourly_grid_w, hourly_grid_hz = await hourly_inverter_history_for_kyiv_day(
            db, deviceSn, trade_day
        )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "deviceSn": deviceSn,
                "date": date,
                "hourlySocPercent": hourly_soc,
                "hourlyGridPowerW": hourly_grid_w,
                "hourlyGridFrequencyHz": hourly_grid_hz,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("GET /api/deye/soc-history-day — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/roi-stats")
async def get_roi_stats(
    deviceSn: str = Query(
        ...,
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial",
    ),
    startIso: str = Query(
        ...,
        min_length=8,
        max_length=64,
        description="ROI period start (ISO-8601, e.g. from Setup ROI statistics)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Consumption kWh from ``load_power_w`` (DB) and UAH = kWh × DAM at each consumption hour (Kyiv).

    ``totalPvKwh`` is PV generation (reference). ``totalConsumptionKwh`` and ``totalValueUah`` use load.
    ``dailyConsumptionKwh`` lists Kyiv-calendar days with per-day kWh and UAH (1-day aggregation).

    ``effectiveRateUahPerKwh`` is ``totalValueUah / totalConsumptionKwh`` (DAM-weighted by when load ran).

    ``previousMonth`` is the same for the previous calendar month (Europe/Kyiv), intersected with the ROI window.
    """
    if not deye_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "detail": "deye_not_configured",
            },
            headers=_NO_STORE_CACHE,
        )
    sn = deviceSn.strip()
    try:
        await assert_inverter_owned(sn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        data = await compute_roi_pv_kwh_and_value_uah(db, sn, startIso)
        previous_month = await compute_roi_pv_kwh_and_value_uah_previous_kyiv_month(db, sn, startIso)
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "deviceSn": sn,
                **data,
                "previousMonth": previous_month,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("GET /api/deye/roi-stats — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/roi-settings")
async def get_roi_settings(
    deviceSn: str = Query(
        ...,
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial",
    ),
    db: AsyncSession = Depends(get_db),
):
    """CAPEX (USD) and ROI period start from deye_roi_capex (Setup ROI statistics)."""
    if not deye_configured():
        return JSONResponse(
            content={"ok": False, "configured": False},
            headers=_NO_STORE_CACHE,
        )
    sn = deviceSn.strip()
    try:
        await assert_inverter_owned(sn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        row = await get_roi_capex(db, sn)
        if row is None:
            return JSONResponse(
                content={"ok": True, "configured": True, "hasRow": False},
                headers=_NO_STORE_CACHE,
            )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "hasRow": True,
                "capexUsd": row["capexUsd"],
                "periodStartIso": row["periodStartIso"],
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("GET /api/deye/roi-settings — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/roi-settings")
async def post_roi_settings(
    body: RoiSettingsBody,
    db: AsyncSession = Depends(get_db),
):
    """Save CAPEX and set ROI period start to now (same as previous localStorage behaviour)."""
    if not deye_configured():
        return JSONResponse(
            content={"ok": False, "configured": False},
            headers=_NO_STORE_CACHE,
        )
    sn = body.deviceSn.strip()
    try:
        await assert_inverter_owned(sn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await assert_deye_write_pin(sn, body.pin)
    try:
        period_start = await upsert_roi_capex(db, sn, body.capexUsd)
        await db.commit()
        iso = period_start.isoformat().replace("+00:00", "Z")
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "capexUsd": body.capexUsd,
                "periodStartIso": iso,
            },
            headers=_NO_STORE_CACHE,
        )
    except Exception as exc:
        logger.exception("POST /api/deye/roi-settings — failed: %s", exc)
        await db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/solar-insolation-tomorrow")
async def get_solar_insolation_tomorrow(
    deviceSn: str = Query(
        ...,
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial; coordinates resolved server-side from listWithDevice (not returned).",
    ),
) -> JSONResponse:
    """
    Tomorrow insolation index (0–100 %) from Open-Meteo for the plant/device location in Deye Cloud.

    GPS is never sent to the browser; only the percentage and optional local forecast date are returned.
    """
    if not deye_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "insolationPct": None},
            headers=_NO_STORE_CACHE,
        )
    sn = deviceSn.strip()
    try:
        await assert_inverter_owned(sn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    lat, lon = await get_inverter_station_coordinates(sn)
    if lat is None or lon is None:
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "insolationPct": None,
                "detail": "no_station_coordinates",
            },
            headers=_NO_STORE_CACHE,
        )
    pct, day = await fetch_tomorrow_insolation_percent(lat, lon)
    if pct is None:
        return JSONResponse(
            content={
                "ok": False,
                "configured": True,
                "insolationPct": None,
                "detail": "forecast_unavailable",
            },
            headers=_NO_STORE_CACHE,
        )
    return JSONResponse(
        content={"ok": True, "configured": True, "insolationPct": pct, "date": day},
        headers=_NO_STORE_CACHE,
    )


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
                "gridFrequencyHz": None,
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        bat, load_w, pv_w, grid_w, grid_hz = await get_live_metrics_cached(deviceSn)
        logger.info(
            "GET /api/deye/ess-power — sn=%s batteryW=%s loadW=%s pvW=%s gridW=%s gridHz=%s",
            deviceSn,
            bat,
            load_w,
            pv_w,
            grid_w,
            grid_hz,
        )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "batteryPowerW": bat,
                "loadPowerW": load_w,
                "pvPowerW": pv_w,
                "gridPowerW": grid_w,
                "gridFrequencyHz": grid_hz,
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


@router.get("/peak-auto-discharge")
async def get_peak_auto_discharge(
    deviceSn: str = Query(
        ...,
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial",
    ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Per-device preference: backend auto discharge at Kyiv hour of today’s DAM price peak (DB)."""
    if not deye_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "enabled": False,
                "dischargeSocDeltaPct": 2,
            },
            headers=_NO_STORE_CACHE,
        )
    en, pct = await get_peak_auto_pref(db, deviceSn.strip())
    return JSONResponse(
        content={
            "ok": True,
            "configured": True,
            "deviceSn": deviceSn.strip(),
            "enabled": en,
            "dischargeSocDeltaPct": pct,
        },
        headers=_NO_STORE_CACHE,
    )


@router.post("/peak-auto-discharge")
async def post_peak_auto_discharge(
    body: PeakAutoDischargeBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upsert preference; enabling checks device is in listWithDevice for this account."""
    if not deye_configured():
        missing = deye_missing_env_names()
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "enabled": False,
                "detail": "DEYE_* not set"
                + (f" (missing: {', '.join(missing)})" if missing else ""),
            },
            headers=_NO_STORE_CACHE,
        )
    sn = body.deviceSn.strip()
    try:
        await assert_deye_write_pin(sn, body.pin)
        await set_peak_auto_from_ui(db, sn, body.enabled, body.dischargeSocDeltaPct)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("POST /api/deye/peak-auto-discharge — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return JSONResponse(
        content={
            "ok": True,
            "configured": True,
            "deviceSn": sn,
            "enabled": body.enabled,
            "dischargeSocDeltaPct": body.dischargeSocDeltaPct,
        },
        headers=_NO_STORE_CACHE,
    )


@router.post("/discharge-2pct")
async def post_discharge_2pct(
    body: Discharge2PctBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Set Deye strategy to SELLING_FIRST, wait until SoC drops by socDeltaPercent (2, 10, or 20) or timeout,
    then ZERO_EXPORT_TO_CT. If socDeltaPercent is omitted, uses stored per-device prefs (default 2).
    Overwrites device TOU template per Deye /strategy/dynamicControl (see Deye sample scripts).
    Long-running: ensure reverse-proxy read timeout > DEYE_DISCHARGE_SOC_TIMEOUT_SEC.
    """
    if not deye_configured():
        missing = deye_missing_env_names()
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "detail": "DEYE_* not set"
                + (f" (missing: {', '.join(missing)})" if missing else ""),
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        sn = body.deviceSn.strip()
        await assert_deye_write_pin(sn, body.pin)
        delta = body.socDeltaPercent
        if delta is None:
            delta = await get_discharge_soc_delta_stored(db, sn)
        result = await discharge_soc_delta_then_zero_export_ct(
            sn, float(delta), return_after_start=body.respondAfterStart
        )
        return JSONResponse(
            content={"ok": True, "configured": True, **result},
            headers=_NO_STORE_CACHE,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("POST /api/deye/discharge-2pct — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/low-dam-charge")
async def get_low_dam_charge(
    deviceSn: str = Query(
        ...,
        min_length=6,
        max_length=32,
        pattern=r"^[0-9]+$",
        description="Deye inverter serial",
    ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Per-device preference: auto charge at Kyiv hour of today's minimum DAM price (DB)."""
    if not deye_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "enabled": False,
                "chargeSocDeltaPct": 10,
            },
            headers=_NO_STORE_CACHE,
        )
    en, pct = await get_low_dam_charge_pref(db, deviceSn.strip())
    return JSONResponse(
        content={
            "ok": True,
            "configured": True,
            "deviceSn": deviceSn.strip(),
            "enabled": en,
            "chargeSocDeltaPct": pct,
        },
        headers=_NO_STORE_CACHE,
    )


@router.post("/low-dam-charge")
async def post_low_dam_charge(
    body: LowDamChargeBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upsert low-DAM auto charge preference."""
    if not deye_configured():
        missing = deye_missing_env_names()
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "enabled": False,
                "detail": "DEYE_* not set"
                + (f" (missing: {', '.join(missing)})" if missing else ""),
            },
            headers=_NO_STORE_CACHE,
        )
    sn = body.deviceSn.strip()
    try:
        await assert_deye_write_pin(sn, body.pin)
        await set_low_dam_charge_from_ui(db, sn, body.enabled, body.chargeSocDeltaPct)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("POST /api/deye/low-dam-charge — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return JSONResponse(
        content={
            "ok": True,
            "configured": True,
            "deviceSn": sn,
            "enabled": body.enabled,
            "chargeSocDeltaPct": body.chargeSocDeltaPct,
        },
        headers=_NO_STORE_CACHE,
    )


@router.post("/charge-2pct")
async def post_charge_2pct(
    body: Charge2PctBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Charge battery toward higher SoC via dynamicControl (same long-running semantics as discharge).
    socDeltaPercent: 10, 20, 50, or 100 — optional; uses stored per-device prefs when omitted.
    """
    if not deye_configured():
        missing = deye_missing_env_names()
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "detail": "DEYE_* not set"
                + (f" (missing: {', '.join(missing)})" if missing else ""),
            },
            headers=_NO_STORE_CACHE,
        )
    try:
        sn = body.deviceSn.strip()
        await assert_deye_write_pin(sn, body.pin)
        delta = body.socDeltaPercent
        if delta is None:
            delta = await get_charge_soc_delta_stored(db, sn)
        result = await charge_soc_delta_then_zero_export_ct(
            sn, float(delta), return_after_start=body.respondAfterStart
        )
        return JSONResponse(
            content={"ok": True, "configured": True, **result},
            headers=_NO_STORE_CACHE,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("POST /api/deye/charge-2pct — failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
