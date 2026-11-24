"""Ubetter EMS Open API — multi-tenant auth, device list, power-flow, manual control.

Supports parallel tenants:
  - default (cabinettest) via UBETTER_PASSWORD
  - dedicated 220km via UBETTER_220KM_PASSWORD
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_CODE_SUCCESS = 0
_CODE_TOKEN_INVALID = 40101

_device_list_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
_power_flow_cache: dict[str, tuple[dict[str, Any], float]] = {}
# sn → account key (updated on successful list_devices)
_sn_account: dict[str, str] = {}
_sessions: dict[str, "UbetterSession"] = {}
_sessions_lock = asyncio.Lock()


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


@dataclass(frozen=True)
class UbetterAccountConfig:
    key: str
    username: str
    password: str
    tenant_username: str
    base_url: str

    @property
    def configured(self) -> bool:
        return bool(self.password and self.username and self.tenant_username and self.base_url)


def configured_ubetter_accounts() -> list[UbetterAccountConfig]:
    """Return enabled accounts that have a password (order: default, then 220km)."""
    if not settings.UBETTER_ENABLED:
        return []
    base = settings.UBETTER_BASE_URL.rstrip("/")
    out: list[UbetterAccountConfig] = []
    default = UbetterAccountConfig(
        key="default",
        username=settings.UBETTER_USERNAME,
        password=settings.UBETTER_PASSWORD,
        tenant_username=settings.UBETTER_TENANT_USERNAME,
        base_url=base,
    )
    if default.configured:
        out.append(default)
    km = UbetterAccountConfig(
        key="220km",
        username=settings.UBETTER_220KM_USERNAME,
        password=settings.UBETTER_220KM_PASSWORD,
        tenant_username=settings.UBETTER_220KM_TENANT_USERNAME,
        base_url=base,
    )
    if km.configured:
        out.append(km)
    return out


def ubetter_missing_env_names() -> list[str]:
    if configured_ubetter_accounts():
        return []
    missing: list[str] = []
    if not settings.UBETTER_PASSWORD and not settings.UBETTER_220KM_PASSWORD:
        missing.append("UBETTER_PASSWORD or UBETTER_220KM_PASSWORD")
    return missing


def ubetter_configured() -> bool:
    return bool(configured_ubetter_accounts())


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


class UbetterSession:
    """Per-tenant HTTP session (token + X-Tenant-Id)."""

    __slots__ = ("account", "_lock", "_access_token", "_tenant_id", "_token_expires_at")

    def __init__(self, account: UbetterAccountConfig):
        self.account = account
        self._lock = asyncio.Lock()
        self._access_token: Optional[str] = None
        self._tenant_id: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _clear_unlocked(self) -> None:
        self._access_token = None
        self._tenant_id = None
        self._token_expires_at = 0.0

    async def _login_unlocked(self, client: httpx.AsyncClient) -> None:
        url = f"{self.account.base_url}/v1/auth/token"
        body = {
            "username": self.account.username,
            "password": self.account.password,
            "tenantUsername": self.account.tenant_username,
        }
        logger.info("Ubetter[%s]: POST %s (auth token)", self.account.key, url)
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
        self._access_token = token
        self._tenant_id = tenant
        self._token_expires_at = time.time() + max(60, expires_in - 60)
        logger.info(
            "Ubetter[%s]: session OK (tenantId=%s, ttl=%ss)",
            self.account.key,
            tenant,
            expires_in,
        )

    async def ensure_token(self, client: httpx.AsyncClient, *, force: bool = False) -> tuple[str, str]:
        async with self._lock:
            now = time.time()
            if not force and self._access_token and self._tenant_id and now < self._token_expires_at:
                return self._access_token, self._tenant_id
            await self._login_unlocked(client)
            if not self._access_token or not self._tenant_id:
                raise UbetterAuthError("failed to obtain access token")
            return self._access_token, self._tenant_id

    async def request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        retry_on_token_expired: bool = True,
    ) -> Any:
        token, tenant_id = await self.ensure_token(client)
        url = f"{self.account.base_url}{path}"
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
                logger.info(
                    "Ubetter[%s]: code=40101 — re-login and retry once (%s)",
                    self.account.key,
                    path,
                )
                async with self._lock:
                    await self._clear_unlocked()
                return await self.request(
                    client,
                    method,
                    path,
                    params=params,
                    json_body=json_body,
                    retry_on_token_expired=False,
                )
            raise


def _unwrap_api_payload(path: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ubetter {path}: expected JSON object")
    code = payload.get("code")
    if code != _CODE_SUCCESS:
        msg = str(payload.get("message") or path)
        raise UbetterApiError(path, code, msg)
    return payload.get("data")


async def _get_or_create_session(account: UbetterAccountConfig) -> UbetterSession:
    async with _sessions_lock:
        sess = _sessions.get(account.key)
        if sess is None or sess.account != account:
            sess = UbetterSession(account)
            _sessions[account.key] = sess
        return sess


async def _sessions_for_configured() -> list[UbetterSession]:
    return [await _get_or_create_session(a) for a in configured_ubetter_accounts()]


async def _session_for_sn(sn: str) -> UbetterSession:
    """Resolve which tenant owns ``sn`` (from prior list, or probe all accounts)."""
    device_sn = (sn or "").strip()
    key = _sn_account.get(device_sn)
    accounts = {a.key: a for a in configured_ubetter_accounts()}
    if key and key in accounts:
        return await _get_or_create_session(accounts[key])
    sessions = await _sessions_for_configured()
    if not sessions:
        raise UbetterAuthError("no Ubetter account configured")
    if len(sessions) == 1:
        return sessions[0]

    async def _probe(session: UbetterSession) -> Optional[UbetterSession]:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                await session.request(client, "GET", f"/v1/devices/{device_sn}")
            _sn_account[device_sn] = session.account.key
            return session
        except Exception:
            return None

    results = await asyncio.gather(*[_probe(s) for s in sessions])
    for hit in results:
        if hit is not None:
            return hit
    # Fallback: first configured (caller surfaces upstream error)
    return sessions[0]


def _normalize_device_rows(
    data: Any,
    *,
    account_key: str,
) -> list[dict[str, Any]]:
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
        out.append({"sn": sn, "name": name, "online": online, "accountKey": account_key})
        _sn_account[sn] = account_key
    return out


async def _list_devices_one(
    session: UbetterSession,
    page: int,
    size: int,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        data = await session.request(
            client,
            "GET",
            "/v1/devices",
            params={"page": int(page), "size": min(int(size), 50)},
        )
    return _normalize_device_rows(data, account_key=session.account.key)


async def list_devices(page: int = 1, size: int = 50) -> list[dict[str, Any]]:
    """Merge device lists from all configured tenants (both accounts stay active).

    Account fetches run sequentially — concurrent logins under the same Open API
    tenantId can drop one account's device list. Both tenants remain configured
    and serve power-flow/control in parallel via per-SN session routing.
    """
    sessions = await _sessions_for_configured()
    if not sessions:
        return []
    cache_key = f"{int(page)}:{int(size)}:{','.join(s.account.key for s in sessions)}"
    now = time.time()
    ttl = float(settings.UBETTER_DEVICE_LIST_CACHE_TTL_SEC)
    cached = _device_list_cache.get(cache_key)
    if cached and (now - cached[1]) <= ttl:
        return cached[0]

    async def _one(session: UbetterSession) -> tuple[list[dict[str, Any]], bool]:
        try:
            rows = await _list_devices_one(session, page, size)
            logger.info(
                "Ubetter[%s]: list_devices — %s device(s)",
                session.account.key,
                len(rows),
            )
            return rows, True
        except UbetterAuthError as exc:
            logger.warning(
                "Ubetter[%s]: list_devices login failed: %s",
                session.account.key,
                exc,
            )
            return [], False
        except Exception:
            logger.exception("Ubetter[%s]: list_devices failed", session.account.key)
            return [], False

    # Sequential: avoids concurrent /v1/auth/token races on shared tenantId.
    parts: list[list[dict[str, Any]]] = []
    all_ok = True
    for session in sessions:
        rows, ok = await _one(session)
        parts.append(rows)
        all_ok = all_ok and ok

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for part in parts:
        for row in part:
            sn = row["sn"]
            if sn in seen:
                continue
            seen.add(sn)
            merged.append(row)
    merged.sort(key=lambda x: (not x["online"], x["name"].lower()))
    # Only cache complete merges so a single-account failure is not sticky for TTL.
    if all_ok:
        _device_list_cache[cache_key] = (merged, now)
    logger.info(
        "Ubetter: list_devices merged — %s device(s) from %s account(s) (all_ok=%s)",
        len(merged),
        len(sessions),
        all_ok,
    )
    return merged


def _kw_to_w(kw: Optional[float]) -> Optional[float]:
    return kw * 1000.0 if kw is not None else None


def _battery_power_w_from_api_kw(bat_kw: Optional[float]) -> Optional[float]:
    # Ubetter API: +batteryPower = charging; UI/Deye: +batteryPowerW = discharge.
    return -bat_kw * 1000.0 if bat_kw is not None else None


def _off_grid_from_energy_flow(energy_flow: Any) -> Optional[bool]:
    """True when the utility grid is disconnected.

    ``energyFlow.gridData.gridConnected`` is false while the cabinet runs
    islanded (battery covers the load, grid meter at 0 kW). A missing flag
    stays unknown so a summary-only payload is not painted off-grid.
    """
    if not isinstance(energy_flow, dict):
        return None
    grid = energy_flow.get("gridData")
    if not isinstance(grid, dict) or "gridConnected" not in grid:
        return None
    connected = grid.get("gridConnected")
    if isinstance(connected, bool):
        return not connected
    return None


def _map_summary_to_power_flow(sn: str, summary: dict[str, Any]) -> dict[str, Any]:
    pv_kw = _float_or_none(summary.get("pvTotalPower"))
    grid_kw = _float_or_none(summary.get("gridActivePower"))
    load_kw = _float_or_none(summary.get("loadActivePower"))
    bat_kw = _float_or_none(summary.get("batteryPower"))
    soc = _float_or_none(summary.get("soc"))
    if soc is None:
        soc_int = _int_or_none(summary.get("soc"))
        soc = float(soc_int) if soc_int is not None else None
    return {
        "ok": True,
        "configured": True,
        "sn": sn,
        "pvPowerW": _kw_to_w(pv_kw),
        "gridPowerW": _kw_to_w(grid_kw),
        "loadPowerW": _kw_to_w(load_kw),
        "batteryPowerW": _battery_power_w_from_api_kw(bat_kw),
        "socPercent": soc,
        "sohPercent": _int_or_none(summary.get("soh")),
        "batteryVoltageV": _float_or_none(summary.get("batteryVoltage")),
        "batteryCurrentA": _float_or_none(summary.get("batteryCurrent")),
        "batteryTemperatureC": _float_or_none(summary.get("batteryTemperature")),
        "reportTimeMs": _int_or_none(summary.get("reportTime")),
        "offGrid": None,
    }


def _extract_detail_group_summary(detail_data: Any) -> Optional[dict[str, Any]]:
    """Return groupRow.summary or singleDevice.summary from GET /v1/devices/{sn}/detail."""
    if not isinstance(detail_data, dict):
        return None
    group = detail_data.get("groupRow")
    if isinstance(group, dict):
        summary = group.get("summary")
        if isinstance(summary, dict):
            return summary
    single = detail_data.get("singleDevice")
    if isinstance(single, dict):
        summary = single.get("summary")
        if isinstance(summary, dict):
            return summary
    return None


def _energy_flow_power_kw(energy_flow: Any, block_key: str) -> Optional[float]:
    if not isinstance(energy_flow, dict):
        return None
    block = energy_flow.get(block_key)
    if not isinstance(block, dict):
        return None
    return _float_or_none(block.get("power"))


def _map_detail_to_power_flow(
    sn: str,
    detail_summary: dict[str, Any],
    summary_fallback: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Map GET /v1/devices/{sn}/detail group summary; fill gaps from realtime summary."""
    fb = summary_fallback if isinstance(summary_fallback, dict) else {}
    rt = detail_summary.get("realtimePower")
    rt = rt if isinstance(rt, dict) else {}
    ef = detail_summary.get("energyFlow")

    pv_kw = _energy_flow_power_kw(ef, "pvData")
    load_kw = _energy_flow_power_kw(ef, "loadData")
    grid_kw = _energy_flow_power_kw(ef, "gridData")
    if pv_kw is None:
        pv_kw = _float_or_none(fb.get("pvTotalPower"))
    if load_kw is None:
        load_kw = _float_or_none(fb.get("loadActivePower"))
    if grid_kw is None:
        grid_kw = _float_or_none(fb.get("gridActivePower"))

    bat_kw = _float_or_none(rt.get("batteryPower"))
    if bat_kw is None:
        bat_kw = _float_or_none(fb.get("batteryPower"))

    soc = _float_or_none(detail_summary.get("soc"))
    if soc is None:
        soc_int = _int_or_none(fb.get("soc"))
        soc = float(soc_int) if soc_int is not None else None

    report_ts = _int_or_none(rt.get("powerTimestamp")) or _int_or_none(fb.get("reportTime"))

    return {
        "ok": True,
        "configured": True,
        "sn": sn,
        "pvPowerW": _kw_to_w(pv_kw),
        "gridPowerW": _kw_to_w(grid_kw),
        "loadPowerW": _kw_to_w(load_kw),
        "batteryPowerW": _battery_power_w_from_api_kw(bat_kw),
        "socPercent": soc,
        "sohPercent": _int_or_none(fb.get("soh")),
        "batteryVoltageV": _float_or_none(fb.get("batteryVoltage")),
        "batteryCurrentA": _float_or_none(fb.get("batteryCurrent")),
        "batteryTemperatureC": _float_or_none(fb.get("batteryTemperature")),
        "reportTimeMs": report_ts,
        "offGrid": _off_grid_from_energy_flow(ef),
    }


