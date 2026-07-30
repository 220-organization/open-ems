"""GridLab External BESS API — JWT auth, live status/meters, hourly history (read-only).

Docs: https://gridlab.com.ua/docs (External BESS API).
Base: {GRIDLAB_BASE_URL}/api/external/bess/{GRIDLAB_DEVICE_ID}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import date
from typing import Any, Optional

import httpx

from app import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_status_cache: Optional[tuple[dict[str, Any], float]] = None
_meters_cache: Optional[tuple[dict[str, Any], float]] = None
_session: Optional["GridLabSession"] = None
_session_lock = asyncio.Lock()


class GridLabAuthError(RuntimeError):
    """Login failed or token could not be obtained."""


class GridLabApiError(RuntimeError):
    """Upstream returned a business / HTTP error with a known status."""

    __slots__ = ("path", "http_status", "detail")

    def __init__(self, path: str, http_status: int, detail: str):
        self.path = path
        self.http_status = http_status
        self.detail = detail
        super().__init__(f"GridLab {path} HTTP {http_status}: {detail}")


class GridLabUpstreamHttpError(RuntimeError):
    """Non-success HTTP before usable JSON body."""

    __slots__ = ("endpoint", "http_status", "body_snippet")

    def __init__(self, endpoint: str, http_status: int, body_snippet: str):
        self.endpoint = endpoint
        self.http_status = http_status
        self.body_snippet = body_snippet
        tail = (body_snippet or "").strip()
        if len(tail) > 220:
            tail = tail[:220] + "…"
        msg = f"GridLab HTTP {http_status} ({endpoint})"
        if tail:
            msg = f"{msg}: {tail}"
        super().__init__(msg)


def gridlab_missing_env_names() -> list[str]:
    missing: list[str] = []
    if not settings.GRIDLAB_ENABLED:
        return missing
    if not settings.GRIDLAB_PASSWORD:
        missing.append("GRIDLAB_PASSWORD")
    return missing


def gridlab_configured() -> bool:
    if not settings.GRIDLAB_ENABLED:
        return False
    return bool(settings.GRIDLAB_PASSWORD and settings.GRIDLAB_DEVICE_ID > 0)


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


def _jwt_exp_unix(token: str) -> Optional[float]:
    """Read ``exp`` claim from a JWT without verifying signature (TTL only)."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        pad = "=" * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload + pad)
        data = json.loads(raw.decode("utf-8"))
        exp = data.get("exp")
        if exp is None:
            return None
        return float(exp)
    except Exception:
        return None


def _bess_base() -> str:
    return f"{settings.GRIDLAB_BASE_URL.rstrip('/')}/api/external/bess/{int(settings.GRIDLAB_DEVICE_ID)}"


class GridLabSession:
    """HTTP session with cached JWT Bearer token."""

    __slots__ = ("_lock", "_access_token", "_token_expires_at")

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _clear_unlocked(self) -> None:
        self._access_token = None
        self._token_expires_at = 0.0

    async def _login_unlocked(self, client: httpx.AsyncClient) -> None:
        url = f"{settings.GRIDLAB_BASE_URL.rstrip('/')}/api/auth/login"
        body = {
            "username": settings.GRIDLAB_USERNAME,
            "password": settings.GRIDLAB_PASSWORD,
        }
        logger.info("GridLab: POST %s (auth token)", url)
        r = await client.post(url, json=body, headers={"Content-Type": "application/json"})
        try:
            payload = r.json()
        except Exception:
            payload = None
        if r.status_code >= 400:
            snippet = (r.text or "").replace("\n", " ").strip()[:400]
            if r.status_code in (401, 403):
                raise GridLabAuthError(f"login HTTP {r.status_code}: {snippet or r.reason_phrase}")
            raise GridLabUpstreamHttpError("auth/login", int(r.status_code), snippet)
        if not isinstance(payload, dict):
            raise GridLabAuthError("invalid login response (not object)")
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise GridLabAuthError("login response missing access_token")
        exp = _jwt_exp_unix(token)
        now = time.time()
        if exp is not None and exp > now:
            self._token_expires_at = exp - 60.0
            ttl = max(0, int(exp - now))
        else:
            self._token_expires_at = now + 3600.0 - 60.0
            ttl = 3600
        self._access_token = token
        logger.info("GridLab: session OK (ttl≈%ss)", ttl)

    async def ensure_token(self, client: httpx.AsyncClient, *, force: bool = False) -> str:
        async with self._lock:
            now = time.time()
            if not force and self._access_token and now < self._token_expires_at:
                return self._access_token
            await self._login_unlocked(client)
            if not self._access_token:
                raise GridLabAuthError("failed to obtain access token")
            return self._access_token

    async def request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        retry_on_401: bool = True,
    ) -> Any:
        token = await self.ensure_token(client)
        url = path if path.startswith("http") else f"{settings.GRIDLAB_BASE_URL.rstrip('/')}{path}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        r = await client.request(method, url, params=params, headers=headers)
        if r.status_code == 401 and retry_on_401:
            logger.info("GridLab: HTTP 401 — re-login and retry once (%s)", path)
            async with self._lock:
                await self._clear_unlocked()
            return await self.request(
                client, method, path, params=params, retry_on_401=False
            )
        if r.status_code >= 400:
            snippet = (r.text or "").replace("\n", " ").strip()[:500]
            short = path.rstrip("/").split("/")[-1] or path.replace("/", "_")
            # Spec says 401 for missing/expired token; live probe often returns 403 without token.
            # Do not retry 403 (disabled endpoint / device not allowed).
            if r.status_code in (403, 404, 422, 503):
                raise GridLabApiError(short, int(r.status_code), snippet or r.reason_phrase or "")
            raise GridLabUpstreamHttpError(short, int(r.status_code), snippet)
        try:
            return r.json()
        except Exception:
            raise RuntimeError(f"GridLab {path}: invalid JSON") from None


