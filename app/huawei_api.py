"""Huawei FusionSolar SmartPVMS Northbound Open API — session, plant list, real-time KPI."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select

from app import settings
from app.db import async_session_factory
from app.models import HuaweiPowerDevicesCache, HuaweiPowerFlowCache, HuaweiPowerSample, HuaweiStationListCache

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

# Last successful power-flow snapshot per station (getDevRealKpi; 407 fallback).
_power_flow_cache: dict[str, tuple[dict[str, Any], float]] = {}
# getDevList rows per station (device topology changes rarely).
_dev_list_rows_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
# Monotonic: skip live Northbound power-flow until then after 407 (scheduler only).
_northbound_power_flow_cooldown_until: float = 0.0
# Resolved (meterId, meterType, inverterId, inverterType) per stationCode.
_device_pair_cache: dict[str, tuple[str, int, str, int]] = {}


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


class HuaweiAuthError(RuntimeError):
    """FusionSolar Northbound login failed or session token could not be obtained."""


class HuaweiUpstreamHttpError(RuntimeError):
    """Non-success HTTP from FusionSolar before JSON (avoids httpx default message with full URL + MDN link)."""

    __slots__ = ("endpoint", "http_status", "body_snippet")

    def __init__(self, endpoint: str, http_status: int, body_snippet: str):
        self.endpoint = endpoint
        self.http_status = http_status
        self.body_snippet = body_snippet
        tail = (body_snippet or "").strip()
        if len(tail) > 220:
            tail = tail[:220] + "…"
        msg = f"FusionSolar HTTP {http_status} ({endpoint})"
        if tail:
            msg = f"{msg}: {tail}"
        super().__init__(msg)


def huawei_missing_env_names() -> list[str]:
    missing: list[str] = []
    if not settings.HUAWEI_ENABLED:
        missing.append("HUAWEI_ENABLED")
    if not settings.HUAWEI_USER_NAME:
        missing.append("HUAWEI_USER_NAME")
    if not settings.HUAWEI_SYSTEM_CODE:
        missing.append("HUAWEI_SYSTEM_CODE")
    return missing


def huawei_configured() -> bool:
    return bool(
        settings.HUAWEI_ENABLED
        and settings.HUAWEI_USER_NAME
        and settings.HUAWEI_SYSTEM_CODE
    )


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
        snippet = (r.text or "").replace("\n", " ").strip()[:400]
        logger.warning("Huawei: login HTTP %s — %s", r.status_code, snippet or r.reason_phrase)
        raise HuaweiAuthError(f"login HTTP {r.status_code}: {snippet or r.reason_phrase or 'error'}")
    try:
        payload = r.json()
    except Exception:
        logger.warning("Huawei: login response is not JSON — %s", (r.text or "")[:400])
        raise HuaweiAuthError("invalid login response (not JSON)") from None
    if not payload.get("success"):
        msg = str(payload.get("message") or payload.get("msg") or "login failed")
        logger.warning("Huawei: login success=false — %s", msg[:400])
        raise HuaweiAuthError(msg)

    token = _xsrf_from_response(r)
    if not token:
        logger.warning("Huawei: login OK but no xsrf-token header in response")
        raise HuaweiAuthError("missing xsrf-token header after login")

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
            raise HuaweiAuthError("failed to obtain xsrf-token")
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
        snippet = (r.text or "").replace("\n", " ").strip()[:500]
        logger.warning("Huawei: POST %s HTTP %s — %s", path, r.status_code, snippet or r.reason_phrase)
        short = path.rstrip("/").split("/")[-1] or path.replace("/", "_")
        raise HuaweiUpstreamHttpError(short, int(r.status_code), snippet or (r.reason_phrase or ""))
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
        item: dict[str, str] = {"stationCode": code, "stationName": name}
        pdn = str(row.get("dn") or row.get("plantDn") or "").strip()
        if pdn:
            item["plantDn"] = pdn
        out.append(item)
    out.sort(key=lambda x: x["stationName"].lower())
    return out


async def _read_station_list_db(
    cache_key: str, *, stale_ok: bool = False
) -> Optional[tuple[list[dict[str, str]], float]]:
    try:
        async with async_session_factory() as session:
            row = await session.get(HuaweiStationListCache, cache_key)
        if row is None:
            return None
        saved_ts = row.saved_at.replace(tzinfo=timezone.utc).timestamp()
        if not stale_ok and time.time() - saved_ts > float(settings.HUAWEI_STATION_LIST_CACHE_TTL_SEC):
            return None
        items = row.items
        if not isinstance(items, list):
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
        return (out, saved_ts)
    except Exception as exc:
        logger.warning("Huawei: station list DB cache read failed — %s", exc)
        return None


async def _write_station_list_db(cache_key: str, items: list[dict[str, str]]) -> None:
    try:
        async with async_session_factory() as session:
            stmt = pg_insert(HuaweiStationListCache).values(
                cache_key=cache_key,
                saved_at=datetime.now(timezone.utc),
                items=items,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["cache_key"],
                set_={"saved_at": stmt.excluded.saved_at, "items": stmt.excluded.items},
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as exc:
        logger.warning("Huawei: station list DB cache write failed — %s", exc)


def _newer_station_cache(
    a: Optional[tuple[list[dict[str, str]], float]],
    b: Optional[tuple[list[dict[str, str]], float]],
) -> Optional[tuple[list[dict[str, str]], float]]:
    if a and b:
        return a if a[1] >= b[1] else b
    return a or b


async def list_stations(page_no: int = 1, page_size: int = 100) -> list[dict[str, str]]:
    if not huawei_configured():
        return []

    cache_key = f"{int(page_no)}:{int(page_size)}"
    now = time.time()
    ttl = float(settings.HUAWEI_STATION_LIST_CACHE_TTL_SEC)

    ram = _station_list_cache.get(cache_key)
    # RAM hit within TTL: skip Postgres read (same process already has newest snapshot).
    if ram and (now - ram[1]) <= ttl:
        db_stale: Optional[tuple[list[dict[str, str]], float]] = None
    else:
        db_stale = await _read_station_list_db(cache_key, stale_ok=True)
    best = _newer_station_cache(ram, db_stale)
    if best:
        _station_list_cache[cache_key] = best

    if now < _station_list_skip_api_until[0]:
        if best:
            src = "RAM" if ram and best is ram else "DB"
            logger.info("Huawei: list_stations — cooldown, %s cache (%s plants)", src, len(best[0]))
            return best[0]
        logger.warning(
            "Huawei: list_stations — cooldown %.0fs left, no station list cache",
            _station_list_skip_api_until[0] - now,
        )
        raise HuaweiRateLimitNoCacheError("northbound_rate_limit_no_station_list")

    if best and (now - best[1]) <= ttl:
        logger.info(
            "Huawei: list_stations — cache hit (%s plants, age %.0fs ≤ ttl %.0fs), skip getStationList",
            len(best[0]),
            now - best[1],
            ttl,
        )
        return best[0]

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
            db = await _read_station_list_db(cache_key, stale_ok=True)
            if db:
                out_d, saved_at = db
                _station_list_cache[cache_key] = db
                logger.warning(
                    "Huawei: getStationList failCode=407 — returning DB cache (age %.0fs, %s plants)",
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
        # Non-407 Northbound error — fall through to generic cache fallback below.
        raise
    except Exception:
        # Login failure, network error, etc. — return any available cache rather than 502.
        cached = _station_list_cache.get(cache_key)
        if cached:
            logger.warning(
                "Huawei: getStationList failed — returning RAM cache (age %.0fs, %s plants)",
                now - cached[1],
                len(cached[0]),
            )
            return cached[0]
        db = await _read_station_list_db(cache_key, stale_ok=True)
        if db:
            out_d, saved_at = db
            _station_list_cache[cache_key] = db
            logger.warning(
                "Huawei: getStationList failed — returning DB cache (age %.0fs, %s plants)",
                now - saved_at,
                len(out_d),
            )
            return out_d
        raise

    out = _station_list_from_payload(payload)
    _station_list_cache[cache_key] = (out, now)
    _station_list_skip_api_until[0] = 0.0
    await _write_station_list_db(cache_key, out)
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


def _normalize_maybe_kw_to_w(value: float, *, reference_w: Optional[float] = None) -> float:
    """
    Northbound often returns instant power in kW (e.g. ~13); some devices return watts (e.g. |v| > 500).

    When ``reference_w`` is set (typically inverter output for a grid meter), avoid treating small
    watt readings as kW — e.g. meter ``active_power=-240`` W must not become -240 kW.
    """
    if value != value:  # NaN
        return value
    if abs(value) >= 500:
        return value
    scaled = value * 1000.0
    if reference_w is not None:
        ref = abs(float(reference_w))
        if ref > 0 and abs(scaled) > max(25_000.0, ref * 15.0):
            return value
    return scaled


def _active_power_w_from_data_item_map(
    m: dict[str, Any], *, reference_w: Optional[float] = None
) -> Optional[float]:
    return _active_power_w_from_dev_dim(m, reference_w=reference_w)


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
                if _huawei_live_kpi_cache_fresh(cached[1], now=now):
                    logger.warning(
                        "Huawei: getStationRealKpi failCode=407 (rate limit) — returning cached data (age %.0fs)",
                        age,
                    )
                    return cached[0]
                logger.warning(
                    "Huawei: getStationRealKpi failCode=407 — cached data expired (age %.0fs > ttl %.0fs)",
                    age,
                    float(settings.HUAWEI_LIVE_KPI_CACHE_TTL_SEC),
                )
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


async def _read_power_devices_db(station_code: str) -> Optional[tuple[str, int, str, int]]:
    try:
        async with async_session_factory() as session:
            row = await session.get(HuaweiPowerDevicesCache, station_code)
        if row is None:
            return None
        mid = str(row.meter_dev_id).strip()
        iid = str(row.inverter_dev_id).strip()
        if not mid or not iid:
            return None
        return (mid, int(row.meter_dev_type_id), iid, int(row.inverter_dev_type_id))
    except Exception as exc:
        logger.warning("Huawei: power devices DB cache read failed — %s", exc)
        return None


async def _write_power_devices_db(station_code: str, quad: tuple[str, int, str, int]) -> None:
    mid, mt, iid, it = quad
    try:
        async with async_session_factory() as session:
            stmt = pg_insert(HuaweiPowerDevicesCache).values(
                station_code=station_code,
                saved_at=datetime.now(timezone.utc),
                meter_dev_id=mid,
                meter_dev_type_id=mt,
                inverter_dev_id=iid,
                inverter_dev_type_id=it,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["station_code"],
                set_={
                    "saved_at": stmt.excluded.saved_at,
                    "meter_dev_id": stmt.excluded.meter_dev_id,
                    "meter_dev_type_id": stmt.excluded.meter_dev_type_id,
                    "inverter_dev_id": stmt.excluded.inverter_dev_id,
                    "inverter_dev_type_id": stmt.excluded.inverter_dev_type_id,
                },
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as exc:
        logger.warning("Huawei: power devices DB cache write failed — %s", exc)


def _power_flow_body_for_storage(body: dict[str, Any]) -> dict[str, Any]:
    """Strip volatile keys before persisting (re-applied on read)."""
    return {k: v for k, v in body.items() if k not in ("northboundRateLimited", "cacheAgeSec")}


def _huawei_sample_age_ok(saved_at_ts: float, max_age_sec: float, *, now: Optional[float] = None) -> bool:
    ref = now if now is not None else time.time()
    return (ref - saved_at_ts) <= max_age_sec


def _huawei_live_kpi_cache_fresh(saved_at_ts: float, *, now: Optional[float] = None) -> bool:
    """True when a Northbound 407 fallback snapshot is still within the live KPI TTL (default 5 min)."""
    return _huawei_sample_age_ok(
        saved_at_ts, float(settings.HUAWEI_LIVE_KPI_CACHE_TTL_SEC), now=now
    )


def _power_flow_rate_limit_body(body: dict[str, Any], saved_at_ts: float, now: float) -> dict[str, Any]:
    out = _apply_huawei_power_flow_repairs(dict(body))
    out["northboundRateLimited"] = True
    out["cacheAgeSec"] = round(now - saved_at_ts, 1)
    _ensure_power_flow_export_flags(out)
    return out


def _power_flow_cached_response(
    body: dict[str, Any],
    saved_at_ts: float,
    now: float,
    *,
    northbound_rate_limited: bool,
) -> dict[str, Any]:
    out = _apply_huawei_power_flow_repairs(dict(body))
    out["northboundRateLimited"] = northbound_rate_limited
    out["cacheAgeSec"] = round(now - saved_at_ts, 1)
    _ensure_power_flow_export_flags(out)
    return out


async def _read_power_flow_db(station_code: str) -> Optional[tuple[dict[str, Any], float]]:
    st = (station_code or "").strip()
    if not st:
        return None
    try:
        async with async_session_factory() as session:
            row = await session.get(HuaweiPowerFlowCache, st)
        if row is None:
            return None
        raw = row.payload
        if not isinstance(raw, dict):
            return None
        saved_ts = row.saved_at.replace(tzinfo=timezone.utc).timestamp()
        return (_apply_huawei_power_flow_repairs(dict(raw)), saved_ts)
    except Exception as exc:
        logger.warning("Huawei: power flow DB cache read failed — %s", exc)
        return None


async def _write_power_flow_db(station_code: str, body: dict[str, Any]) -> None:
    st = (station_code or "").strip()
    if not st:
        return
    try:
        payload = _power_flow_body_for_storage(body)
        if payload.get("ok") is not True:
            return
        async with async_session_factory() as session:
            stmt = pg_insert(HuaweiPowerFlowCache).values(
                station_code=st,
                saved_at=datetime.now(timezone.utc),
                payload=payload,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["station_code"],
                set_={"saved_at": stmt.excluded.saved_at, "payload": stmt.excluded.payload},
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as exc:
        logger.warning("Huawei: power flow DB cache write failed — %s", exc)


def _parse_dev_list_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        inner = (
            data.get("list")
            or data.get("dataList")
            or data.get("deviceList")
            or data.get("devList")
            or []
        )
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
    raw = payload.get("list") or payload.get("dataList") or []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _meter_type_fallback_order() -> tuple[int, ...]:
    seen: set[int] = set()
    out: list[int] = []
    for x in (settings.HUAWEI_METER_DEV_TYPE_ID, 47, 17):
        if x not in seen:
            seen.add(x)
            out.append(x)
    return tuple(out)


def _pick_all_inverters_from_rows(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """All grid-tied inverters at the plant (multi-string / multi-inverter sites)."""
    inv_type = settings.HUAWEI_INVERTER_DEV_TYPE_ID
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for r in rows:
        if int(r.get("devTypeId") or 0) != inv_type:
            continue
        did = r.get("id")
        if did is None:
            continue
        sid = str(did)
        if sid in seen:
            continue
        seen.add(sid)
        out.append((sid, int(r["devTypeId"])))
    return out


def _pick_meter_inverter_from_rows(
    rows: list[dict[str, Any]],
) -> tuple[Optional[tuple[str, int]], Optional[tuple[str, int]]]:
    inv_type = settings.HUAWEI_INVERTER_DEV_TYPE_ID
    inv_row = None
    for r in rows:
        if int(r.get("devTypeId") or 0) == inv_type and r.get("id") is not None:
            inv_row = r
            break
    meter_row = None
    for mt in _meter_type_fallback_order():
        for r in rows:
            if int(r.get("devTypeId") or 0) == mt and r.get("id") is not None:
                meter_row = r
                break
        if meter_row:
            break
    inv_pair: Optional[tuple[str, int]] = None
    meter_pair: Optional[tuple[str, int]] = None
    if inv_row:
        inv_pair = (str(inv_row["id"]), int(inv_row["devTypeId"]))
    if meter_row:
        meter_pair = (str(meter_row["id"]), int(meter_row["devTypeId"]))
    return meter_pair, inv_pair


def _huawei_battery_dev_type_ids() -> set[int]:
    out: set[int] = set()
    raw = (settings.HUAWEI_BATTERY_DEV_TYPE_IDS or "").strip()
    for part in raw.split(","):
        p = part.strip()
        if p.isdigit():
            out.add(int(p))
    if not out:
        out.add(39)
        out.add(52)
    return out


def _has_battery_device_in_dev_list(rows: list[dict[str, Any]]) -> bool:
    battery_types = _huawei_battery_dev_type_ids()
    for r in rows:
        try:
            dt = int(r.get("devTypeId") or 0)
        except (TypeError, ValueError):
            continue
        if dt in battery_types:
            return True
    return False


def _ess_soc_percent_from_inverter_dim(dim: dict[str, Any]) -> Optional[float]:
    """Hybrid inverters sometimes expose SoC in getDevRealKpi ``dataItemMap`` (FusionSolar naming varies)."""
    if not dim:
        return None
    for k, v in dim.items():
        lk = str(k).lower()
        if "soc" not in lk or "cosoc" in lk:
            continue
        if any(x in lk for x in ("socket", "cosphi", "associate")):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f < 0 or f > 100:
            continue
        return f
    return None


async def _fetch_dev_list_rows(client: httpx.AsyncClient, station: str) -> list[dict[str, Any]]:
    payload = await _post_third_data(client, "/thirdData/getDevList", {"stationCodes": station})
    return _parse_dev_list_rows(payload)


async def _get_dev_list_rows_cached(client: httpx.AsyncClient, station: str) -> list[dict[str, Any]]:
    """Device topology from getDevList — refresh rarely to save Northbound quota for live KPI."""
    st = (station or "").strip()
    if not st:
        return []
    now = time.time()
    ttl = float(settings.HUAWEI_DEV_LIST_CACHE_TTL_SEC)
    hit = _dev_list_rows_cache.get(st)
    if hit and (now - hit[1]) <= ttl:
        return hit[0]
    rows = await _fetch_dev_list_rows(client, st)
    if rows:
        _dev_list_rows_cache[st] = (rows, now)
    return rows


async def _read_power_flow_from_sample(
    st: str,
    now: float,
    *,
    max_age_sec: Optional[float] = None,
) -> Optional[tuple[dict[str, Any], float]]:
    """Latest huawei_power_sample row within max_age_sec (default live KPI TTL)."""
    if not st:
        return None
    age_limit = float(max_age_sec if max_age_sec is not None else settings.HUAWEI_LIVE_KPI_CACHE_TTL_SEC)
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(HuaweiPowerSample)
                .where(HuaweiPowerSample.station_code == st)
                .order_by(HuaweiPowerSample.bucket_start.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
        if row is None:
            return None
        saved_ts = row.bucket_start.replace(tzinfo=timezone.utc).timestamp()
        if not _huawei_sample_age_ok(saved_ts, age_limit, now=now):
            return None
        if row.pv_power_w is None and row.grid_power_w is None and row.load_power_w is None:
            return None
        body: dict[str, Any] = {
            "ok": True,
            "configured": True,
            "stationCode": st,
            "pvPowerW": row.pv_power_w,
            "gridPowerW": row.grid_power_w,
            "loadPowerW": row.load_power_w,
            "hasBatteryKpi": False,
            "essSocPercent": None,
            "source": "huawei_power_sample",
        }
        return body, saved_ts
    except Exception as exc:
        logger.warning("Huawei: power sample fallback read failed — %s", exc)
        return None


def _power_flow_fresh_cached_body(st: str, now: float) -> Optional[dict[str, Any]]:
    """Return RAM power-flow snapshot when still within live KPI TTL (skip Northbound)."""
    cached = _power_flow_cache.get(st)
    if not cached:
        return None
    snap, saved_at = cached
    if snap.get("ok") is not True or not _huawei_live_kpi_cache_fresh(saved_at, now=now):
        return None
    body = _apply_huawei_power_flow_repairs(dict(snap))
    body["northboundRateLimited"] = False
    body["cacheAgeSec"] = round(now - saved_at, 1)
    _ensure_power_flow_export_flags(body)
    return body


async def _power_flow_rate_limit_fallback(
    st: str, now: float, *, stale_display: bool = False
) -> Optional[dict[str, Any]]:
    """RAM / DB cache, then power sample — optional stale sample up to 1h when Northbound is in 407."""
    sample_max = (
        float(settings.HUAWEI_POWER_SAMPLE_STALE_DISPLAY_SEC)
        if stale_display
        else float(settings.HUAWEI_LIVE_KPI_CACHE_TTL_SEC)
    )
    cached = _power_flow_cache.get(st)
    if cached:
        snap, saved_at = cached
        max_age = (
            float(settings.HUAWEI_POWER_SAMPLE_STALE_DISPLAY_SEC)
            if stale_display
            else float(settings.HUAWEI_LIVE_KPI_CACHE_TTL_SEC)
        )
        if _huawei_sample_age_ok(saved_at, max_age, now=now):
            stale = stale_display and not _huawei_live_kpi_cache_fresh(saved_at, now=now)
            return _power_flow_cached_response(
                snap, saved_at, now, northbound_rate_limited=stale
            )
    db_hit = await _read_power_flow_db(st)
    if db_hit:
        snap, saved_at = db_hit
        max_age = (
            float(settings.HUAWEI_POWER_SAMPLE_STALE_DISPLAY_SEC)
            if stale_display
            else float(settings.HUAWEI_LIVE_KPI_CACHE_TTL_SEC)
        )
        if _huawei_sample_age_ok(saved_at, max_age, now=now):
            _power_flow_cache[st] = (dict(snap), saved_at)
            stale = stale_display and not _huawei_live_kpi_cache_fresh(saved_at, now=now)
            return _power_flow_cached_response(
                snap, saved_at, now, northbound_rate_limited=stale
            )
    sample_hit = await _read_power_flow_from_sample(st, now, max_age_sec=sample_max)
    if sample_hit:
        snap, saved_at = sample_hit
        _power_flow_cache[st] = (dict(snap), saved_at)
        stale = not _huawei_live_kpi_cache_fresh(saved_at, now=now)
        body = _power_flow_cached_response(snap, saved_at, now, northbound_rate_limited=stale)
        body["source"] = "huawei_power_sample"
        return body
    return None


async def _power_flow_display_body(st: str, now: float) -> Optional[dict[str, Any]]:
    """
    UI path: never call FusionSolar Northbound — read RAM / DB / samples only.

    The background scheduler is the sole live Northbound caller (5-min quota).
    """
    fresh = _power_flow_fresh_cached_body(st, now)
    if fresh is not None:
        return fresh
    body = await _power_flow_rate_limit_fallback(st, now, stale_display=True)
    if body is not None:
        return body
    return None


async def _resolve_meter_inverter_pairs(
    client: httpx.AsyncClient, station: str
) -> tuple[Optional[tuple[str, int]], Optional[tuple[str, int]], list[dict[str, Any]]]:
    mid_e = (settings.HUAWEI_METER_DEV_ID or "").strip()
    iid_e = (settings.HUAWEI_INVERTER_DEV_ID or "").strip()
    if mid_e and iid_e:
        return (
            (mid_e, settings.HUAWEI_METER_DEV_TYPE_ID),
            (iid_e, settings.HUAWEI_INVERTER_DEV_TYPE_ID),
            [],
        )

    quad = _device_pair_cache.get(station)
    if not quad:
        db = await _read_power_devices_db(station)
        if db:
            _device_pair_cache[station] = db
            quad = db

    rows = await _get_dev_list_rows_cached(client, station)
    mp, ip = _pick_meter_inverter_from_rows(rows) if rows else (None, None)
    if mid_e:
        mp = (mid_e, settings.HUAWEI_METER_DEV_TYPE_ID)
    if iid_e:
        ip = (iid_e, settings.HUAWEI_INVERTER_DEV_TYPE_ID)
    if mp and ip:
        _device_pair_cache[station] = (mp[0], mp[1], ip[0], ip[1])
        await _write_power_devices_db(station, _device_pair_cache[station])
    return mp, ip, rows


def _active_power_w_from_dev_dim(
    dim: dict[str, Any], *, reference_w: Optional[float] = None
) -> Optional[float]:
    """Parse getDevRealKpi dataItemMap active / generation power into watts (same kW heuristic as plant KPI)."""
    if not dim:
        return None
    lower_map = {str(k).lower(): v for k, v in dim.items()}
    candidates_kw = (
        "active_power",
        "activepower",
        "inverter_power",
        "inverterpower",
        "generation_power",
        "total_active_power",
        "p_power",
        "realtime_power",
    )
    for ck in candidates_kw:
        for mk, mv in lower_map.items():
            if ck.replace("_", "") == mk.replace("_", "") or ck == mk:
                try:
                    v = float(mv)
                except (TypeError, ValueError):
                    continue
                if v != v:
                    continue
                return _normalize_maybe_kw_to_w(v, reference_w=reference_w)
    return None


def _pv_power_w_from_dev_dim(dim: dict[str, Any]) -> Optional[float]:
    """
    Prefer explicit PV-side KPIs for Huawei inverters.

    Hybrid inverters can report positive ``active_power`` while supplying load from the battery,
    which would otherwise look like fake solar generation after sunset.
    """
    if not dim:
        return None
    lower_map = {str(k).lower(): v for k, v in dim.items()}
    explicit_candidates = (
        "mppt_power",
        "mpptpower",
        "pv_power",
        "pvpower",
        "generation_power",
        "generationpower",
        "string_power",
        "stringpower",
        "total_pv_power",
        "totalpvpower",
        "solar_power",
        "solarpower",
    )
    for ck in explicit_candidates:
        wanted = ck.replace("_", "")
        for mk, mv in lower_map.items():
            if mk.replace("_", "") != wanted:
                continue
            try:
                v = float(mv)
            except (TypeError, ValueError):
                continue
            if v != v:
                continue
            return max(0.0, _normalize_maybe_kw_to_w(v))

    # Fallback for device models that expose only per-string DC voltage/current instead of PV power.
    pv_vi_sum_w = 0.0
    pv_vi_pairs = 0
    for mk, mv in lower_map.items():
        m = re.fullmatch(r"pv(\d+)_u", mk)
        if not m:
            continue
        try:
            volts = float(mv)
            amps = float(lower_map.get(f"pv{m.group(1)}_i"))
        except (TypeError, ValueError):
            continue
        if volts != volts or amps != amps or volts <= 0.0 or amps <= 0.0:
            continue
        pv_vi_sum_w += volts * amps
        pv_vi_pairs += 1
    if pv_vi_pairs > 0:
        return pv_vi_sum_w
    return None


def _normalize_meter_scale_if_implausible(
    meter_raw_w: Optional[float],
    inverter_raw_w: Optional[float],
) -> Optional[float]:
    """
    Fix occasional meter x1000 scaling artifacts for Huawei power flow snapshots.

    In some responses, meter power appears to already be in watts but still passes the
    generic kW->W heuristic and becomes 1000x too large (e.g. ~496 kW import while
    inverter output is ~44 kW). If the meter value is extremely high and dividing by
    1000 keeps it in a realistic range relative to inverter power, use the downscaled
    value.
    """
    if meter_raw_w is None:
        return None
    if inverter_raw_w is None:
        return meter_raw_w
    try:
        meter_abs = abs(float(meter_raw_w))
        inv_abs = abs(float(inverter_raw_w))
    except (TypeError, ValueError):
        return meter_raw_w

    # Trigger only for clearly implausible meter spikes.
    if inv_abs <= 0:
        if meter_abs < 300_000.0:
            return meter_raw_w
    elif meter_abs > max(50_000.0, inv_abs * 8.0 + 10_000.0):
        for divisor in (1000.0, 100.0):
            down = meter_abs / divisor
            plausibility_limit = max(inv_abs * 3.0 + 5_000.0, 200_000.0)
            if down <= plausibility_limit:
                sign = -1.0 if float(meter_raw_w) < 0.0 else 1.0
                return sign * down
    elif meter_abs < 300_000.0:
        return meter_raw_w

    meter_div_1k = meter_abs / 1000.0
    # Accept the correction only when the reduced value is still in a plausible envelope
    # for the current inverter power.
    plausibility_limit = max(200_000.0, inv_abs * 3.0 + 20_000.0)
    if meter_div_1k <= plausibility_limit:
        sign = -1.0 if float(meter_raw_w) < 0.0 else 1.0
        return sign * meter_div_1k
    return meter_raw_w


def _repair_huawei_power_flow_triplet(
    pv_w: Optional[float],
    grid_w: Optional[float],
    load_w: Optional[float],
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Fix legacy x1000 meter/load artifacts in RAM/DB cache and edge cases on live reads.

    Applies to every Huawei plant — no per-station allowlist.
    """
    try:
        pv = max(0.0, float(pv_w)) if pv_w is not None else None
        grid = float(grid_w) if grid_w is not None else None
        load = max(0.0, float(load_w)) if load_w is not None else None
    except (TypeError, ValueError):
        return pv_w, grid_w, load_w

    if pv is None or pv <= 0:
        return pv_w, grid_w, load_w

    if grid is not None and abs(grid) > max(100_000.0, pv * 12.0 + 10_000.0):
        scaled = grid / 1000.0
        if abs(scaled) <= max(50_000.0, pv * 3.0 + 5_000.0):
            grid = scaled

    if load is not None and load > max(100_000.0, pv * 4.0 + 15_000.0):
        if grid is not None:
            load = max(0.0, pv + max(0.0, grid))
        else:
            scaled_load = load / 1000.0
            if scaled_load <= max(50_000.0, pv * 3.0 + 5_000.0):
                load = scaled_load

    if load is not None and grid is not None and load > pv + max(0.0, grid) + max(15_000.0, pv * 0.5):
        load = max(0.0, pv + max(0.0, grid))

    return pv, grid, load


