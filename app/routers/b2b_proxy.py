"""Proxy 220-km.com public B2B REST endpoints (avoids browser CORS when using the power-flow page)."""

import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.settings import B2B_API_BASE_URL, EV_PORT_DEVICE_CLIENT_UI_ID

logger = logging.getLogger(__name__)

# Public device API (same host as B2B in production): nearest stations + job payload.
_DEVICE_NEAREST_PATH = "/api/device/v2/station/nearest"
_DEVICE_STATION_STATUS_PATH = "/api/device/v2/station/status"

router = APIRouter(prefix="/api/b2b", tags=["b2b-proxy"])

# Avoid stale dashboards: browsers may cache GET; power-flow polls these every few seconds.
_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}

# GET /b2b/public/day-kwh is IP rate-limited upstream; cache aggressively (process-local).
_DAY_KWH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DAY_KWH_TTL_SEC = 6 * 3600
_CHARGING_AVG_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CHARGING_AVG_TTL_SEC = 3600


async def _proxy_get(path: str, params: Optional[dict[str, str]] = None) -> Any:
    url = f"{B2B_API_BASE_URL}{path}"
    q = f" params={params}" if params else ""
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.get(url, params=params or {})
    except httpx.RequestError as exc:
        logger.warning("B2B proxy GET %s%s — transport error: %s", path, q, exc)
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc}") from exc
    if response.status_code >= 400:
        logger.warning(
            "B2B proxy GET %s%s — upstream HTTP %s",
            path,
            q,
            response.status_code,
        )
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text[:2000] if response.text else "Upstream error",
        )
    logger.debug("B2B proxy GET %s%s — OK %s", path, q, response.status_code)
    return response.json()


async def _fetch_day_kwh_json(iso_date: str) -> Optional[dict[str, Any]]:
    """GET /b2b/public/day-kwh?date=YYYY-MM-DD (UTC calendar day). Returns None on transport/HTTP errors."""
    now = time.monotonic()
    cached = _DAY_KWH_CACHE.get(iso_date)
    if cached is not None and now - cached[0] < _DAY_KWH_TTL_SEC:
        return cached[1]
    url = f"{B2B_API_BASE_URL}/b2b/public/day-kwh"
    params = {"date": iso_date}
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.get(url, params=params)
    except httpx.RequestError as exc:
        logger.warning("B2B day-kwh GET date=%s — transport error: %s", iso_date, exc)
        return None
    if response.status_code != 200:
        logger.warning(
            "B2B day-kwh GET date=%s — HTTP %s",
            iso_date,
            response.status_code,
        )
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    _DAY_KWH_CACHE[iso_date] = (now, data)
    return data


def _volume_weighted_tariff_uah_per_kwh(day_payload: dict[str, Any]) -> tuple[float, float]:
    """
    Returns (sum tariff*kWh, sum kWh) for 220 network hours with positive energy and finite tariff.
    """
    kwhs = day_payload.get("hourlyKwh220")
    tariffs = day_payload.get("hourlyTariff220")
    if not isinstance(kwhs, list) or not isinstance(tariffs, list):
        return (0.0, 0.0)
    n = min(len(kwhs), len(tariffs), 24)
    wsum = 0.0
    ksum = 0.0
    for i in range(n):
        try:
            k = float(kwhs[i] or 0.0)
        except (TypeError, ValueError):
            continue
        if k <= 1e-12:
            continue
        tf = tariffs[i]
        if tf is None:
            continue
        try:
            tv = float(tf)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(tv):
            continue
        wsum += k * tv
        ksum += k
    return (wsum, ksum)


@router.get("/charging-network-tariff-avg")
async def charging_network_tariff_avg(
    days: int = Query(default=7, ge=1, le=14, description="Completed UTC calendar days to include (excluding today)"),
) -> JSONResponse:
    """
    Volume-weighted average 220-km charging tariff (UAH/kWh) from public day-kwh hourly series.
    Cached server-side to stay under upstream day-kwh rate limits.
    """
    cache_key = str(days)
    now = time.monotonic()
    hit = _CHARGING_AVG_CACHE.get(cache_key)
    if hit is not None and now - hit[0] < _CHARGING_AVG_TTL_SEC:
        return JSONResponse(content=hit[1], headers=_NO_STORE_CACHE)

    today_utc = datetime.now(timezone.utc).date()
    total_w = 0.0
    total_k = 0.0
    days_with_energy = 0
    for i in range(1, days + 1):
        d = today_utc - timedelta(days=i)
        iso = d.isoformat()
        payload = await _fetch_day_kwh_json(iso)
        if not payload:
            continue
        w, k = _volume_weighted_tariff_uah_per_kwh(payload)
        if k > 1e-12:
            total_w += w
            total_k += k
            days_with_energy += 1

    if total_k <= 1e-12:
        body: dict[str, Any] = {
            "ok": False,
            "avgUahPerKwh": None,
            "daysRequested": days,
            "daysWithEnergy": days_with_energy,
        }
    else:
        body = {
            "ok": True,
            "avgUahPerKwh": total_w / total_k,
            "daysRequested": days,
            "daysWithEnergy": days_with_energy,
        }
    _CHARGING_AVG_CACHE[cache_key] = (now, body)
    return JSONResponse(content=body, headers=_NO_STORE_CACHE)


