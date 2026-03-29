"""Expose Deye inverter list for the Power flow UI (server-side token; no secrets in browser)."""

from fastapi import APIRouter, HTTPException

from app.deye_api import deye_configured, list_inverter_devices

router = APIRouter(prefix="/api/deye", tags=["deye"])


@router.get("/inverters")
async def get_inverters() -> dict:
    """
    Inverters under your Deye Cloud plants (Open API /station/listWithDevice).
    Requires DEYE_* env vars; returns empty list when not configured.
    """
    if not deye_configured():
        return {"configured": False, "items": []}
    try:
        items = await list_inverter_devices()
        return {"configured": True, "items": items}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
