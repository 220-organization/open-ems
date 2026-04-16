"""Huawei FusionSolar SmartPVMS Northbound Open API — session + plant list + real-time KPI (read-only)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from app import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_session_lock = asyncio.Lock()
# Serialize Northbound thirdData POSTs — parallel /stations + /plant-status caused failCode 407 bursts.
_third_data_lock = asyncio.Lock()
_xsrf_token: Optional[str] = None
_huawei_cookies: httpx.Cookies = httpx.Cookies()

_FAIL_CODE_SESSION_EXPIRED = 305
# Northbound: ACCESS_FREQUENCY_IS_TOO_HIGH — Huawei limits how often getStationRealKpi may be called (often ~5 min).
_FAIL_CODE_RATE_LIMIT = 407

# Last successful getStationRealKpi payload per stationCodes key (used when 407 returns before next allowed call).
_plant_status_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}

# Last successful getStationList result per pageNo:pageSize (407 fallback).
_station_list_cache: dict[str, tuple[list[dict[str, str]], float]] = {}
# Monotonic wall time: skip calling getStationList until then after 407 with no cache (list cell, not global stmt).
_station_list_skip_api_until: list[float] = [0.0]


class HuaweiNorthboundError(RuntimeError):
    """API returned success=false with a known failCode."""

    __slots__ = ("fail_code", "path", "api_message")

    def __init__(self, path: str, fail_code: Any, api_message: str):
        self.path = path
        self.fail_code = fail_code
        self.api_message = api_message
        super().__init__(f"Huawei {path} failCode={fail_code} message={api_message}")


class HuaweiRateLimitNoCacheError(RuntimeError):
    """Northbound failCode 407 and no cached response yet — retry after several minutes."""


def huawei_missing_env_names() -> list[str]:
    missing: list[str] = []
    if not settings.HUAWEI_USER_NAME:
        missing.append("HUAWEI_USER_NAME")
    if not settings.HUAWEI_SYSTEM_CODE:
        missing.append("HUAWEI_SYSTEM_CODE")
    return missing


def huawei_configured() -> bool:
    return bool(settings.HUAWEI_USER_NAME and settings.HUAWEI_SYSTEM_CODE)


def _base_url() -> str:
    return settings.HUAWEI_BASE_URL.rstrip("/")


def _xsrf_from_response(r: httpx.Response) -> Optional[str]:
    for key, val in r.headers.items():
        if key.lower() == "xsrf-token" and val and str(val).strip():
            return str(val).strip()
    return None


async def _clear_session_unlocked() -> None:
    global _xsrf_token
    _xsrf_token = None
    _huawei_cookies.clear()


async def _login_unlocked(client: httpx.AsyncClient) -> None:
    global _xsrf_token
    url = f"{_base_url()}/thirdData/login"
    body = {"userName": settings.HUAWEI_USER_NAME, "systemCode": settings.HUAWEI_SYSTEM_CODE}
    logger.info("Huawei: POST %s (Northbound login)", url)
    r = await client.post(
        url,
        json=body,
        headers={"Content-Type": "application/json"},
        cookies=_huawei_cookies,
    )
    if r.status_code >= 400:
        logger.warning("Huawei: login HTTP %s — %s", r.status_code, (r.text or "")[:500])
    r.raise_for_status()
    try:
        payload = r.json()
    except Exception:
        logger.warning("Huawei: login response is not JSON — %s", (r.text or "")[:400])
        raise RuntimeError("Huawei login: invalid JSON response") from None
    if not payload.get("success"):
        msg = str(payload.get("message") or payload.get("msg") or "login failed")
        logger.warning("Huawei: login success=false — %s", msg[:400])
        raise RuntimeError(msg)

    token = _xsrf_from_response(r)
    if not token:
        logger.warning("Huawei: login OK but no xsrf-token header in response")
        raise RuntimeError("Huawei login: missing xsrf-token header")

    _huawei_cookies.update(r.cookies)
    _xsrf_token = token
    logger.info("Huawei: session OK (xsrf-token acquired)")


async def _ensure_session(client: httpx.AsyncClient) -> str:
    global _xsrf_token
    async with _session_lock:
        if _xsrf_token:
            return _xsrf_token
        await _login_unlocked(client)
        if not _xsrf_token:
            raise RuntimeError("Huawei: failed to obtain xsrf-token")
        return _xsrf_token


async def _post_third_data_impl(
    client: httpx.AsyncClient,
    path: str,
    json_body: dict[str, Any],
    *,
    retry_on_session_expired: bool = True,
) -> dict[str, Any]:
    token = await _ensure_session(client)
    url = f"{_base_url()}{path}"
    headers = {
        "Content-Type": "application/json",
        "xsrf-token": token,
    }
    r = await client.post(url, json=json_body, headers=headers, cookies=_huawei_cookies)
    if r.status_code >= 400:
        logger.warning("Huawei: POST %s HTTP %s — %s", path, r.status_code, (r.text or "")[:600])
    r.raise_for_status()
    try:
        data = r.json()
    except Exception:
        logger.warning("Huawei: POST %s — non-JSON body", path)
        raise RuntimeError(f"Huawei {path}: invalid JSON") from None

    if isinstance(data, dict):
        _huawei_cookies.update(r.cookies)
        fc = data.get("failCode")
        if fc == _FAIL_CODE_SESSION_EXPIRED and retry_on_session_expired:
            logger.info("Huawei: failCode=305 — clearing session and retrying once (%s)", path)
            async with _session_lock:
                await _clear_session_unlocked()
            return await _post_third_data_impl(client, path, json_body, retry_on_session_expired=False)
        if data.get("success") is False:
            msg = str(data.get("message") or data.get("msg") or path)
            logger.warning("Huawei: POST %s success=false failCode=%s msg=%s", path, fc, msg[:400])
            raise HuaweiNorthboundError(path, fc, msg)

    if not isinstance(data, dict):
        raise RuntimeError(f"Huawei {path}: expected JSON object")
    return data


async def _post_third_data(
    client: httpx.AsyncClient,
    path: str,
    json_body: dict[str, Any],
    *,
    retry_on_session_expired: bool = True,
) -> dict[str, Any]:
    async with _third_data_lock:
        return await _post_third_data_impl(
            client, path, json_body, retry_on_session_expired=retry_on_session_expired
        )


def _collect_station_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    raw: list[Any] = []
    if isinstance(data, dict):
        raw = (
            data.get("list")
            or data.get("stationList")
            or data.get("plants")
            or data.get("pageList")
            or []
        )
    if not isinstance(raw, list):
        raw = payload.get("list") or payload.get("stationList") or []
    return [x for x in raw if isinstance(x, dict)]


def _station_code_from_row(row: dict[str, Any]) -> str:
    for k in ("plantCode", "stationCode", "id", "dn"):
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _station_name_from_row(row: dict[str, Any]) -> str:
    for k in ("plantName", "stationName", "name", "title"):
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _station_list_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = _collect_station_rows(payload)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        code = _station_code_from_row(row)
        if not code or code in seen:
            continue
        seen.add(code)
        name = _station_name_from_row(row) or code
        out.append({"stationCode": code, "stationName": name})
    out.sort(key=lambda x: x["stationName"].lower())
    return out


def _station_list_disk_path(cache_key: str) -> Path:
    safe = cache_key.replace(":", "_")
    return settings.huawei_disk_cache_dir() / f"station_list_{safe}.json"


def _read_station_list_disk(cache_key: str) -> Optional[tuple[list[dict[str, str]], float]]:
    if not settings.HUAWEI_DISK_CACHE_ENABLED:
        return None
    path = _station_list_disk_path(cache_key)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    saved = data.get("savedAt")
    items = data.get("items")
    if not isinstance(saved, (int, float)) or not isinstance(items, list):
        return None
    if time.time() - float(saved) > float(settings.HUAWEI_STATION_LIST_DISK_TTL_SEC):
        return None
    out: list[dict[str, str]] = []
    for x in items:
        if not isinstance(x, dict):
            continue
        code = str(x.get("stationCode") or "").strip()
        name = str(x.get("stationName") or "").strip() or code
        if code:
            out.append({"stationCode": code, "stationName": name})
    if not out:
        return None
    out.sort(key=lambda x: x["stationName"].lower())
    return (out, float(saved))


def _write_station_list_disk(cache_key: str, items: list[dict[str, str]]) -> None:
    if not settings.HUAWEI_DISK_CACHE_ENABLED:
        return
    path = _station_list_disk_path(cache_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(
            {"savedAt": time.time(), "items": items},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        path.write_text(blob, encoding="utf-8")
    except OSError as exc:
        logger.warning("Huawei: station list disk cache write failed — %s", exc)


async def list_stations(page_no: int = 1, page_size: int = 100) -> list[dict[str, str]]:
    if not huawei_configured():
        return []

    cache_key = f"{int(page_no)}:{int(page_size)}"
    now = time.time()
    if cache_key not in _station_list_cache:
        disk = _read_station_list_disk(cache_key)
        if disk:
            _station_list_cache[cache_key] = disk

    if now < _station_list_skip_api_until[0]:
        cached = _station_list_cache.get(cache_key)
        if cached:
            logger.info("Huawei: list_stations — cooldown, RAM cache (%s plants)", len(cached[0]))
            return cached[0]
        disk2 = _read_station_list_disk(cache_key)
        if disk2:
            _station_list_cache[cache_key] = disk2
            logger.info("Huawei: list_stations — cooldown, disk cache (%s plants)", len(disk2[0]))
            return disk2[0]
        logger.warning(
            "Huawei: list_stations — cooldown %.0fs left, no station list cache",
            _station_list_skip_api_until[0] - now,
        )
        raise HuaweiRateLimitNoCacheError("northbound_rate_limit_no_station_list")

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            payload = await _post_third_data(
                client,
                "/thirdData/getStationList",
                {"pageNo": int(page_no), "pageSize": int(page_size)},
            )
    except HuaweiNorthboundError as exc:
        if exc.fail_code == _FAIL_CODE_RATE_LIMIT:
            cached = _station_list_cache.get(cache_key)
            if cached:
                age = now - cached[1]
                logger.warning(
                    "Huawei: getStationList failCode=407 — returning cached list (age %.0fs, %s plants)",
                    age,
                    len(cached[0]),
                )
                return cached[0]
            disk = _read_station_list_disk(cache_key)
            if disk:
                out_d, saved_at = disk
                _station_list_cache[cache_key] = disk
                logger.warning(
                    "Huawei: getStationList failCode=407 — returning disk cache (age %.0fs, %s plants)",
                    now - saved_at,
                    len(out_d),
                )
                return out_d
            cool = float(settings.HUAWEI_STATION_LIST_COOLDOWN_AFTER_407_SEC)
            _station_list_skip_api_until[0] = now + cool
            logger.warning(
                "Huawei: getStationList failCode=407 — no cache; pausing further list calls for %.0fs",
                cool,
            )
            raise HuaweiRateLimitNoCacheError("northbound_rate_limit_no_station_list") from exc
        raise

    out = _station_list_from_payload(payload)
    _station_list_cache[cache_key] = (out, now)
    _station_list_skip_api_until[0] = 0.0
    _write_station_list_disk(cache_key, out)
    logger.info("Huawei: list_stations — %s plant(s)", len(out))
    return out


def _float_from_map(m: dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        if k not in m:
            continue
        raw = m.get(k)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _active_power_w_from_data_item_map(m: dict[str, Any]) -> Optional[float]:
    if not m:
        return None
    lower_map = {str(k).lower(): v for k, v in m.items()}
    candidates_kw = (
        "active_power",
        "activepower",
        "p_power",
        "ppower",
        "generation_power",
        "pv_power",
        "inverter_power",
        "total_active_power",
        "realtime_power",
    )
    for ck in candidates_kw:
        for mk, mv in lower_map.items():
            if ck.replace("_", "") == mk.replace("_", "") or ck == mk:
                try:
                    v = float(mv)
                except (TypeError, ValueError):
                    continue
                if v != v:  # NaN
                    continue
                if abs(v) < 500:
                    return v * 1000.0
                return v
    return None


def _parse_kpi_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        inner = data.get("list") or data.get("dataList") or []
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
    return []


def _build_plant_status_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = _parse_kpi_items(payload)
    out: list[dict[str, Any]] = []
    for it in items:
        code = str(it.get("stationCode") or it.get("plantCode") or "").strip()
        dim = it.get("dataItemMap")
        if not code or not isinstance(dim, dict):
            continue
        health = _float_from_map(dim, "real_health_state", "realHealthState")
        day_kwh = _float_from_map(dim, "day_power", "dayPower", "day_cap")
        month_kwh = _float_from_map(dim, "month_power", "monthPower")
        total_kwh = _float_from_map(dim, "total_power", "totalPower", "total_cap")
        pv_w = _active_power_w_from_data_item_map(dim)
        out.append(
            {
                "stationCode": code,
                "healthState": int(health) if health is not None and health == int(health) else None,
                "dayPowerKwh": day_kwh,
                "monthPowerKwh": month_kwh,
                "totalPowerKwh": total_kwh,
                "pvPowerW": pv_w,
            }
        )
    return out


async def get_plant_status(station_codes: str) -> list[dict[str, Any]]:
    codes = ",".join(s.strip() for s in (station_codes or "").split(",") if s.strip())
    if not codes:
        return []
    if not huawei_configured():
        return []

    now = time.time()
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            payload = await _post_third_data(
                client,
                "/thirdData/getStationRealKpi",
                {"stationCodes": codes},
            )
    except HuaweiNorthboundError as exc:
        if exc.fail_code == _FAIL_CODE_RATE_LIMIT:
            cached = _plant_status_cache.get(codes)
            if cached:
                age = now - cached[1]
                logger.warning(
                    "Huawei: getStationRealKpi failCode=407 (rate limit) — returning cached data (age %.0fs)",
                    age,
                )
                return cached[0]
            logger.warning(
                "Huawei: getStationRealKpi failCode=407 (ACCESS_FREQUENCY_IS_TOO_HIGH) — no cache yet; "
                "wait ~5 minutes between calls (UI polls every 300s).",
            )
            raise HuaweiRateLimitNoCacheError(
                "Huawei FusionSolar rate limit (failCode 407): getStationRealKpi may only be called "
                "about once every 5 minutes for this Northbound account. Wait and retry."
            ) from exc
        raise

    out = _build_plant_status_rows(payload)
    if out:
        _plant_status_cache[codes] = (out, now)
    return out
