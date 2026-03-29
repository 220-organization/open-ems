"""Proxy 220-km.com public B2B REST endpoints (avoids browser CORS when using the power-flow page)."""

import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.settings import B2B_API_BASE_URL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/b2b", tags=["b2b-proxy"])


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
    return await _proxy_get("/b2b/public/realtime-power", params if params else None)


@router.get("/miner-power")
async def miner_power() -> Any:
    """Proxies GET /b2b/public/miner-power — Binance Pool miner snapshot when configured."""
    return await _proxy_get("/b2b/public/miner-power")