async def get_device_summary(sn: str) -> dict[str, Any]:
    device_sn = (sn or "").strip()
    if not device_sn:
        return {"ok": False, "configured": bool(ubetter_configured()), "reason": "missing_sn"}
    if not ubetter_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    session = await _session_for_sn(device_sn)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        detail_summary: Optional[dict[str, Any]] = None
        summary_data: Optional[dict[str, Any]] = None
        try:
            detail_raw = await session.request(
                client,
                "GET",
                f"/v1/devices/{device_sn}/detail",
                params={"viewScope": "group"},
            )
            detail_summary = _extract_detail_group_summary(detail_raw)
        except Exception as exc:
            logger.warning("Ubetter: detail fetch failed for %s: %s", device_sn, exc)
        try:
            summary_raw = await session.request(client, "GET", f"/v1/devices/{device_sn}")
            if isinstance(summary_raw, dict):
                summary_data = summary_raw
        except Exception as exc:
            logger.warning("Ubetter: summary fetch failed for %s: %s", device_sn, exc)
            if detail_summary is None:
                raise
    if detail_summary is not None:
        return _map_detail_to_power_flow(device_sn, detail_summary, summary_data)
    if summary_data is not None:
        return _map_summary_to_power_flow(device_sn, summary_data)
    return {"ok": False, "configured": True, "reason": "invalid_summary", "sn": device_sn}