def _sum_inverter_power_from_dims(
    inv_dims: list[dict[str, Any]],
) -> tuple[Optional[float], Optional[float]]:
    """Sum PV (mppt) and AC output across all inverters at the grid tie point."""
    pv_sum = 0.0
    pv_count = 0
    inv_sum = 0.0
    inv_count = 0
    for dim in inv_dims:
        inv_raw = _active_power_w_from_dev_dim(dim)
        if inv_raw is not None:
            inv_sum += float(inv_raw)
            inv_count += 1
        pv_raw = _pv_power_w_from_dev_dim(dim)
        if pv_raw is not None:
            pv_sum += max(0.0, float(pv_raw))
            pv_count += 1
        elif inv_raw is not None:
            pv_sum += max(0.0, float(inv_raw))
            pv_count += 1
    pv_w = pv_sum if pv_count else None
    inv_w = inv_sum if inv_count else None
    return pv_w, inv_w


def _parse_huawei_power_flow_from_dims(
    meter_dim: dict[str, Any],
    inv_dims: list[dict[str, Any]],
    *,
    for_storage: bool = False,
) -> dict[str, Optional[float]]:
    """
    Instantaneous PV / grid / load (W) from getDevRealKpi meter + inverter dataItemMaps.

    ``inv_dims`` may contain one or many inverters (multi-inverter plants sum PV and AC output).
    Shared by live API, 5-minute snapshots, and cache repair — same rules for every plant.
    """
    dims = [d for d in inv_dims if d]
    if not dims:
        dims = [{}]
    pv_w, inv_raw = _sum_inverter_power_from_dims(dims)
    meter_raw = _active_power_w_from_dev_dim(meter_dim, reference_w=inv_raw)
    meter_raw = _normalize_meter_scale_if_implausible(meter_raw, inv_raw)

    grid_ui: Optional[float] = -float(meter_raw) if meter_raw is not None else None
    load_w: Optional[float] = None
    if inv_raw is not None and meter_raw is not None:
        load_w = max(0.0, float(inv_raw) - float(meter_raw))

    if not for_storage:
        grid_ui = _huawei_zero_grid_import_when_pv_meets_load(pv_w, load_w, grid_ui)

    pv_w, grid_ui, load_w = _repair_huawei_power_flow_triplet(pv_w, grid_ui, load_w)
    return {
        "pvPowerW": pv_w,
        "gridPowerW": grid_ui,
        "loadPowerW": load_w,
    }


