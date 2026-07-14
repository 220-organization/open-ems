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


# Open API run-strategy: 0=Manual; chargeCtrl 1=charge, 2=discharge (appendix B).
_STRATEGY_MANUAL = 0
_CHARGE_CTRL_IDLE = 0
_CHARGE_CTRL_CHARGE = 1
_CHARGE_CTRL_DISCHARGE = 2


def _invalidate_power_flow_cache(device_sn: str) -> None:
    _power_flow_cache.pop((device_sn or "").strip(), None)


def _clamp_soc(value: Any, *, default: int) -> int:
    n = _int_or_none(value)
    if n is None:
        return default
    return max(0, min(100, n))


def _manual_run_strategy_body(
    *,
    charge_ctrl: int,
    charge_soc: int,
    discharge_soc: int,
    power_kw: Optional[float] = None,
    for_charge: bool,
    include_power: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "strategy": _STRATEGY_MANUAL,
        "chargeCtrl": int(charge_ctrl),
        "chargeSoc": _clamp_soc(charge_soc, default=95),
        "dischargeSoc": _clamp_soc(discharge_soc, default=10),
    }
    if include_power:
        kw = power_kw if power_kw is not None else float(settings.UBETTER_MANUAL_POWER_KW)
        if kw > 0:
            if for_charge:
                body["chargePower"] = float(kw)
            else:
                body["dischargePower"] = float(kw)
    return body


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


async def start_manual_charge(
    sn: str,
    *,
    charge_soc_percent: int,
    discharge_soc_percent: int = 10,
    power_kw: Optional[float] = None,
) -> dict[str, Any]:
    """Manual charge until chargeSoc (Open API strategy=0, chargeCtrl=1)."""
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
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_CHARGE,
        charge_soc=charge_soc,
        discharge_soc=discharge_soc,
        power_kw=power_kw,
        for_charge=True,
    )
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
) -> dict[str, Any]:
    """Manual discharge until dischargeSoc (Open API strategy=0, chargeCtrl=2)."""
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
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_DISCHARGE,
        charge_soc=charge_soc,
        discharge_soc=discharge_soc,
        power_kw=power_kw,
        for_charge=False,
    )
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
    """Stop manual charge/discharge (chargeCtrl=0, strategy stays Manual)."""
    device_sn = (sn or "").strip()
    body = _manual_run_strategy_body(
        charge_ctrl=_CHARGE_CTRL_IDLE,
        charge_soc=charge_soc_percent,
        discharge_soc=discharge_soc_percent,
        for_charge=True,
        include_power=False,
    )
    return await update_run_strategy(device_sn, body)
