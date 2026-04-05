"""Proxy 220-km.com public B2B REST endpoints (avoids browser CORS when using the power-flow page)."""

import logging
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
        items_out.append(
            {
                "number": key,
                "label": (str(name).strip() if name is not None else "") or key,
                "distanceMeters": row.get("distanceMeters"),
                "powerWt": job.get("powerWt") if isinstance(job, dict) else None,
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