def _occurred_unix_sec(raw: Any) -> Optional[int]:
    """Ubetter ``time`` is epoch milliseconds; some payloads send seconds."""
    sec = _int_or_none(raw)
    if sec is None:
        return None
    if sec > 10_000_000_000:
        sec //= 1000
    if sec <= 0:
        return None
    return sec


def normalize_ubetter_alarm(row: Any) -> Optional[dict[str, Any]]:
    """One detail ``faultList`` alarm, or None when the row has no identity."""
    if not isinstance(row, dict):
        return None
    alarm_id = str(row.get("id") or "").strip()
    name = str(row.get("alarmName") or "").strip()
    name_en = str(row.get("alarmNameEn") or "").strip()
    if not alarm_id and not name and not name_en:
        return None
    if not alarm_id:
        alarm_id = f"{name_en or name}:{row.get('time') or ''}"
    current = row.get("isCurrentAlarm")
    if isinstance(current, bool):
        active = current
    else:
        active = row.get("isFault") is True
    category = str(row.get("componentCategoryNameEn") or "").strip()
    model = str(row.get("componentModelNameEn") or "").strip()
    position = str(row.get("faultPosition") or "").strip()
    source = str(row.get("alarmSource") or "").strip()
    return {
        "id": alarm_id[:64],
        "name": name or name_en,
        "title": name_en or name,
        "source": source or None,
        "level": _int_or_none(row.get("alarmLevel")),
        "eventStatus": _int_or_none(row.get("eventStatus")),
        "isFault": row.get("isFault") if isinstance(row.get("isFault"), bool) else None,
        "active": active,
        "startTime": _occurred_unix_sec(row.get("time")),
        "componentCategoryEn": category or None,
        "componentModelEn": model or None,
        "faultPosition": position or None,
    }


