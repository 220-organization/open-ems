"""Deye Cloud Open API v1 — token + station/inverter list (same auth flow as Java DeyeAuth)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Optional

import httpx

from app import settings

logger = logging.getLogger(__name__)

_token: Optional[str] = None
_token_expires_at: float = 0.0
_lock = asyncio.Lock()

# Inverter SoC % from POST /device/latest — TTL cache (seconds).
_soc_cache: dict[str, tuple[Optional[float], float]] = {}
_soc_lock = asyncio.Lock()
SOC_CACHE_TTL_SEC = 300.0


def deye_missing_env_names() -> list[str]:
    """Env var names that are unset (for startup / request logs only; no secrets)."""
    missing: list[str] = []
    if not settings.DEYE_APP_ID:
        missing.append("DEYE_APP_ID")
    if not settings.DEYE_APP_SECRET:
        missing.append("DEYE_APP_SECRET")
    if not settings.DEYE_EMAIL:
        missing.append("DEYE_EMAIL")
    if not settings.DEYE_PASSWORD:
        missing.append("DEYE_PASSWORD")
    return missing


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
            logger.debug("Deye: using cached access token")
            return _token
        if not deye_configured():
            raise RuntimeError("Deye API credentials not configured")

        url = f"{settings.DEYE_API_BASE_URL}/account/token"
        logger.info("Deye: requesting access token from %s/account/token", settings.DEYE_API_BASE_URL)
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
        if r.status_code >= 400:
            logger.warning(
                "Deye: token HTTP %s — %s",
                r.status_code,
                (r.text or "")[:500],
            )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            msg = str(data.get("msg") or "Deye token request failed")
            logger.warning("Deye: token rejected success=false msg=%s", msg[:500])
            raise RuntimeError(msg)

        access = data.get("accessToken")
        expires_in = int(data.get("expiresIn") or 0)
        if not access or expires_in <= 0:
            logger.warning("Deye: token response missing accessToken or expiresIn")
            raise RuntimeError("Invalid Deye token response")

        _token = access
        _token_expires_at = now + expires_in
        logger.info("Deye: access token OK, expires_in=%ss", expires_in)
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
    # listWithDevice returns deviceListItems (newer); older samples use deviceList / devices.
    dl = st.get("deviceListItems") or st.get("deviceList") or st.get("devices") or []
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


def _log_list_with_device_round_trip(page: int, base: str, req_body: dict[str, Any], data: Any) -> None:
    """Log request/response shape for debugging empty inverter lists (no secrets)."""
    url = f"{base}/station/listWithDevice"
    logger.info("Deye: listWithDevice REQUEST POST %s body=%s", url, json.dumps(req_body))

    if not isinstance(data, dict):
        logger.info(
            "Deye: listWithDevice RESPONSE page=%s parsed_type=%s raw_text_trunc=%s",
            page,
            type(data).__name__,
            str(data)[:500],
        )
        return

    top_keys = sorted(data.keys())
    inner = data.get("data") if isinstance(data.get("data"), dict) else None
    stations = _collect_station_list(data)
    total = data.get("total")
    if isinstance(inner, dict):
        total = total if total is not None else inner.get("total") or inner.get("totalCount")

    logger.info(
        "Deye: listWithDevice RESPONSE page=%s success=%s top_keys=%s total=%s stationList_len=%s",
        page,
        data.get("success"),
        top_keys,
        total,
        len(stations),
    )

    if stations:
        st0 = stations[0]
        devs = st0.get("deviceListItems") or st0.get("deviceList") or st0.get("devices") or []
        n_dev = len(devs) if isinstance(devs, list) else -1
        logger.info(
            "Deye: listWithDevice sample station[0] keys=%s deviceList_len=%s",
            sorted(st0.keys()),
            n_dev,
        )
        if isinstance(devs, list) and devs and isinstance(devs[0], dict):
            d0 = devs[0]
            logger.info(
                "Deye: listWithDevice sample device[0] keys=%s deviceType=%r has_sn=%s",
                sorted(d0.keys()),
                d0.get("deviceType"),
                bool(d0.get("deviceSn") or d0.get("deviceSN") or d0.get("serialNumber")),
            )
    else:
        if isinstance(inner, dict):
            logger.info(
                "Deye: listWithDevice empty stationList — data.inner_keys=%s",
                sorted(inner.keys()),
            )
        try:
            snippet = json.dumps(data, default=str)[:2000]
            logger.info("Deye: listWithDevice RESPONSE json_trunc=%s", snippet)
        except Exception:
            logger.info("Deye: listWithDevice RESPONSE (could not json-dump)")


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
    t0 = time.perf_counter()
    pages_fetched = 0
    async with httpx.AsyncClient(timeout=45.0) as client:
        token = await _ensure_token(client)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        items: list[dict[str, str]] = []
        seen: set[str] = set()
        page = 1
        # Deye Open API rejects size > 50 (e.g. msg "size max 50", code 2101006).
        page_size = 50

        logger.info("Deye: fetching inverter list (listWithDevice, page_size=%s)", page_size)

        while page <= 100:
            req_body = {
                "page": page,
                "size": page_size,
                "deviceType": "INVERTER",
            }
            list_url = f"{base}/station/listWithDevice"
            r = await client.post(list_url, headers=headers, json=req_body)
            pages_fetched += 1
            logger.info(
                "Deye: listWithDevice HTTP status=%s page=%s url=%s",
                r.status_code,
                page,
                list_url,
            )
            if r.status_code >= 400:
                logger.warning(
                    "Deye: listWithDevice page=%s HTTP %s — %s",
                    page,
                    r.status_code,
                    (r.text or "")[:800],
                )
            r.raise_for_status()
            data = r.json()
            _log_list_with_device_round_trip(page, base, req_body, data)

            if isinstance(data, dict) and data.get("success") is False:
                msg = str(data.get("msg") or "Deye station list failed")
                logger.warning("Deye: listWithDevice success=false page=%s msg=%s", page, msg[:400])
                raise RuntimeError(msg)

            stations = _collect_station_list(data if isinstance(data, dict) else {})
            logger.info("Deye: listWithDevice page=%s parsed_station_count=%s", page, len(stations))
            if not stations:
                break

            page_inverter_count = 0
            for st in stations:
                for dev in _devices_from_station(st):
                    sn = str(dev.get("deviceSn") or dev.get("serialNumber") or "")
                    if not sn or sn in seen:
                        continue
                    seen.add(sn)
                    items.append({"deviceSn": sn, "label": _station_label(st, dev)})
                    page_inverter_count += 1
            logger.info(
                "Deye: listWithDevice page=%s new_inverters_added=%s (total_so_far=%s)",
                page,
                page_inverter_count,
                len(items),
            )

            if len(stations) < page_size:
                break
            page += 1

        items.sort(key=lambda x: x["label"].lower())
        elapsed = time.perf_counter() - t0
        logger.info(
            "Deye: inverter list done — %s device(s), %s page(s), %.2fs",
            len(items),
            pages_fetched,
            elapsed,
        )
        return items


_SOC_KEYS = frozenset({"SOC", "BMS_SOC", "BATTERY_SOC"})


def _soc_percent_from_device_data_entry(dev_entry: Any) -> Optional[float]:
    if not isinstance(dev_entry, dict):
        return None
    dl = dev_entry.get("dataList")
    if not isinstance(dl, list):
        return None
    for row in dl:
        if not isinstance(row, dict):
            continue
        raw_key = str(row.get("key") or "").strip().upper()
        if raw_key not in _SOC_KEYS:
            continue
        try:
            return float(row.get("value"))
        except (TypeError, ValueError):
            continue
    return None


async def _post_latest_soc_map(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    base: str,
    sns: list[str],
) -> dict[str, Optional[float]]:
    """POST /device/latest for up to 10 serials (Open API limit). Returns sn -> % or None."""
    if not sns:
        return {}
    url = f"{base.rstrip('/')}/device/latest"
    out: dict[str, Optional[float]] = {sn: None for sn in sns}
    r = await client.post(url, headers=headers, json={"deviceList": sns})
    if r.status_code >= 400:
        logger.warning(
            "Deye: device/latest HTTP %s batch_size=%s — %s",
            r.status_code,
            len(sns),
            (r.text or "")[:400],
        )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        return out
    if data.get("success") is False:
        logger.warning(
            "Deye: device/latest success=false batch_size=%s msg=%s",
            len(sns),
            str(data.get("msg"))[:200],
        )
        return out
    ddl = data.get("deviceDataList")
    if not isinstance(ddl, list):
        return out

    for i, entry in enumerate(ddl):
        soc = _soc_percent_from_device_data_entry(entry)
        if soc is None:
            continue
        sn_hint: Optional[str] = None
        if isinstance(entry, dict):
            for k in ("deviceSn", "deviceSN", "serialNumber"):
                raw = entry.get(k)
                if raw is not None:
                    c = str(raw).strip()
                    if c.isdigit() and c in out:
                        sn_hint = c
                        break
        target = sn_hint if sn_hint is not None else (sns[i] if i < len(sns) else None)
        if target is not None and target in out:
            out[target] = soc
    return out


async def get_soc_map_cached(device_sns: list[str]) -> dict[str, Optional[float]]:
    """
    Map device serial -> SoC % using in-memory TTL cache (SOC_CACHE_TTL_SEC).
    Batches POST /device/latest in chunks of up to 10.
    """
    if not deye_configured():
        return {}

    unique: list[str] = []
    seen: set[str] = set()
    for s in device_sns:
        sn = str(s or "").strip()
        if not sn.isdigit() or sn in seen:
            continue
        seen.add(sn)
        unique.append(sn)
    if not unique:
        return {}

    now = time.monotonic()
    result: dict[str, Optional[float]] = {}
    to_fetch: list[str] = []

    async with _soc_lock:
        now = time.monotonic()
        for sn in unique:
            hit = _soc_cache.get(sn)
            if hit is not None:
                val, ts = hit
                if now - ts < SOC_CACHE_TTL_SEC:
                    result[sn] = val
                    continue
            to_fetch.append(sn)

    merged_fetch: dict[str, Optional[float]] = {}
    if to_fetch:
        base = settings.DEYE_API_BASE_URL.rstrip("/")
        async with httpx.AsyncClient(timeout=45.0) as client:
            token = await _ensure_token(client)
            hdrs = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
            for off in range(0, len(to_fetch), 10):
                chunk = to_fetch[off : off + 10]
                part = await _post_latest_soc_map(client, hdrs, base, chunk)
                merged_fetch.update(part)

        fetch_time = time.monotonic()
        async with _soc_lock:
            for sn, soc in merged_fetch.items():
                _soc_cache[sn] = (soc, fetch_time)

    for sn in unique:
        if sn in result:
            continue
        result[sn] = merged_fetch.get(sn)

    return result


async def fetch_device_soc_percent(device_sn: str) -> Optional[float]:
    """Single-serial SoC; uses the same TTL cache as get_soc_map_cached."""
    sn = (device_sn or "").strip()
    if not sn:
        return None
    m = await get_soc_map_cached([sn])
    return m.get(sn)
