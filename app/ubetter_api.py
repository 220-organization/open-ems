"""Ubetter EMS Open API — token auth, device list, realtime summary (read-only)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from app import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_session_lock = asyncio.Lock()
_access_token: Optional[str] = None
_tenant_id: Optional[str] = None
_token_expires_at: float = 0.0

_device_list_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
_power_flow_cache: dict[str, tuple[dict[str, Any], float]] = {}

_CODE_SUCCESS = 0
_CODE_TOKEN_INVALID = 40101


class UbetterAuthError(RuntimeError):
    """Login failed or token could not be obtained."""


class UbetterApiError(RuntimeError):
    """EMS Open API returned a non-zero business code."""

    __slots__ = ("code", "message", "path")

    def __init__(self, path: str, code: Any, message: str):
        self.path = path
        self.code = code
        self.message = message
        super().__init__(f"Ubetter {path} code={code} message={message}")


class UbetterUpstreamHttpError(RuntimeError):
    """Non-success HTTP before JSON body."""

    __slots__ = ("endpoint", "http_status", "body_snippet")

    def __init__(self, endpoint: str, http_status: int, body_snippet: str):
        self.endpoint = endpoint
        self.http_status = http_status
        self.body_snippet = body_snippet
        tail = (body_snippet or "").strip()
        if len(tail) > 220:
            tail = tail[:220] + "…"
        msg = f"Ubetter HTTP {http_status} ({endpoint})"
        if tail:
            msg = f"{msg}: {tail}"
        super().__init__(msg)


def ubetter_missing_env_names() -> list[str]:
    missing: list[str] = []
    if not settings.UBETTER_ENABLED:
        missing.append("UBETTER_ENABLED")
    if not settings.UBETTER_USERNAME:
        missing.append("UBETTER_USERNAME")
    if not settings.UBETTER_PASSWORD:
        missing.append("UBETTER_PASSWORD")
    if not settings.UBETTER_TENANT_USERNAME:
        missing.append("UBETTER_TENANT_USERNAME")
    return missing


def ubetter_configured() -> bool:
    return bool(
        settings.UBETTER_ENABLED
        and settings.UBETTER_USERNAME
        and settings.UBETTER_PASSWORD
        and settings.UBETTER_TENANT_USERNAME
    )


def _base_url() -> str:
    return settings.UBETTER_BASE_URL.rstrip("/")


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _int_or_none(value: Any) -> Optional[int]:
    f = _float_or_none(value)
    if f is None:
        return None
    return int(f) if f == int(f) else int(round(f))


async def _clear_session_unlocked() -> None:
    global _access_token, _tenant_id, _token_expires_at
    _access_token = None
    _tenant_id = None
    _token_expires_at = 0.0


async def _login_unlocked(client: httpx.AsyncClient) -> None:
    global _access_token, _tenant_id, _token_expires_at
    url = f"{_base_url()}/v1/auth/token"
    body = {
        "username": settings.UBETTER_USERNAME,
        "password": settings.UBETTER_PASSWORD,
        "tenantUsername": settings.UBETTER_TENANT_USERNAME,
    }
    logger.info("Ubetter: POST %s (auth token)", url)
    r = await client.post(url, json=body, headers={"Content-Type": "application/json"})
    try:
        payload = r.json()
    except Exception:
        payload = None
    if r.status_code >= 400:
        if isinstance(payload, dict):
            code = payload.get("code")
            msg = str(payload.get("message") or r.reason_phrase or "login failed")
            if code in (40102, 40303, 40304, 40305, 40306, 40001):
                raise UbetterAuthError(msg)
            raise UbetterApiError("/v1/auth/token", code, msg)
        snippet = (r.text or "").replace("\n", " ").strip()[:400]
        raise UbetterUpstreamHttpError("auth/token", int(r.status_code), snippet)
    if not isinstance(payload, dict):
        raise UbetterAuthError("invalid login response (not object)")
    code = payload.get("code")
    if code != _CODE_SUCCESS:
        msg = str(payload.get("message") or "login failed")
        if code in (40102, 40303, 40304, 40305, 40306, 40001):
            raise UbetterAuthError(msg)
        raise UbetterApiError("/v1/auth/token", code, msg)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise UbetterAuthError("login response missing data")
    token = str(data.get("accessToken") or "").strip()
    tenant = str(data.get("tenantId") or "").strip()
    expires_in = _int_or_none(data.get("expiresIn")) or 3600
    if not token or not tenant:
        raise UbetterAuthError("login response missing accessToken or tenantId")
    _access_token = token
    _tenant_id = tenant
    # Refresh slightly before upstream expiry.
    _token_expires_at = time.time() + max(60, expires_in - 60)
    logger.info("Ubetter: session OK (tenantId=%s, ttl=%ss)", tenant, expires_in)


async def _ensure_token(client: httpx.AsyncClient, *, force: bool = False) -> tuple[str, str]:
    global _access_token, _tenant_id
    async with _session_lock:
        now = time.time()
        if not force and _access_token and _tenant_id and now < _token_expires_at:
            return _access_token, _tenant_id
        await _login_unlocked(client)
        if not _access_token or not _tenant_id:
            raise UbetterAuthError("failed to obtain access token")
        return _access_token, _tenant_id


def _unwrap_api_payload(path: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ubetter {path}: expected JSON object")
    code = payload.get("code")
    if code != _CODE_SUCCESS:
        msg = str(payload.get("message") or path)
        raise UbetterApiError(path, code, msg)
    return payload.get("data")


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    retry_on_token_expired: bool = True,
) -> Any:
    token, tenant_id = await _ensure_token(client)
    url = f"{_base_url()}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    r = await client.request(method, url, params=params, json=json_body, headers=headers)
    if r.status_code >= 400:
        snippet = (r.text or "").replace("\n", " ").strip()[:500]
        short = path.rstrip("/").split("/")[-1] or path.replace("/", "_")
        raise UbetterUpstreamHttpError(short, int(r.status_code), snippet)
    try:
        payload = r.json()
    except Exception:
        raise RuntimeError(f"Ubetter {path}: invalid JSON") from None
    try:
        return _unwrap_api_payload(path, payload)
    except UbetterApiError as exc:
        if exc.code == _CODE_TOKEN_INVALID and retry_on_token_expired:
            logger.info("Ubetter: code=40101 — re-login and retry once (%s)", path)
            async with _session_lock:
                await _clear_session_unlocked()
            return await _request(
                client,
                method,
                path,
                params=params,
                json_body=json_body,
                retry_on_token_expired=False,
            )
        raise


def _normalize_device_rows(data: Any) -> list[dict[str, Any]]:
    items: list[Any] = []
    if isinstance(data, dict):
        raw = data.get("items")
        if isinstance(raw, list):
            items = raw
    elif isinstance(data, list):
        items = data
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in items:
        if not isinstance(row, dict):
            continue
        sn = str(row.get("sn") or "").strip()
        if not sn or sn in seen:
            continue
        seen.add(sn)
        name = str(row.get("name") or "").strip() or sn
        online = bool(row.get("online")) if row.get("online") is not None else False
        out.append({"sn": sn, "name": name, "online": online})
    out.sort(key=lambda x: (not x["online"], x["name"].lower()))
    return out


async def list_devices(page: int = 1, size: int = 50) -> list[dict[str, Any]]:
    if not ubetter_configured():
        return []
    cache_key = f"{int(page)}:{int(size)}"
    now = time.time()
    ttl = float(settings.UBETTER_DEVICE_LIST_CACHE_TTL_SEC)
    cached = _device_list_cache.get(cache_key)
    if cached and (now - cached[1]) <= ttl:
        return cached[0]
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        data = await _request(
            client,
            "GET",
            "/v1/devices",
            params={"page": int(page), "size": min(int(size), 50)},
        )
    out = _normalize_device_rows(data)
    _device_list_cache[cache_key] = (out, now)
    logger.info("Ubetter: list_devices — %s device(s)", len(out))
    return out


def _map_summary_to_power_flow(sn: str, summary: dict[str, Any]) -> dict[str, Any]:
    pv_kw = _float_or_none(summary.get("pvTotalPower"))
    grid_kw = _float_or_none(summary.get("gridActivePower"))
    load_kw = _float_or_none(summary.get("loadActivePower"))
    bat_kw = _float_or_none(summary.get("batteryPower"))
    soc = _int_or_none(summary.get("soc"))
    return {
        "ok": True,
        "configured": True,
        "sn": sn,
        "pvPowerW": pv_kw * 1000.0 if pv_kw is not None else None,
        "gridPowerW": grid_kw * 1000.0 if grid_kw is not None else None,
        "loadPowerW": load_kw * 1000.0 if load_kw is not None else None,
        # API: +batteryPower = charging; UI/Deye: +batteryPowerW = discharge.
        "batteryPowerW": -bat_kw * 1000.0 if bat_kw is not None else None,
        "socPercent": float(soc) if soc is not None else None,
        "sohPercent": _int_or_none(summary.get("soh")),
        "batteryVoltageV": _float_or_none(summary.get("batteryVoltage")),
        "batteryCurrentA": _float_or_none(summary.get("batteryCurrent")),
        "batteryTemperatureC": _float_or_none(summary.get("batteryTemperature")),
        "reportTimeMs": _int_or_none(summary.get("reportTime")),
    }


async def get_device_summary(sn: str) -> dict[str, Any]:
    device_sn = (sn or "").strip()
    if not device_sn:
        return {"ok": False, "configured": bool(ubetter_configured()), "reason": "missing_sn"}
    if not ubetter_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        data = await _request(client, "GET", f"/v1/devices/{device_sn}")
    if not isinstance(data, dict):
        return {"ok": False, "configured": True, "reason": "invalid_summary", "sn": device_sn}
    body = _map_summary_to_power_flow(device_sn, data)
    return body


async def get_power_flow(sn: str) -> dict[str, Any]:
    device_sn = (sn or "").strip()
    if not device_sn:
        return {"ok": False, "configured": bool(ubetter_configured()), "reason": "missing_sn"}
    if not ubetter_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    now = time.time()
    ttl = float(settings.UBETTER_POWER_FLOW_CACHE_TTL_SEC)
    cached = _power_flow_cache.get(device_sn)
    if cached and (now - cached[1]) <= ttl:
        return dict(cached[0])
    body = await get_device_summary(device_sn)
    if body.get("ok"):
        _power_flow_cache[device_sn] = (dict(body), now)
    return body


async def get_energy(
    sn: str,
    *,
    year: Optional[str] = None,
    month: Optional[str] = None,
) -> dict[str, Any]:
    device_sn = (sn or "").strip()
    if not device_sn:
        return {"ok": False, "reason": "missing_sn"}
    if not ubetter_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    params: dict[str, str] = {}
    if year:
        params["year"] = str(year).strip()
    if month:
        params["month"] = str(month).strip()
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        data = await _request(client, "GET", f"/v1/devices/{device_sn}/energy", params=params or None)
    rows: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "totalChargeKwh": _float_or_none(item.get("totalCharge")),
                    "totalDischargeKwh": _float_or_none(item.get("totalDischarge")),
                    "totalChargeFee": _float_or_none(item.get("totalChargeFee")),
                    "totalChargeIncome": _float_or_none(item.get("totalChargeIncome")),
                    "totalDischargeFee": _float_or_none(item.get("totalDischargeFee")),
                }
            )
    return {"ok": True, "configured": True, "sn": device_sn, "items": rows}