def alarms_from_fault_list(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in raw:
        item = normalize_ubetter_alarm(row)
        if item is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append(item)
    return out


async def fetch_device_alarms(sn: str) -> tuple[list[dict[str, Any]], bool]:
    """Current alarms from GET /v1/devices/{sn}/detail ``faultList``.

    The second value is False when the payload has no ``faultList`` key, so the
    caller must not mark previously stored alarms as cleared.
    """
    device_sn = (sn or "").strip()
    if not device_sn:
        return [], False
    if not ubetter_configured():
        return [], False
    session = await _session_for_sn(device_sn)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        detail_raw = await session.request(
            client,
            "GET",
            f"/v1/devices/{device_sn}/detail",
            params={"viewScope": "group"},
        )
    summary = _extract_detail_group_summary(detail_raw)
    if not isinstance(summary, dict) or "faultList" not in summary:
        return [], False
    return alarms_from_fault_list(summary.get("faultList")), True


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
    session = await _session_for_sn(device_sn)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        data = await session.request(
            client, "GET", f"/v1/devices/{device_sn}/energy", params=params or None
        )
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


# EMS Open API run-strategy V2.1 (docs/ubetter-run-strategy-v2.1.md).
# Each strategy has one parameter block. Slots are writable only for 3 and 7.
# chargeCtrl lives on strategy 0 (`manual`) only. Device clocks are local; this fleet is in Ukraine.
_STRATEGY_PEAK_SHAVING = 3
_DEVICE_LOCAL_TZ = "Europe/Kyiv"
_CHARGE_CTRL_IDLE = 0
_CHARGE_CTRL_CHARGE = 1
_CHARGE_CTRL_DISCHARGE = 2
_STRATEGY_BLOCKS = {
    0: "manual",
    1: "backup",
    3: "peakValley",
    4: "fixedTime",
    5: "selfConsumption",
    6: "aiAuto",
    7: "transformerExpand",
}
_SETTINGS_STRATEGY_CODES = frozenset(_STRATEGY_BLOCKS)
_SLOT_STRATEGY_CODES = frozenset({3, 7})
_SOC_FIELDS = {
    "manual": ("chargeSoc", "dischargeSoc"),
    "backup": ("chargeSoc",),
    "peakValley": ("chargeSoc", "dischargeSoc"),
    "fixedTime": ("chargeSoc", "dischargeSoc"),
    "selfConsumption": ("chargeSoc", "dischargeSoc"),
    "aiAuto": ("chargeSoc", "dischargeSoc"),
    "transformerExpand": ("chargeSoc", "dischargeSoc"),
}
_POWER_FIELDS = {
    "manual": ("chargePower", "dischargePower"),
    "backup": ("chargePower",),
    "peakValley": ("chargePower", "dischargePower"),
    "fixedTime": ("chargePower", "dischargePower"),
    "selfConsumption": (),
    "aiAuto": ("chargePower", "dischargePower"),
    "transformerExpand": ("chargePower", "dischargePower"),
}


def _invalidate_power_flow_cache(device_sn: str) -> None:
    _power_flow_cache.pop((device_sn or "").strip(), None)


def _clamp_soc(value: Any, *, default: int) -> int:
    n = _int_or_none(value)
    if n is None:
        return default
    return max(0, min(100, n))


def _settings_strategy_code(value: Any) -> Optional[int]:
    """Strategies the settings form may write. Test (2) is not in the V2.1 contract."""
    n = _int_or_none(value)
    if n is None or n not in _SETTINGS_STRATEGY_CODES:
        return None
    return n


def _live_strategy_code(value: Any) -> Optional[int]:
    """Strategy already stored on the device, including AI auto (6) and transformer expansion (7)."""
    n = _int_or_none(value)
    if n is None or n < 0 or n > 7:
        return None
    return n


def _live_block(src: dict[str, Any]) -> dict[str, Any]:
    code = _live_strategy_code(src.get("strategy"))
    name = _STRATEGY_BLOCKS.get(code) if code is not None else None
    block = src.get(name) if name else None
    if isinstance(block, dict):
        return dict(block)
    return {}


def _clock_seconds(value: Any, *, end: bool = False) -> Optional[int]:
    """Device-local HH:mm:ss. endTime 00:00:00 is end of day (24:00)."""
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    if end and hour == 0 and minute == 0 and second == 0:
        return 24 * 3600
    if hour == 24 and minute == 0 and second == 0:
        return 24 * 3600
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return hour * 3600 + minute * 60 + second


def _format_clock(total_seconds: int) -> str:
    if total_seconds >= 24 * 3600:
        return "00:00:00"
    total_seconds = max(0, total_seconds)
    hour, rem = divmod(total_seconds, 3600)
    minute, second = divmod(rem, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _device_local_hms() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(_DEVICE_LOCAL_TZ)).strftime("%H:%M:%S")


def _apply_slot_mode(
    slot: dict[str, Any],
    mode: int,
    power: Optional[float],
    charge_soc: int,
    discharge_soc: int,
) -> dict[str, Any]:
    out = dict(slot)
    out["mode"] = int(mode)
    if int(mode) == _CHARGE_CTRL_IDLE:
        out["power"] = 0
    elif power is not None and float(power) > 0:
        out["power"] = float(power)
    if int(mode) == _CHARGE_CTRL_CHARGE:
        out["chargeSocLimit"] = charge_soc
    elif int(mode) == _CHARGE_CTRL_DISCHARGE:
        out["dischargeSocLimit"] = discharge_soc
    return out


def _slots_with_mode(
    slots: Any,
    *,
    now_hms: str,
    mode: int,
    power: Optional[float],
    charge_soc: int,
    discharge_soc: int,
) -> list[dict[str, Any]]:
    """Keep every saved window. Point the window that covers now at charge, discharge, or idle."""
    now_sec = _clock_seconds(now_hms)
    if now_sec is None:
        now_sec = 0
    parsed: list[tuple[int, int, dict[str, Any]]] = []
    untouched: list[dict[str, Any]] = []
    raw = slots if isinstance(slots, list) else []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start = _clock_seconds(item.get("startTime"))
        end = _clock_seconds(item.get("endTime"), end=True)
        if start is None or end is None or end <= start:
            untouched.append(dict(item))
            continue
        parsed.append((start, end, dict(item)))
    covering = [row for row in parsed if row[0] <= now_sec < row[1]]
    ordered: list[tuple[int, dict[str, Any]]] = []
    if covering:
        for start, end, slot in parsed:
            if start <= now_sec < end:
                ordered.append(
                    (start, _apply_slot_mode(slot, mode, power, charge_soc, discharge_soc))
                )
            else:
                ordered.append((start, slot))
    else:
        for start, _end, slot in parsed:
            ordered.append((start, slot))
        later = [start for start, _end, _slot in parsed if start > now_sec]
        next_start = min(later) if later else 24 * 3600
        if next_start > now_sec:
            created: dict[str, Any] = {
                "startTime": _format_clock(now_sec),
                "endTime": _format_clock(next_start),
                "mode": int(mode),
                "power": 0 if int(mode) == _CHARGE_CTRL_IDLE else float(power or 0),
            }
            if int(mode) == _CHARGE_CTRL_CHARGE:
                created["chargeSocLimit"] = charge_soc
            elif int(mode) == _CHARGE_CTRL_DISCHARGE:
                created["dischargeSocLimit"] = discharge_soc
            ordered.append((now_sec, created))
    ordered.sort(key=lambda row: row[0])
    return [slot for _start, slot in ordered] + untouched


def _command_powers(
    *,
    for_charge: bool,
    include_power: bool,
    power_kw: Optional[float],
    charge_power_kw: Optional[float],
    discharge_power_kw: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    if not include_power:
        return None, None
    charge_kw = charge_power_kw
    discharge_kw = discharge_power_kw
    if charge_kw is None and for_charge:
        charge_kw = power_kw if power_kw is not None else float(settings.UBETTER_MANUAL_POWER_KW)
    if discharge_kw is None and not for_charge:
        discharge_kw = power_kw if power_kw is not None else float(settings.UBETTER_MANUAL_POWER_KW)
    charge_out = float(charge_kw) if charge_kw is not None and float(charge_kw) > 0 else None
    discharge_out = (
        float(discharge_kw) if discharge_kw is not None and float(discharge_kw) > 0 else None
    )
    return charge_out, discharge_out


def _manual_run_strategy_body(
    *,
    current: Optional[dict[str, Any]],
    charge_ctrl: int,
    charge_soc: int,
    discharge_soc: int,
    power_kw: Optional[float] = None,
    for_charge: bool,
    include_power: bool = True,
    charge_power_kw: Optional[float] = None,
    discharge_power_kw: Optional[float] = None,
    now_hms: str = "12:00:00",
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Nested V2.1 body. Keeps the strategy code already on the device."""
    src = current if isinstance(current, dict) else {}
    code = _live_strategy_code(src.get("strategy"))
    if code is None:
        return None, "strategy_unknown"
    if code == 1 and int(charge_ctrl) == _CHARGE_CTRL_DISCHARGE:
        return None, "backup_charge_only"
    name = _STRATEGY_BLOCKS.get(code)
    if name is None:
        return None, "strategy_unsupported"
    block = dict(src[name]) if isinstance(src.get(name), dict) else {}
    charge_target = _clamp_soc(charge_soc, default=95)
    discharge_target = _clamp_soc(discharge_soc, default=10)
    if "chargeSoc" in _SOC_FIELDS[name]:
        block["chargeSoc"] = charge_target
    if "dischargeSoc" in _SOC_FIELDS[name]:
        block["dischargeSoc"] = discharge_target
    charge_kw, discharge_kw = _command_powers(
        for_charge=for_charge,
        include_power=include_power,
        power_kw=power_kw,
        charge_power_kw=charge_power_kw,
        discharge_power_kw=discharge_power_kw,
    )
    if "chargePower" in _POWER_FIELDS[name] and charge_kw is not None:
        block["chargePower"] = charge_kw
    if "dischargePower" in _POWER_FIELDS[name] and discharge_kw is not None:
        block["dischargePower"] = discharge_kw
    if code == 0:
        block["chargeCtrl"] = int(charge_ctrl)
    body: dict[str, Any] = {"strategy": code, name: block}
    if code in _SLOT_STRATEGY_CODES:
        slot_power = None
        if int(charge_ctrl) == _CHARGE_CTRL_CHARGE:
            slot_power = charge_kw
        elif int(charge_ctrl) == _CHARGE_CTRL_DISCHARGE:
            slot_power = discharge_kw
        elif int(charge_ctrl) == _CHARGE_CTRL_IDLE:
            slot_power = 0
        body["slots"] = _slots_with_mode(
            src.get("slots"),
            now_hms=now_hms,
            mode=int(charge_ctrl),
            power=slot_power,
            charge_soc=charge_target,
            discharge_soc=discharge_target,
        )
    return body, None


def _settings_run_strategy_body(
    current: Optional[dict[str, Any]],
    *,
    strategy: int,
    charge_power_kw: Optional[float],
    discharge_power_kw: Optional[float],
) -> dict[str, Any]:
    """One V2.1 parameter block. Does not send slots, so the saved schedule stays."""
    code = _settings_strategy_code(strategy)
    if code is None:
        raise ValueError("strategy is not writable")
    name = _STRATEGY_BLOCKS[code]
    src = current if isinstance(current, dict) else {}
    prev = _live_block(src)
    same = _live_strategy_code(src.get("strategy")) == code
    block: dict[str, Any] = dict(src[name]) if same and isinstance(src.get(name), dict) else {}
    if "chargeSoc" in _SOC_FIELDS[name]:
        block["chargeSoc"] = _clamp_soc(block.get("chargeSoc", prev.get("chargeSoc")), default=95)
    if "dischargeSoc" in _SOC_FIELDS[name]:
        block["dischargeSoc"] = _clamp_soc(
            block.get("dischargeSoc", prev.get("dischargeSoc")), default=10
        )
    if "chargePower" in _POWER_FIELDS[name] and charge_power_kw is not None:
        block["chargePower"] = float(charge_power_kw)
    if "dischargePower" in _POWER_FIELDS[name] and discharge_power_kw is not None:
        block["dischargePower"] = float(discharge_power_kw)
    return {"strategy": code, name: block}


async def get_run_strategy(sn: str) -> dict[str, Any]:
    device_sn = (sn or "").strip()
    if not device_sn:
        return {"ok": False, "configured": bool(ubetter_configured()), "reason": "missing_sn"}
    if not ubetter_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    session = await _session_for_sn(device_sn)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        data = await session.request(client, "GET", f"/v1/devices/{device_sn}/run-strategy")
    return {"ok": True, "configured": True, "sn": device_sn, "strategy": data}


async def update_run_strategy(sn: str, body: dict[str, Any]) -> dict[str, Any]:
    device_sn = (sn or "").strip()
    if not device_sn:
        return {"ok": False, "configured": bool(ubetter_configured()), "reason": "missing_sn"}
    if not ubetter_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    session = await _session_for_sn(device_sn)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        data = await session.request(
            client, "PUT", f"/v1/devices/{device_sn}/run-strategy", json_body=body
        )
    _invalidate_power_flow_cache(device_sn)
    return {"ok": True, "configured": True, "sn": device_sn, "strategy": data}


async def apply_run_strategy_settings(
    sn: str,
    *,
    strategy: int,
    charge_power_kw: Optional[float],
    discharge_power_kw: Optional[float],
) -> dict[str, Any]:
    """Write the V2.1 block for this strategy. Does not replace slots."""
    device_sn = (sn or "").strip()
    if not device_sn:
        return {"ok": False, "configured": bool(ubetter_configured()), "reason": "missing_sn"}
    if not ubetter_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    code = _settings_strategy_code(strategy)
    if code is None:
        return {"ok": False, "configured": True, "reason": "bad_strategy", "sn": device_sn}
    name = _STRATEGY_BLOCKS[code]
    if "chargePower" in _POWER_FIELDS[name] and (
        charge_power_kw is None or float(charge_power_kw) <= 0
    ):
        return {"ok": False, "configured": True, "reason": "bad_power", "sn": device_sn}
    if "dischargePower" in _POWER_FIELDS[name] and (
        discharge_power_kw is None or float(discharge_power_kw) <= 0
    ):
        return {"ok": False, "configured": True, "reason": "bad_power", "sn": device_sn}
    current = await get_run_strategy(device_sn)
    if not current.get("ok"):
        return current
    live = current.get("strategy") if isinstance(current.get("strategy"), dict) else {}
    body = _settings_run_strategy_body(
        live,
        strategy=code,
        charge_power_kw=charge_power_kw,
        discharge_power_kw=discharge_power_kw,
    )
    return await update_run_strategy(device_sn, body)


async def _load_live_strategy(device_sn: str) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """Return the device's current run-strategy object, or an error body."""
    current = await get_run_strategy(device_sn)
    if not current.get("ok"):
        return None, current
    live = current.get("strategy") if isinstance(current.get("strategy"), dict) else {}
    if _live_strategy_code(live.get("strategy")) is None:
        return None, {
            "ok": False,
            "configured": True,
            "reason": "strategy_unknown",
            "sn": device_sn,
        }
    return live, None


async def start_manual_charge(
    sn: str,
    *,
    charge_soc_percent: int,
    discharge_soc_percent: int = 10,
    power_kw: Optional[float] = None,
    charge_power_kw: Optional[float] = None,
    discharge_power_kw: Optional[float] = None,
) -> dict[str, Any]:
    """Charge until chargeSoc. Keeps the strategy already on the device."""
    device_sn = (sn or "").strip()
    if not device_sn:
        return {"ok": False, "configured": bool(ubetter_configured()), "reason": "missing_sn"}
    if not ubetter_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    summary = await get_device_summary(device_sn)
    start_soc = _float_or_none(summary.get("socPercent")) if summary.get("ok") else None
    charge_soc = _clamp_soc(charge_soc_percent, default=95)
    discharge_soc = _clamp_soc(discharge_soc_percent, default=10)
    if start_soc is not None and start_soc >= charge_soc - 0.05:
        return {
            "ok": False,
            "configured": True,
            "reason": "already_at_charge_target",
            "sn": device_sn,
            "startSoc": start_soc,
            "chargeSocPercent": charge_soc,
        }
    live, err = await _load_live_strategy(device_sn)
    if err is not None or live is None:
        return err or {"ok": False, "configured": True, "reason": "strategy_unknown", "sn": device_sn}
    body, reason = _manual_run_strategy_body(
        current=live,
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=charge_soc,
        discharge_soc=discharge_soc,
        power_kw=power_kw,
        for_charge=True,
        charge_power_kw=charge_power_kw,
        discharge_power_kw=discharge_power_kw,
        now_hms=_device_local_hms(),
    )
    if reason or body is None:
        return {
            "ok": False,
            "configured": True,
            "reason": reason or "strategy_unsupported",
            "sn": device_sn,
        }
    result = await update_run_strategy(device_sn, body)
    return {
        **result,
        "startSoc": start_soc,
        "chargeSocPercent": charge_soc,
        "dischargeSocPercent": discharge_soc,
        "chargeCtrl": _CHARGE_CTRL_CHARGE,
        "respondAfterStart": True,
    }


async def start_manual_discharge(
    sn: str,
    *,
    discharge_soc_percent: int,
    charge_soc_percent: int = 95,
    power_kw: Optional[float] = None,
    charge_power_kw: Optional[float] = None,
    discharge_power_kw: Optional[float] = None,
) -> dict[str, Any]:
    """Discharge until dischargeSoc. Keeps the strategy already on the device."""
    device_sn = (sn or "").strip()
    if not device_sn:
        return {"ok": False, "configured": bool(ubetter_configured()), "reason": "missing_sn"}
    if not ubetter_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}
    summary = await get_device_summary(device_sn)
    start_soc = _float_or_none(summary.get("socPercent")) if summary.get("ok") else None
    discharge_soc = _clamp_soc(discharge_soc_percent, default=10)
    charge_soc = _clamp_soc(charge_soc_percent, default=95)
    if start_soc is not None and start_soc <= discharge_soc + 0.05:
        return {
            "ok": False,
            "configured": True,
            "reason": "already_at_discharge_target",
            "sn": device_sn,
            "startSoc": start_soc,
            "dischargeSocPercent": discharge_soc,
        }
    live, err = await _load_live_strategy(device_sn)
    if err is not None or live is None:
        return err or {"ok": False, "configured": True, "reason": "strategy_unknown", "sn": device_sn}
    body, reason = _manual_run_strategy_body(
        current=live,
        charge_ctrl=_CHARGE_CTRL_DISCHARGE,
        charge_soc=charge_soc,
        discharge_soc=discharge_soc,
        power_kw=power_kw,
        for_charge=False,
        charge_power_kw=charge_power_kw,
        discharge_power_kw=discharge_power_kw,
        now_hms=_device_local_hms(),
    )
    if reason or body is None:
        return {
            "ok": False,
            "configured": True,
            "reason": reason or "strategy_unsupported",
            "sn": device_sn,
        }
    result = await update_run_strategy(device_sn, body)
    return {
        **result,
        "startSoc": start_soc,
        "chargeSocPercent": charge_soc,
        "dischargeSocPercent": discharge_soc,
        "chargeCtrl": _CHARGE_CTRL_DISCHARGE,
        "respondAfterStart": True,
    }


async def stop_manual_control(
    sn: str,
    *,
    charge_soc_percent: int = 95,
    discharge_soc_percent: int = 10,
) -> dict[str, Any]:
    """Stop the slot that covers now and keep peak shaving (strategy=3)."""
    device_sn = (sn or "").strip()
    body, reason = _manual_run_strategy_body(
        current={"strategy": _STRATEGY_PEAK_SHAVING, "peakValley": {}},
        charge_ctrl=_CHARGE_CTRL_IDLE,
        charge_soc=charge_soc_percent,
        discharge_soc=discharge_soc_percent,
        for_charge=True,
        include_power=False,
        now_hms=_device_local_hms(),
    )
    if reason or body is None:
        return {"ok": False, "configured": True, "reason": reason or "strategy_unsupported", "sn": device_sn}
    return await update_run_strategy(device_sn, body)
