"""Deye Cloud Open API v1 — token + station/inverter list (same auth flow as Java DeyeAuth)."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Optional

import httpx

from app import settings

_token: Optional[str] = None
_token_expires_at: float = 0.0
_lock = asyncio.Lock()


def deye_configured() -> bool:
    return bool(
        settings.DEYE_APP_ID
        and settings.DEYE_APP_SECRET
        and settings.DEYE_EMAIL
        and settings.DEYE_PASSWORD,
    )


def _sha256_hex(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


async def _ensure_token(client: httpx.AsyncClient) -> str:
    global _token, _token_expires_at
    async with _lock:
        now = time.time()
        if _token and now < _token_expires_at - 300:
            return _token
        if not deye_configured():
            raise RuntimeError("Deye API credentials not configured")

        url = f"{settings.DEYE_API_BASE_URL}/account/token"
        params = {"appId": settings.DEYE_APP_ID}
        body = {
            "appSecret": settings.DEYE_APP_SECRET,
            "email": settings.DEYE_EMAIL,
            "companyId": settings.DEYE_COMPANY_ID,
            "password": _sha256_hex(settings.DEYE_PASSWORD),
        }
        r = await client.post(
            url,
            params=params,
            json=body,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(str(data.get("msg") or "Deye token request failed"))

        access = data.get("accessToken")
        expires_in = int(data.get("expiresIn") or 0)
        if not access or expires_in <= 0:
            raise RuntimeError("Invalid Deye token response")

        _token = access
        _token_expires_at = now + expires_in
        return access


def _collect_station_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(inner, dict):
        return []
    raw = inner.get("stationList")
    if not isinstance(raw, list):
        raw = payload.get("stationList") or []
    return [x for x in raw if isinstance(x, dict)]


def _devices_from_station(st: dict[str, Any]) -> list[dict[str, Any]]:
    dl = st.get("deviceList") or st.get("devices") or []
    if not isinstance(dl, list):
        return []
    out: list[dict[str, Any]] = []
    for d in dl:
        if not isinstance(d, dict):
            continue
        sn = d.get("deviceSn") or d.get("deviceSN") or d.get("serialNumber")
        if not sn:
            continue
        dt = str(d.get("deviceType") or "").upper()
        # Request already filters INVERTER; keep rows with missing type.
        if dt and dt != "INVERTER":
            continue
        out.append(d)
    return out


def _station_label(st: dict[str, Any], device: dict[str, Any]) -> str:
    pname = str(
        st.get("stationName") or st.get("name") or st.get("title") or "",
    ).strip()
    dname = str(device.get("deviceName") or device.get("name") or "").strip()
    sn = str(device.get("deviceSn") or device.get("serialNumber") or "")
    if pname and dname:
        return f"{pname} — {dname}"
    if pname:
        return f"{pname} — {sn}" if sn else pname
    return dname or sn or "inverter"


async def list_inverter_devices() -> list[dict[str, str]]:
    """Inverters from POST /station/listWithDevice (plant list + device list, same data as cloud plant UI)."""
    if not deye_configured():
        return []

    base = settings.DEYE_API_BASE_URL
    async with httpx.AsyncClient(timeout=45.0) as client:
        token = await _ensure_token(client)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        items: list[dict[str, str]] = []
        seen: set[str] = set()
        page = 1
        page_size = 100

        while page <= 100:
            r = await client.post(
                f"{base}/station/listWithDevice",
                headers=headers,
                json={
                    "page": page,
                    "size": page_size,
                    "deviceType": "INVERTER",
                },
            )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("success") is False:
                raise RuntimeError(str(data.get("msg") or "Deye station list failed"))

            stations = _collect_station_list(data if isinstance(data, dict) else {})
            if not stations:
                break

            for st in stations:
                for dev in _devices_from_station(st):
                    sn = str(dev.get("deviceSn") or dev.get("serialNumber") or "")
                    if not sn or sn in seen:
                        continue
                    seen.add(sn)
                    items.append({"deviceSn": sn, "label": _station_label(st, dev)})

            if len(stations) < page_size:
                break
            page += 1

        items.sort(key=lambda x: x["label"].lower())
        return items
