"""Huawei FusionSolar SmartPVMS Northbound Open API — session + plant list + real-time KPI (read-only)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select

from app import settings
from app.db import async_session_factory
from app.models import HuaweiPowerDevicesCache, HuaweiPowerFlowCache, HuaweiStationListCache

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


def _normalize_maybe_kw_to_w(value: float) -> float:
    """Northbound often returns instant power in kW (e.g. ~28); some devices return watts (e.g. |v| > 500)."""
    if value != value:  # NaN
        return value
    if abs(value) < 500:
        return value * 1000.0
    return value


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
                return _normalize_maybe_kw_to_w(v)
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
        return (dict(raw), saved_ts)
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
    return []


def _meter_type_fallback_order() -> tuple[int, ...]:
    seen: set[int] = set()
    out: list[int] = []
    for x in (settings.HUAWEI_METER_DEV_TYPE_ID, 47, 17):
        if x not in seen:
            seen.add(x)
            out.append(x)
    return tuple(out)


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


async def _resolve_meter_inverter_pairs(
    client: httpx.AsyncClient, station: str
) -> tuple[Optional[tuple[str, int]], Optional[tuple[str, int]]]:
    mid_e = (settings.HUAWEI_METER_DEV_ID or "").strip()
    iid_e = (settings.HUAWEI_INVERTER_DEV_ID or "").strip()
    if mid_e and iid_e:
        return (
            (mid_e, settings.HUAWEI_METER_DEV_TYPE_ID),
            (iid_e, settings.HUAWEI_INVERTER_DEV_TYPE_ID),
        )

    quad = _device_pair_cache.get(station)
    if not quad:
        db = await _read_power_devices_db(station)
        if db:
            _device_pair_cache[station] = db
            quad = db

    need_dev_list = quad is None or bool(mid_e) or bool(iid_e)
    if not need_dev_list:
        mid2, mt2, iid2, it2 = quad
        return (mid2, mt2), (iid2, it2)

    payload = await _post_third_data(client, "/thirdData/getDevList", {"stationCodes": station})
    rows = _parse_dev_list_rows(payload)
    mp, ip = _pick_meter_inverter_from_rows(rows)
    if mid_e:
        mp = (mid_e, settings.HUAWEI_METER_DEV_TYPE_ID)
    if iid_e:
        ip = (iid_e, settings.HUAWEI_INVERTER_DEV_TYPE_ID)
    if mp and ip:
        _device_pair_cache[station] = (mp[0], mp[1], ip[0], ip[1])
        await _write_power_devices_db(station, _device_pair_cache[station])
    return mp, ip


def _active_power_w_from_dev_dim(dim: dict[str, Any]) -> Optional[float]:
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
                return _normalize_maybe_kw_to_w(v)
    return None


async def _fetch_dev_real_kpi_dim(
    client: httpx.AsyncClient, dev_id: str, dev_type_id: int
) -> dict[str, Any]:
    payload = await _post_third_data(
        client,
        "/thirdData/getDevRealKpi",
        {"devIds": str(dev_id), "devTypeId": int(dev_type_id)},
    )
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            dim = first.get("dataItemMap")
            if isinstance(dim, dict):
                return dim
    return {}


async def get_power_flow(station_code: str) -> dict[str, Any]:
    """
    Instantaneous PV / grid / load (W) via getDevList + getDevRealKpi (meter + inverter).

    gridPowerW uses the same sign convention as Deye in PowerFlowPage: positive = grid import,
    negative = export. Huawei meter active_power is typically negative on import, so we negate it.
    loadPowerW = inverter_active_power - meter_active_power (both raw W from API).
    """
    st = (station_code or "").strip()
    if not st:
        return {"ok": False, "configured": bool(huawei_configured()), "reason": "missing_station"}
    if not huawei_configured():
        return {"ok": False, "configured": False, "reason": "not_configured"}

    now = time.time()
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            mp, ip = await _resolve_meter_inverter_pairs(client, st)
            if not mp or not ip:
                return {
                    "ok": False,
                    "configured": True,
                    "reason": "no_meter_inverter",
                    "stationCode": st,
                }
            meter_dim = await _fetch_dev_real_kpi_dim(client, mp[0], mp[1])
            inv_dim = await _fetch_dev_real_kpi_dim(client, ip[0], ip[1])
    except HuaweiNorthboundError as exc:
        if exc.fail_code == _FAIL_CODE_RATE_LIMIT:
            cached = _power_flow_cache.get(st)
            if cached:
                body = dict(cached[0])
                body["northboundRateLimited"] = True
                body["cacheAgeSec"] = round(now - cached[1], 1)
                return body
            db_hit = await _read_power_flow_db(st)
            if db_hit:
                snap, saved_at = db_hit
                _power_flow_cache[st] = (dict(snap), saved_at)
                body = dict(snap)
                body["northboundRateLimited"] = True
                body["cacheAgeSec"] = round(now - saved_at, 1)
                return body
            return {
                "ok": False,
                "configured": True,
                "northboundRateLimited": True,
                "reason": "rate_limit",
                "stationCode": st,
            }
        raise

    meter_raw = _active_power_w_from_dev_dim(meter_dim)
    inv_raw = _active_power_w_from_dev_dim(inv_dim)

    pv_w = max(0.0, float(inv_raw)) if inv_raw is not None else None
    grid_ui: Optional[float] = -float(meter_raw) if meter_raw is not None else None
    load_w: Optional[float] = None
    if inv_raw is not None and meter_raw is not None:
        load_w = max(0.0, float(inv_raw) - float(meter_raw))

    out: dict[str, Any] = {
        "ok": True,
        "configured": True,
        "stationCode": st,
        "pvPowerW": pv_w,
        "gridPowerW": grid_ui,
        "loadPowerW": load_w,
        "northboundRateLimited": False,
    }
    _power_flow_cache[st] = (dict(out), now)
    await _write_power_flow_db(st, out)
    return dict(out)