def _apply_huawei_power_flow_repairs(body: dict[str, Any]) -> dict[str, Any]:
    """Repair cached power-flow snapshots in place (legacy bad meter scaling)."""
    if body.get("ok") is not True:
        return body
    pv, grid, load = _repair_huawei_power_flow_triplet(
        body.get("pvPowerW"),
        body.get("gridPowerW"),
        body.get("loadPowerW"),
    )
    body["pvPowerW"] = pv
    body["gridPowerW"] = grid
    body["loadPowerW"] = load
    return body


def _parse_dev_real_kpi_dims(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        dim = item.get("dataItemMap")
        if isinstance(dim, dict):
            out.append(dim)
    return out


async def _fetch_dev_real_kpi_dims(
    client: httpx.AsyncClient, dev_ids: list[str], dev_type_id: int
) -> list[dict[str, Any]]:
    ids = [str(d).strip() for d in dev_ids if str(d).strip()]
    if not ids:
        return []
    payload = await _post_third_data(
        client,
        "/thirdData/getDevRealKpi",
        {"devIds": ",".join(ids), "devTypeId": int(dev_type_id)},
    )
    dims = _parse_dev_real_kpi_dims(payload)
    if len(ids) == 1 or len(dims) >= len(ids):
        return dims

    # Some Northbound regions return only the first devId in a comma-separated batch.
    out: list[dict[str, Any]] = []
    for dev_id in ids:
        one_payload = await _post_third_data(
            client,
            "/thirdData/getDevRealKpi",
            {"devIds": dev_id, "devTypeId": int(dev_type_id)},
        )
        one_dims = _parse_dev_real_kpi_dims(one_payload)
        if one_dims:
            out.append(one_dims[0])
    return out


async def _fetch_dev_real_kpi_dim(
    client: httpx.AsyncClient, dev_id: str, dev_type_id: int
) -> dict[str, Any]:
    dims = await _fetch_dev_real_kpi_dims(client, [dev_id], dev_type_id)
    return dims[0] if dims else {}


def _inverter_pairs_for_power_flow(
    ip: Optional[tuple[str, int]],
    dev_rows: list[dict[str, Any]],
) -> list[tuple[str, int]]:
    """Resolve inverter device ids: env override → all from dev list → single cached pair."""
    iid_e = (settings.HUAWEI_INVERTER_DEV_ID or "").strip()
    if iid_e:
        return [(iid_e, settings.HUAWEI_INVERTER_DEV_TYPE_ID)]
    if dev_rows:
        pairs = _pick_all_inverters_from_rows(dev_rows)
        if pairs:
            return pairs
    return [ip] if ip else []


def _ess_soc_from_inverter_dims(inv_dims: list[dict[str, Any]]) -> Optional[float]:
    for dim in inv_dims:
        soc = _ess_soc_percent_from_inverter_dim(dim)
        if soc is not None:
            return soc
    return None


def _ensure_power_flow_export_flags(body: dict[str, Any]) -> None:
    """Backfill KPI snapshot fields for RAM or DB rows saved before these keys existed."""
    if body.get("ok") is not True:
        return
    if "hasBatteryKpi" not in body:
        body["hasBatteryKpi"] = False
    if "essSocPercent" not in body:
        body["essSocPercent"] = None


# Huawei-only: treat grid import as zero when PV and load are kW-scale and nearly equal.
# Mitigates Northbound kW-vs-W heuristics (_normalize_maybe_kw_to_w) blowing up small imports.
_HUAWEI_SELF_CONSUMPTION_MIN_PV_LOAD_W = 2500.0
_HUAWEI_SELF_CONSUMPTION_MAX_PV_LOAD_DIFF_W = 1000.0


def _huawei_zero_grid_import_when_pv_meets_load(
    pv_w: Optional[float],
    load_w: Optional[float],
    grid_ui: Optional[float],
) -> Optional[float]:
    """
    If PV and load are both ~3+ kW and within ~1 kW of each other, force grid import to 0 W.

    Keeps grid export (negative grid_ui) unchanged. Only applies to Huawei get_power_flow.
    """
    if grid_ui is None or grid_ui <= 0:
        return grid_ui
    if pv_w is None or load_w is None:
        return grid_ui
    try:
        pv_f = float(pv_w)
        load_f = float(load_w)
    except (TypeError, ValueError):
        return grid_ui
    if pv_f < _HUAWEI_SELF_CONSUMPTION_MIN_PV_LOAD_W or load_f < _HUAWEI_SELF_CONSUMPTION_MIN_PV_LOAD_W:
        return grid_ui
    if abs(pv_f - load_f) > _HUAWEI_SELF_CONSUMPTION_MAX_PV_LOAD_DIFF_W:
        return grid_ui
    return 0.0


async def get_power_flow(station_code: str, *, for_storage: bool = False) -> dict[str, Any]:
    """
    Instantaneous PV / grid / load (W) via getDevList + getDevRealKpi (meter + inverter).

    gridPowerW uses the same sign convention as Deye in PowerFlowPage: positive = grid import,
    negative = export. Huawei meter active_power is typically negative on import, so we negate it.
    loadPowerW = sum(inverter_active_power) - meter_active_power (both raw W from API).

    Multi-inverter plants sum every inverter from getDevList (one batched getDevRealKpi per type).

    When ``for_storage`` is True, grid import is left as read from the meter (no PV≈load zeroing).
    Use that for ``huawei_power_sample`` so month/year kWh totals are not understated.
    """
    st = (station_code or "").strip()
    if not st:
        return {"ok": False, "configured": bool(huawei_configured()), "reason": "missing_station"}
    if not huawei_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}

    now = time.time()
    if not for_storage:
        display = await _power_flow_display_body(st, now)
        if display is not None:
            return display
        return {
            "ok": False,
            "configured": True,
            "reason": "awaiting_fresh_sample",
            "stationCode": st,
        }

    global _northbound_power_flow_cooldown_until
    if now < _northbound_power_flow_cooldown_until:
        logger.info(
            "Huawei: get_power_flow scheduler — Northbound cooldown %.0fs left, skip %s",
            _northbound_power_flow_cooldown_until - now,
            st,
        )
        return {
            "ok": False,
            "configured": True,
            "northboundRateLimited": True,
            "reason": "rate_limit_cooldown",
            "stationCode": st,
        }

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            mp, ip, dev_rows = await _resolve_meter_inverter_pairs(client, st)
            inv_pairs = _inverter_pairs_for_power_flow(ip, dev_rows)
            if not mp or not inv_pairs:
                return {
                    "ok": False,
                    "configured": True,
                    "reason": "no_meter_inverter",
                    "stationCode": st,
                }
            meter_dim = await _fetch_dev_real_kpi_dim(client, mp[0], mp[1])
            inv_type_id = inv_pairs[0][1]
            inv_ids = [p[0] for p in inv_pairs]
            inv_dims = await _fetch_dev_real_kpi_dims(client, inv_ids, inv_type_id)

            metrics = _parse_huawei_power_flow_from_dims(
                meter_dim, inv_dims, for_storage=for_storage
            )
            pv_w = metrics["pvPowerW"]
            grid_ui = metrics["gridPowerW"]
            load_w = metrics["loadPowerW"]

            has_battery_kpi = _has_battery_device_in_dev_list(dev_rows) if dev_rows else False
            ess_soc = _ess_soc_from_inverter_dims(inv_dims)

            out: dict[str, Any] = {
                "ok": True,
                "configured": True,
                "stationCode": st,
                "pvPowerW": pv_w,
                "gridPowerW": grid_ui,
                "loadPowerW": load_w,
                "northboundRateLimited": False,
                "hasBatteryKpi": has_battery_kpi,
                "essSocPercent": ess_soc,
            }
            _power_flow_cache[st] = (dict(out), now)
            await _write_power_flow_db(st, out)
            return dict(out)
    except HuaweiNorthboundError as exc:
        if exc.fail_code == _FAIL_CODE_RATE_LIMIT:
            _northbound_power_flow_cooldown_until = now + float(
                settings.HUAWEI_NORTHBOUND_COOLDOWN_AFTER_407_SEC
            )
            body = await _power_flow_rate_limit_fallback(st, now, stale_display=True)
            if body is not None:
                return body
            logger.warning(
                "Huawei: get_power_flow failCode=407 — no fresh cache or power sample (ttl %.0fs)",
                float(settings.HUAWEI_LIVE_KPI_CACHE_TTL_SEC),
            )
            return {
                "ok": False,
                "configured": True,
                "northboundRateLimited": True,
                "reason": "rate_limit",
                "stationCode": st,
            }
        raise


