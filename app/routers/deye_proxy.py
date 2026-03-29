"""Expose Deye inverter list for the Power flow UI (server-side token; no secrets in browser)."""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.deye_api import deye_configured, deye_missing_env_names, list_inverter_devices

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deye", tags=["deye"])

_NO_STORE_CACHE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


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