@router.get("/realtime-power")
async def realtime_power(
    station: Optional[str] = Query(default=None, description="Optional station number, e.g. 655"),
) -> Any:
    """Proxies GET /b2b/public/realtime-power — aggregate charging power (MW)."""
    params = {}
    if station is not None and station != "":
        params["station"] = station
    data = await _proxy_get("/b2b/public/realtime-power", params if params else None)
    return JSONResponse(content=data, headers=_NO_STORE_CACHE)


@router.get("/miner-power")
async def miner_power() -> Any:
    """Proxies GET /b2b/public/miner-power — Binance Pool miner snapshot when configured."""
    data = await _proxy_get("/b2b/public/miner-power")
    return JSONResponse(content=data, headers=_NO_STORE_CACHE)


def _job_is_in_progress(job: Any) -> bool:
    if not isinstance(job, dict):
        return False
    state = job.get("state")
    if state is None:
        return False
    return str(state).strip().upper().replace("-", "_") == "IN_PROGRESS"


@router.get("/charging-ports")
async def charging_ports(
    lat: float = Query(default=50.4501, description="Origin latitude (e.g. user or Kyiv default)"),
    lon: float = Query(default=30.5234, description="Origin longitude"),
    distance_m: int = Query(default=2_000_000, ge=1, le=20_000_000, description="Search radius, meters"),
    top: int = Query(default=500, ge=1, le=2000, description="Max stations from upstream nearest API"),
) -> JSONResponse:
    """
    Stations with an active charging job (job present, state IN_PROGRESS) for Power flow port filter.
    Upstream: GET /api/device/v2/station/nearest (same base URL as B2B).
    Each item includes ``costPerKwt`` (kopecks/kWh) when the upstream Station payload has it, for session tariff UI.
    """
    url = f"{B2B_API_BASE_URL}{_DEVICE_NEAREST_PATH}"
    params = {
        "lat": str(lat),
        "lon": str(lon),
        "distance_m": str(distance_m),
        "top": str(top),
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
    except httpx.RequestError as exc:
        logger.warning("Device nearest GET — transport error: %s", exc)
        return JSONResponse(
            content={"ok": False, "items": [], "detail": str(exc)},
            headers=_NO_STORE_CACHE,
        )
    if response.status_code >= 400:
        logger.warning(
            "Device nearest GET — HTTP %s %s",
            response.status_code,
            (response.text or "")[:300],
        )
        return JSONResponse(
            content={
                "ok": False,
                "items": [],
                "detail": response.text[:500] if response.text else "Upstream error",
            },
            headers=_NO_STORE_CACHE,
        )
    raw = response.json()
    if not isinstance(raw, list):
        return JSONResponse(content={"ok": True, "items": []}, headers=_NO_STORE_CACHE)

    items_out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        job = row.get("job")
        if job is None or not _job_is_in_progress(job):
            continue
        num = row.get("number")
        if num is None:
            continue
        key = str(num).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        name = row.get("name")
        cost_pk = row.get("costPerKwt")
        try:
            cost_per_kwt = int(cost_pk) if cost_pk is not None else None
        except (TypeError, ValueError):
            cost_per_kwt = None
        items_out.append(
            {
                "number": key,
                "label": (str(name).strip() if name is not None else "") or key,
                "distanceMeters": row.get("distanceMeters"),
                "powerWt": job.get("powerWt") if isinstance(job, dict) else None,
                "maxPowerWt": row.get("maxPowerWt"),
                # Station list tariff (kopecks/kWh); UAH/kWh = costPerKwt/100 — same as ChargingPage.
                "costPerKwt": cost_per_kwt,
            }
        )

    def _dist_key(it: dict[str, Any]) -> tuple[bool, float]:
        d = it.get("distanceMeters")
        if d is None:
            return (True, 0.0)
        try:
            return (False, float(d))
        except (TypeError, ValueError):
            return (True, 0.0)

    items_out.sort(key=_dist_key)

    return JSONResponse(content={"ok": True, "items": items_out}, headers=_NO_STORE_CACHE)


@router.get("/station-status")
async def station_status(
    station_number: str = Query(
        ...,
        min_length=1,
        max_length=32,
        description="Charging station number, e.g. 738",
    ),
    client_ui_id: Optional[str] = Query(
        default=None,
        alias="clientUiId",
        description="Public device client id (defaults from EV_PORT_DEVICE_CLIENT_UI_ID)",
    ),
) -> JSONResponse:
    """Proxies GET /api/device/v2/station/status — job powerWt for the EV port dropdown / power-flow node."""
    cid = (client_ui_id or "").strip() or EV_PORT_DEVICE_CLIENT_UI_ID
    params = {"station_number": station_number.strip(), "clientUiId": cid}
    data = await _proxy_get(_DEVICE_STATION_STATUS_PATH, params)
    return JSONResponse(content=data, headers=_NO_STORE_CACHE)