def _parse_date_iso_energy(date_iso: str) -> Optional[date]:
    s = (date_iso or "").strip()
    if len(s) != 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _kpi_collect_time_ms(d: date, period: str) -> int:
    """Unix timestamp in ms for the start of the period (UTC midnight)."""
    if period == "day":
        return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
    if period == "month":
        return int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    # year
    return int(datetime(d.year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _kpi_endpoint(period: str) -> str:
    if period == "day":
        return "/thirdData/getKpiStationDay"
    if period == "month":
        return "/thirdData/getKpiStationMonth"
    return "/thirdData/getKpiStationYear"


def _extract_energy_row(it: dict[str, Any]) -> dict[str, Any]:
    code = str(it.get("stationCode") or "").strip()
    dim = it.get("dataItemMap")
    if not isinstance(dim, dict):
        return {"stationCode": code}

    def fv(*keys: str) -> Optional[float]:
        return _float_from_map(dim, *keys)

    pv_kwh = fv("inverter_power", "inverter_cap")
    cons_kwh = fv("consumption_energy")
    grid_export_kwh = fv("ongrid_power")
    grid_import_kwh = fv("buyEnergy", "buy_power")
    self_cons_kwh = fv("use_power")

    # Huawei sometimes omits consumption_energy (notably on getKpiStationMonth/Year
    # for stations without an explicit consumption meter). Reconstruct it from
    # the parts the API does return so the UI can always show all three rows
    # (Consumption / PV / Grid).
    #   consumption = self-consumption + grid import
    #   self-consumption = pv - grid export  (when not reported directly)
    if cons_kwh is None:
        if self_cons_kwh is not None and grid_import_kwh is not None:
            cons_kwh = float(self_cons_kwh) + float(grid_import_kwh)
        elif (
            pv_kwh is not None
            and grid_export_kwh is not None
            and grid_import_kwh is not None
        ):
            cons_kwh = max(0.0, float(pv_kwh) - float(grid_export_kwh)) + float(grid_import_kwh)

    return {
        "stationCode": code,
        "pvKwh": pv_kwh,
        "consumptionKwh": cons_kwh,
        "gridExportKwh": grid_export_kwh,
        "gridImportKwh": grid_import_kwh,
        "selfConsumptionKwh": self_cons_kwh,
        "radiationKwhM2": fv("radiation_intensity"),
        "theoryKwh": fv("theory_power"),
        "perpowerRatioKwhKwp": fv("perpower_ratio"),
    }


async def get_station_energy_kpi(station_codes: str, period: str, date_iso: str) -> dict[str, Any]:
    """
    Fetch energy KPIs directly from Huawei Northbound — no DB storage.

    period: 'day' | 'month' | 'year'
    date_iso: YYYY-MM-DD  (selects the calendar period)
    Returns {"ok": True, "period": period, "items": [...]} or {"ok": False, "reason": ...}
    """
    codes = ",".join(s.strip() for s in (station_codes or "").split(",") if s.strip())
    if not codes:
        return {"ok": False, "reason": "missing_station"}
    if period not in ("day", "month", "year"):
        return {"ok": False, "reason": "invalid_period"}

    d = _parse_date_iso_energy(date_iso)
    if d is None:
        return {"ok": False, "reason": "invalid_date"}

    collect_time = _kpi_collect_time_ms(d, period)
    endpoint = _kpi_endpoint(period)

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            payload = await _post_third_data(
                client,
                endpoint,
                {"stationCodes": codes, "collectTime": collect_time},
            )
    except HuaweiNorthboundError as exc:
        if exc.fail_code == _FAIL_CODE_RATE_LIMIT:
            return {"ok": False, "configured": True, "northboundRateLimited": True, "reason": "rate_limit"}
        raise

    items = _parse_kpi_items(payload)
    rows = [_extract_energy_row(it) for it in items if isinstance(it, dict)]
    return {"ok": True, "period": period, "collectTimeMs": collect_time, "items": rows}