async def _get_session() -> GridLabSession:
    global _session
    async with _session_lock:
        if _session is None:
            _session = GridLabSession()
        return _session


async def _http_get(path: str, *, params: Optional[dict[str, Any]] = None) -> Any:
    if not gridlab_configured():
        raise GridLabAuthError("GridLab not configured")
    session = await _get_session()
    async with httpx.AsyncClient(timeout=45.0) as client:
        return await session.request(client, "GET", path, params=params)


def _cache_get(
    cache: Optional[tuple[dict[str, Any], float]], ttl_sec: int
) -> Optional[dict[str, Any]]:
    if cache is None:
        return None
    data, ts = cache
    if time.time() - ts < max(1, ttl_sec):
        return data
    return None


async def get_status(*, use_cache: bool = True) -> dict[str, Any]:
    """GET /api/external/bess/{id}/status."""
    global _status_cache
    if use_cache:
        cached = _cache_get(_status_cache, settings.GRIDLAB_STATUS_CACHE_TTL_SEC)
        if cached is not None:
            return cached
    path = f"{_bess_base()}/status"
    payload = await _http_get(path)
    if not isinstance(payload, dict):
        raise RuntimeError("GridLab status: expected JSON object")
    _status_cache = (payload, time.time())
    return payload


async def get_meters(*, use_cache: bool = True) -> dict[str, Any]:
    """GET /api/external/bess/{id}/meters."""
    global _meters_cache
    if use_cache:
        cached = _cache_get(_meters_cache, settings.GRIDLAB_METERS_CACHE_TTL_SEC)
        if cached is not None:
            return cached
    path = f"{_bess_base()}/meters"
    payload = await _http_get(path)
    if not isinstance(payload, dict):
        raise RuntimeError("GridLab meters: expected JSON object")
    _meters_cache = (payload, time.time())
    return payload


async def get_history_flows(date_from: date, date_to: date) -> dict[str, Any]:
    path = f"{_bess_base()}/history/flows"
    payload = await _http_get(
        path,
        params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GridLab history/flows: expected JSON object")
    return payload


async def get_history_meter(meter_id: int, date_from: date, date_to: date) -> dict[str, Any]:
    path = f"{_bess_base()}/history/meter/{int(meter_id)}"
    payload = await _http_get(
        path,
        params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GridLab history/meter: expected JSON object")
    return payload


async def get_history_soc(date_from: date, date_to: date) -> dict[str, Any]:
    path = f"{_bess_base()}/history/soc"
    payload = await _http_get(
        path,
        params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GridLab history/soc: expected JSON object")
    return payload


def clear_caches() -> None:
    """Test helper: drop RAM caches and session."""
    global _status_cache, _meters_cache, _session
    _status_cache = None
    _meters_cache = None
    _session = None
