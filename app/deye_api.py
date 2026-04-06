"""Deye Cloud Open API v1 — token + station/inverter list (same auth flow as Java DeyeAuth)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app import settings
from app.deye_flow_balance import device_uses_flow_balance, flow_balance_grid_w
from app.deye_inverter_pin import assert_inverter_write_pin, strip_inverter_pin_suffix

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_token: Optional[str] = None
_token_expires_at: float = 0.0
_lock = asyncio.Lock()

# Inverter SoC %; live metrics from POST /device/latest:
# battery (W signed), load (W magnitude), PV (W production), grid (W signed import/export).
_soc_cache: dict[str, tuple[Optional[float], float]] = {}
# battery W, load W, pv W, grid W, grid frequency Hz, monotonic fetch time
_live_cache: dict[
    str,
    tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], float],
] = {}
_soc_lock = asyncio.Lock()
SOC_CACHE_TTL_SEC = 300.0
ESS_POWER_CACHE_TTL_SEC = 25.0


def _finalize_live_metrics_for_sn(
    sn: str,
    bat: Optional[float],
    load_w: Optional[float],
    pv_w: Optional[float],
    grid_w: Optional[float],
    freq_hz: Optional[float],
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Override grid with load − k×pv − battery for sites where Deye grid register is wrong."""
    if device_uses_flow_balance(sn):
        derived = flow_balance_grid_w(load_w, pv_w, bat)
        if derived is not None:
            grid_w = derived
    return bat, load_w, pv_w, grid_w, freq_hz


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


def _coerce_geo_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _parse_geo_from_dict(d: dict[str, Any], _depth: int = 0) -> tuple[Optional[float], Optional[float]]:
    """Best-effort lat/lon from Deye station or device payloads (field names vary by API version)."""
    if not d or _depth > 4:
        return None, None
    lat_keys = (
        "latitude",
        "lat",
        "stationLat",
        "stationLatitude",
        "geoLat",
        "locationLat",
        "latVal",
    )
    lon_keys = (
        "longitude",
        "lng",
        "lon",
        "stationLng",
        "stationLongitude",
        "geoLng",
        "locationLng",
        "lngVal",
    )
    lat: Optional[float] = None
    lon: Optional[float] = None
    for k in lat_keys:
        if k in d:
            lat = _coerce_geo_float(d.get(k))
            if lat is not None and -90.0 <= lat <= 90.0:
                break
            lat = None
    for k in lon_keys:
        if k in d:
            lon = _coerce_geo_float(d.get(k))
            if lon is not None and -180.0 <= lon <= 180.0:
                break
            lon = None
    nested = d.get("location") or d.get("geo") or d.get("position")
    if isinstance(nested, dict) and (lat is None or lon is None):
        nlat, nlon = _parse_geo_from_dict(nested, _depth + 1)
        if lat is None:
            lat = nlat
        if lon is None:
            lon = nlon
    return lat, lon


def _compose_inverter_label(pname: str, dname: str, sn: str) -> str:
    """Build list label from plant + device display names (already PIN-stripped by caller)."""
    p = (pname or "").strip()
    d = (dname or "").strip()
    s = (sn or "").strip()
    if p and d:
        return f"{p} — {d}"
    if p:
        return f"{p} — {s}" if s else p
    return d or s or "inverter"


@dataclass(frozen=True)
class _InverterListRow:
    device_sn: str
    label: str
    pin: Optional[str]
    lat: Optional[float]
    lon: Optional[float]


async def _list_inverter_rows() -> list[_InverterListRow]:
    """Raw inverter rows including optional PIN parsed from device name (not exposed in list API)."""
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

        items: list[_InverterListRow] = []
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
                    pname_raw = str(
                        st.get("stationName") or st.get("name") or st.get("title") or "",
                    ).strip()
                    pname_show, pin_from_plant = strip_inverter_pin_suffix(pname_raw)
                    dname_raw = str(dev.get("deviceName") or dev.get("name") or "").strip()
                    dname_show, pin_from_device = strip_inverter_pin_suffix(dname_raw)
                    pin_code = pin_from_device if pin_from_device is not None else pin_from_plant
                    label = _compose_inverter_label(pname_show, dname_show, sn)
                    st_lat, st_lon = _parse_geo_from_dict(st)
                    dev_lat, dev_lon = _parse_geo_from_dict(dev)
                    lat = dev_lat if dev_lat is not None else st_lat
                    lon = dev_lon if dev_lon is not None else st_lon
                    items.append(_InverterListRow(sn, label, pin_code, lat, lon))
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

        items.sort(key=lambda x: x.label.lower())
        elapsed = time.perf_counter() - t0
        logger.info(
            "Deye: inverter list done — %s device(s), %s page(s), %.2fs",
            len(items),
            pages_fetched,
            elapsed,
        )
        return items


async def list_inverter_devices() -> list[dict[str, Any]]:
    """Inverters from POST /station/listWithDevice (plant list + device list, same data as cloud plant UI)."""
    rows = await _list_inverter_rows()
    return [
        {"deviceSn": r.device_sn, "label": r.label, "pinRequired": r.pin is not None} for r in rows
    ]


async def get_inverter_station_coordinates(device_sn: str) -> tuple[Optional[float], Optional[float]]:
    """Lat/lon from Deye listWithDevice (station or device). Not exposed via list_inverter_devices()."""
    sn = (device_sn or "").strip()
    if not sn:
        return None, None
    rows = await _list_inverter_rows()
    row = next((r for r in rows if r.device_sn == sn), None)
    if row is None:
        return None, None
    return row.lat, row.lon


async def assert_deye_write_pin(device_sn: str, pin: Optional[str]) -> None:
    """Require matching PIN when the inverter device name encodes one (trailing `` pin<digits>``)."""
    sn = (device_sn or "").strip()
    if not sn:
        return
    rows = await _list_inverter_rows()
    row = next((r for r in rows if r.device_sn == sn), None)
    if row is None:
        return
    assert_inverter_write_pin(pin, row.pin, row.label)


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


def _row_value_to_watts(row: dict) -> Optional[float]:
    """Numeric register value as watts (handles kW unit when present)."""
    try:
        v = float(row.get("value"))
    except (TypeError, ValueError):
        return None
    unit = str(row.get("unit") or "").upper().replace(" ", "")
    if "KWH" in unit:
        return None
    if "KW" in unit:
        return v * 1000.0
    return v


def _metric_key(raw: Any) -> str:
    """Normalize metric key to UPPER_SNAKE, preserving letters/digits only."""
    s = str(raw or "").strip().upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    return s.strip("_")


def _battery_signed_watts_from_data_list(dl: Any) -> Optional[float]:
    """
    Signed battery power in watts: positive = discharging (from battery), negative = charging.
    Parsed from Deye device/latest dataList keys (firmware-dependent).
    """
    if not isinstance(dl, list):
        return None
    by_key: dict[str, float] = {}
    for row in dl:
        if not isinstance(row, dict):
            continue
        k = _metric_key(row.get("key"))
        w = _row_value_to_watts(row)
        if w is None:
            continue
        by_key[k] = w

    if "BATTERY_POWER" in by_key:
        return by_key["BATTERY_POWER"]
    if "BAT_POWER" in by_key:
        return by_key["BAT_POWER"]
    if "ESS_POWER" in by_key:
        return by_key["ESS_POWER"]
    if "BATTERY_OUTPUT_POWER" in by_key:
        return abs(by_key["BATTERY_OUTPUT_POWER"])
    if "BATTERY_INPUT_POWER" in by_key:
        return -abs(by_key["BATTERY_INPUT_POWER"])

    charge_keys = (
        "BATTERY_CHARGE_POWER",
        "BAT_CHARGE_POWER",
        "CHARGE_POWER",
        "BATTERY_CHARGING_POWER",
        "GRID_TO_BATTERY_POWER",
        "GRID_CHARGE_POWER",
    )
    discharge_keys = (
        "BATTERY_DISCHARGE_POWER",
        "BAT_DISCHARGE_POWER",
        "DISCHARGE_POWER",
        "BATTERY_DISCHARGING_POWER",
        "BATTERY_TO_GRID_POWER",
    )
    ch = next((by_key[k] for k in charge_keys if k in by_key), None)
    dch = next((by_key[k] for k in discharge_keys if k in by_key), None)
    if ch is not None or dch is not None:
        return (dch or 0.0) - (ch or 0.0)

    for k, w in by_key.items():
        if "SOC" in k or "VOLTAGE" in k:
            continue
        if "POWER" not in k or "BATTERY" not in k:
            continue
        return w
    return None


def _load_power_watts_from_data_list(dl: Any) -> Optional[float]:
    """
    Home / AC load power in watts (non-negative magnitude), from Deye dataList.
    """
    if not isinstance(dl, list):
        return None
    by_key: dict[str, float] = {}
    for row in dl:
        if not isinstance(row, dict):
            continue
        k = _metric_key(row.get("key"))
        w = _row_value_to_watts(row)
        if w is None:
            continue
        by_key[k] = w

    candidates: list[float] = []

    # Prefer aggregated/output load metrics first (closer to Deye flow graph UPS/load value).
    for ek in (
        "TOTAL_LOAD_POWER",
        "OUTPUT_LOAD_POWER",
        "INVERTER_LOAD_POWER",
        "EPS_LOAD_POWER",
        "AC_LOAD_POWER",
        "LOAD_ACTIVE_POWER",
        "LOAD_POWER",
        "TOTAL_CONSUMPTION_POWER",
        "CONSUMPTION_POWER",
        "HOME_LOAD_POWER",
        "HOUSE_LOAD_POWER",
        "LOCAL_LOAD_POWER",
        "FAMILY_LOAD_POWER",
        "SMART_LOAD_POWER",
        "PLOAD",
    ):
        if ek in by_key:
            candidates.append(abs(by_key[ek]))
    if candidates:
        # Some firmwares expose both "partial" and "total" load keys; take the largest.
        return max(candidates)

    for k, w in by_key.items():
        if "REACTIVE" in k or "APPARENT" in k:
            continue
        if "BATTERY" in k or "PV" in k or "SOLAR" in k:
            continue
        if ("LOAD" in k or "CONSUMPTION" in k or "HOUSE" in k or "HOME" in k) and "POWER" in k:
            candidates.append(abs(w))
    if candidates:
        return max(candidates)
    return None


def _pv_power_watts_from_data_list(dl: Any) -> Optional[float]:
    """PV / solar production in watts (non-negative magnitude)."""
    if not isinstance(dl, list):
        return None
    by_key: dict[str, float] = {}
    for row in dl:
        if not isinstance(row, dict):
            continue
        k = _metric_key(row.get("key"))
        w = _row_value_to_watts(row)
        if w is None:
            continue
        by_key[k] = w

    # Common split channels on Deye firmwares.
    pv_parts = [by_key[k] for k in ("PPV1", "PPV2", "PV1_POWER", "PV2_POWER") if k in by_key]
    ppv_total = max(0.0, by_key["PPV"]) if "PPV" in by_key else None

    if len(pv_parts) >= 2:
        # Two channels likely represent the full PV input (MPPT1+MPPT2).
        parts_sum = max(0.0, sum(max(0.0, x) for x in pv_parts))
        if ppv_total is not None:
            return max(parts_sum, ppv_total)
        return parts_sum

    if len(pv_parts) == 1:
        # Single-channel payload: prefer PPV total when present to avoid underreporting.
        single = max(0.0, pv_parts[0])
        if ppv_total is not None:
            return max(single, ppv_total)
        return single

    # Often the plant-level PV power in Deye payload.
    if ppv_total is not None:
        return ppv_total

    candidates: list[float] = []
    for ek in (
        "PV_POWER",
        "TOTAL_PV_POWER",
        "SOLAR_POWER",
        "PV_OUTPUT_POWER",
        "PV_GENERATION_POWER",
        "PV_PRODUCTION_POWER",
        "MPPT_TOTAL_POWER",
    ):
        if ek in by_key:
            candidates.append(max(0.0, by_key[ek]))
    if candidates:
        # Prefer the largest non-negative PV power metric to avoid using one MPPT
        # channel when a total value is present under another key.
        return max(candidates)

    for k, w in by_key.items():
        if ("PV" in k or "SOLAR" in k or "MPPT" in k) and "POWER" in k:
            candidates.append(max(0.0, w))
    if candidates:
        return max(candidates)
    return None


def _grid_power_signed_watts_from_data_list(dl: Any) -> Optional[float]:
    """
    Grid power in watts (signed): positive = import from grid, negative = export to grid.
    """
    if not isinstance(dl, list):
        return None
    by_key: dict[str, float] = {}
    for row in dl:
        if not isinstance(row, dict):
            continue
        k = _metric_key(row.get("key"))
        w = _row_value_to_watts(row)
        if w is None:
            continue
        by_key[k] = w

    for ek in (
        "GRID_POWER",
        "GRID_ACTIVE_POWER",
        "UTILITY_POWER",
        "MAINS_POWER",
        "GRID_TOTAL_POWER",
        "PGRID",
    ):
        if ek in by_key:
            return by_key[ek]

    import_keys = ("GRID_IMPORT_POWER", "GRID_BUY_POWER", "IMPORT_POWER", "GRID_CONSUMPTION_POWER")
    export_keys = ("GRID_EXPORT_POWER", "GRID_SELL_POWER", "EXPORT_POWER", "FEED_IN_POWER")
    imp = next((by_key[k] for k in import_keys if k in by_key), None)
    exp = next((by_key[k] for k in export_keys if k in by_key), None)
    if imp is not None or exp is not None:
        return (imp or 0.0) - (exp or 0.0)

    for k, w in by_key.items():
        if "GRID" in k and "POWER" in k:
            return w
    return None


def _grid_frequency_hz_from_data_list(dl: Any) -> Optional[float]:
    """Grid / AC frequency in Hz from Deye dataList (keys vary by firmware)."""
    if not isinstance(dl, list):
        return None
    found: dict[str, float] = {}
    for row in dl:
        if not isinstance(row, dict):
            continue
        k = _metric_key(row.get("key"))
        if "FREQ" not in k and "FREQUENCY" not in k:
            continue
        if "BATTERY" in k or k.startswith("BAT"):
            continue
        try:
            v = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if 40.0 <= v <= 70.0:
            found[k] = v
    if not found:
        return None
    for prefer in (
        "GRID_FREQUENCY",
        "GRID_FREQ",
        "MAINS_FREQUENCY",
        "UTILITY_FREQUENCY",
        "AC_FREQUENCY",
        "AC_FREQ",
        "OUTPUT_FREQUENCY",
        "OUT_FREQUENCY",
        "OUT_FREQ",
        "EPS_FREQUENCY",
        "INVERTER_FREQUENCY",
        "PCU_FREQUENCY",
    ):
        if prefer in found:
            return found[prefer]
    return next(iter(found.values()))


def _parse_metrics_from_entry(
    dev_entry: Any,
) -> tuple[
    Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]
]:
    """(soc %, battery W signed, load W, pv W, grid W signed, grid frequency Hz)."""
    soc = _soc_percent_from_device_data_entry(dev_entry)
    if not isinstance(dev_entry, dict):
        return soc, None, None, None, None, None
    dl = dev_entry.get("dataList")
    pwr = _battery_signed_watts_from_data_list(dl)
    load_w = _load_power_watts_from_data_list(dl)
    pv_w = _pv_power_watts_from_data_list(dl)
    grid_w = _grid_power_signed_watts_from_data_list(dl)
    freq_hz = _grid_frequency_hz_from_data_list(dl)
    return soc, pwr, load_w, pv_w, grid_w, freq_hz


def _resolve_batch_target_sn(entry: Any, sns: list[str], index: int) -> Optional[str]:
    sn_hint: Optional[str] = None
    if isinstance(entry, dict):
        for k in ("deviceSn", "deviceSN", "serialNumber"):
            raw = entry.get(k)
            if raw is not None:
                c = str(raw).strip()
                if c.isdigit():
                    sn_hint = c
                    break
    if sn_hint is not None and sn_hint in sns:
        return sn_hint
    if index < len(sns):
        return sns[index]
    return None


async def _post_latest_metrics_map(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    base: str,
    sns: list[str],
) -> dict[
    str,
    tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]],
]:
    """POST /device/latest for up to 10 serials. Returns sn -> (soc %, bat W, load W, pv W, grid W, freq Hz)."""
    if not sns:
        return {}
    url = f"{base.rstrip('/')}/device/latest"
    empty6 = (None, None, None, None, None, None)
    out: dict[
        str,
        tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]],
    ] = {sn: empty6 for sn in sns}
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
    logger.info(
        "Deye: device/latest response batch_size=%s success=%s top_keys=%s",
        len(sns),
        data.get("success") if isinstance(data, dict) else None,
        sorted(data.keys()) if isinstance(data, dict) else [],
    )
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
    logger.info("Deye: device/latest deviceDataList_len=%s", len(ddl))

    for i, entry in enumerate(ddl):
        soc, pwr, load_w, pv_w, grid_w, freq_hz = _parse_metrics_from_entry(entry)
        target = _resolve_batch_target_sn(entry, sns, i)
        if target is None or target not in out:
            continue
        prev_soc, prev_pwr, prev_load, prev_pv, prev_grid, prev_freq = out[target]
        if soc is not None:
            prev_soc = soc
        if pwr is not None:
            prev_pwr = pwr
        if load_w is not None:
            prev_load = load_w
        if pv_w is not None:
            prev_pv = pv_w
        if grid_w is not None:
            prev_grid = grid_w
        if freq_hz is not None:
            prev_freq = freq_hz
        out[target] = (prev_soc, prev_pwr, prev_load, prev_pv, prev_grid, prev_freq)
    if sns:
        sample_sn = sns[0]
        sample = out.get(sample_sn)
        if sample is not None:
            _, sbat, sload, spv, sgrid, sfreq = sample
            logger.info(
                "Deye: parsed sample sn=%s batteryW=%s loadW=%s pvW=%s gridW=%s gridHz=%s",
                sample_sn,
                sbat,
                sload,
                spv,
                sgrid,
                sfreq,
            )
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

    merged_fetch: dict[
        str,
        tuple[
            Optional[float],
            Optional[float],
            Optional[float],
            Optional[float],
            Optional[float],
            Optional[float],
        ],
    ] = {}
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
                part = await _post_latest_metrics_map(client, hdrs, base, chunk)
                merged_fetch.update(part)

        fetch_time = time.monotonic()
        async with _soc_lock:
            for sn, (soc, pwr, load_w, pv_w, grid_w, freq_hz) in merged_fetch.items():
                _soc_cache[sn] = (soc, fetch_time)
                obat: Optional[float] = None
                oload: Optional[float] = None
                opv: Optional[float] = None
                ogrid: Optional[float] = None
                ofreq: Optional[float] = None
                prev_live = _live_cache.get(sn)
                if prev_live is not None:
                    obat, oload, opv, ogrid, ofreq, _ = prev_live
                nbat = pwr if pwr is not None else obat
                nload = load_w if load_w is not None else oload
                npv = pv_w if pv_w is not None else opv
                ngrid = grid_w if grid_w is not None else ogrid
                nfreq = freq_hz if freq_hz is not None else ofreq
                _live_cache[sn] = (nbat, nload, npv, ngrid, nfreq, fetch_time)

    for sn in unique:
        if sn in result:
            continue
        result[sn] = merged_fetch[sn][0] if sn in merged_fetch else None

    return result


def _normalize_digit_serials(device_sns: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for s in device_sns:
        sn = str(s or "").strip()
        if not sn.isdigit() or sn in seen:
            continue
        seen.add(sn)
        unique.append(sn)
    return unique


async def refresh_device_latest_batches(
    device_sns: list[str],
) -> dict[
    str,
    tuple[
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
    ],
]:
    """
    Always POST /device/latest in batches of up to 10; refresh _soc_cache and _live_cache.
    Returns sn -> (soc %, battery W, load W, pv W, grid W signed, grid frequency Hz).
    """
    unique = _normalize_digit_serials(device_sns)
    if not unique:
        return {}

    merged_fetch: dict[
        str,
        tuple[
            Optional[float],
            Optional[float],
            Optional[float],
            Optional[float],
            Optional[float],
            Optional[float],
        ],
    ] = {}
    base = settings.DEYE_API_BASE_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=45.0) as client:
        token = await _ensure_token(client)
        hdrs = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        for off in range(0, len(unique), 10):
            chunk = unique[off : off + 10]
            part = await _post_latest_metrics_map(client, hdrs, base, chunk)
            merged_fetch.update(part)

    fetch_time = time.monotonic()
    async with _soc_lock:
        for sn, (soc, pwr, load_w, pv_w, grid_w, freq_hz) in merged_fetch.items():
            _soc_cache[sn] = (soc, fetch_time)
            obat: Optional[float] = None
            oload: Optional[float] = None
            opv: Optional[float] = None
            ogrid: Optional[float] = None
            ofreq: Optional[float] = None
            prev_live = _live_cache.get(sn)
            if prev_live is not None:
                obat, oload, opv, ogrid, ofreq, _ = prev_live
            nbat = pwr if pwr is not None else obat
            nload = load_w if load_w is not None else oload
            npv = pv_w if pv_w is not None else opv
            ngrid = grid_w if grid_w is not None else ogrid
            nfreq = freq_hz if freq_hz is not None else ofreq
            _live_cache[sn] = (nbat, nload, npv, ngrid, nfreq, fetch_time)

    empty = (None, None, None, None, None, None)
    return {sn: merged_fetch.get(sn, empty) for sn in unique}


async def fetch_soc_map_refresh(device_sns: list[str]) -> dict[str, Optional[float]]:
    """
    Always calls Deye POST /device/latest (batched); updates _soc_cache and _live_cache.
    Use for DB snapshots so samples are not stuck behind SOC_CACHE_TTL_SEC.
    """
    if not deye_configured():
        return {}
    unique = _normalize_digit_serials(device_sns)
    if not unique:
        return {}
    merged = await refresh_device_latest_batches(unique)
    return {sn: merged[sn][0] for sn in unique}


async def get_live_metrics_cached(
    device_sn: str,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Latest (battery W signed, load W, pv W, grid W signed, grid frequency Hz) for one inverter.
    TTL ESS_POWER_CACHE_TTL_SEC. Same Deye call fills both.
    """
    sn = (device_sn or "").strip()
    if not sn or not deye_configured():
        return None, None, None, None, None

    async with _soc_lock:
        now = time.monotonic()
        hit = _live_cache.get(sn)
        if hit is not None:
            bat, load_w, pv_w, grid_w, freq_hz, ts = hit
            if now - ts < ESS_POWER_CACHE_TTL_SEC:
                return _finalize_live_metrics_for_sn(sn, bat, load_w, pv_w, grid_w, freq_hz)

    base = settings.DEYE_API_BASE_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=45.0) as client:
        token = await _ensure_token(client)
        hdrs = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        merged = await _post_latest_metrics_map(client, hdrs, base, [sn])

    fetch_time = time.monotonic()
    soc, pwr, load_w, pv_w, grid_w, freq_hz = merged.get(sn, (None, None, None, None, None, None))
    async with _soc_lock:
        _soc_cache[sn] = (soc, fetch_time)
        obat: Optional[float] = None
        oload: Optional[float] = None
        opv: Optional[float] = None
        ogrid: Optional[float] = None
        ofreq: Optional[float] = None
        prev_live = _live_cache.get(sn)
        if prev_live is not None:
            obat, oload, opv, ogrid, ofreq, _ = prev_live
        nbat = pwr if pwr is not None else obat
        nload = load_w if load_w is not None else oload
        npv = pv_w if pv_w is not None else opv
        ngrid = grid_w if grid_w is not None else ogrid
        nfreq = freq_hz if freq_hz is not None else ofreq
        _live_cache[sn] = (nbat, nload, npv, ngrid, nfreq, fetch_time)
    fbat, fload, fpv, fgrid, ffreq = _finalize_live_metrics_for_sn(sn, nbat, nload, npv, ngrid, nfreq)
    logger.info(
        "Deye: live metrics sn=%s batteryW=%s loadW=%s pvW=%s gridW=%s gridHz=%s",
        sn,
        fbat,
        fload,
        fpv,
        fgrid,
        ffreq,
    )
    return fbat, fload, fpv, fgrid, ffreq


async def get_battery_power_w_cached(device_sn: str) -> Optional[float]:
    """Battery W only; same cache as get_live_metrics_cached."""
    b, _, _, _, _ = await get_live_metrics_cached(device_sn)
    return b


async def fetch_device_soc_percent(device_sn: str) -> Optional[float]:
    """Single-serial SoC; uses the same TTL cache as get_soc_map_cached."""
    sn = (device_sn or "").strip()
    if not sn:
        return None
    m = await get_soc_map_cached([sn])
    return m.get(sn)


# Week + 6 TOU slots — same shape as Deye sample scripts (dynamic_control_*.py).
_TOU_DAYS: list[str] = [
    "SUNDAY",
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
]
_TOU_TIMES: tuple[str, ...] = ("02:30", "06:30", "20:30", "21:30", "22:30", "23:30")

# Minimum TOU SoC % when restoring ZERO_EXPORT_TO_CT after discharge (Deye self-consumption samples use ~15).
_ZERO_EXPORT_CT_DEFAULT_TOU_SOC_PCT = 15.0


def _tou_setting_items(soc: float, power: int) -> list[dict[str, Any]]:
    return [
        {
            "enableGeneration": True,
            "enableGridCharge": True,
            "power": int(power),
            "soc": float(soc),
            "time": t,
        }
        for t in _TOU_TIMES
    ]


def _body_selling_first(device_sn: str, tou_soc: float, rated_power: int) -> dict[str, Any]:
    rp = int(rated_power)
    return {
        "deviceSn": device_sn,
        "maxSellPower": rp,
        "maxSolarPower": rp,
        "solarSellAction": "on",
        "touAction": "on",
        "touDays": list(_TOU_DAYS),
        "workMode": "SELLING_FIRST",
        "timeUseSettingItems": _tou_setting_items(tou_soc, rp),
    }


def _body_zero_export_target_soc(device_sn: str, tou_soc: float, rated_power: int) -> dict[str, Any]:
    """ZERO_EXPORT_TO_CT with a uniform TOU SoC target (used to bias battery toward a higher SoC)."""
    power = int(rated_power)
    return {
        "deviceSn": device_sn,
        "solarSellAction": "on",
        "touAction": "on",
        "touDays": list(_TOU_DAYS),
        "workMode": "ZERO_EXPORT_TO_CT",
        "timeUseSettingItems": _tou_setting_items(float(tou_soc), power),
    }


async def _post_strategy_dynamic_control(body: dict[str, Any]) -> None:
    """
    POST /strategy/dynamicControl — overwrites device TOU / work mode per Deye cloud semantics.
    See official samples: clientcode/strategy/dynamic_control_*.py
    """
    if not deye_configured():
        raise RuntimeError("Deye API credentials not configured")
    base = settings.DEYE_API_BASE_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=90.0) as client:
        token = await _ensure_token(client)
        r = await client.post(
            f"{base}/strategy/dynamicControl",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            json=body,
        )
        snippet = (r.text or "")[:900]
        if r.status_code >= 400:
            logger.warning("Deye: dynamicControl HTTP %s — %s", r.status_code, snippet)
            r.raise_for_status()
        try:
            data = r.json()
        except Exception:
            return
        if isinstance(data, dict) and data.get("success") is False:
            msg = str(data.get("msg") or data.get("message") or "dynamicControl failed")
            logger.warning("Deye: dynamicControl success=false msg=%s raw=%s", msg[:300], snippet)
            raise RuntimeError(msg)


def _clamp_sell_power_w(p: int) -> int:
    """Same bounds as DEYE_DYNAMIC_CONTROL_RATED_POWER_W (settings._env_int 500..200_000)."""
    return max(500, min(200_000, int(p)))


async def apply_selling_first_max_power_w(
    device_sn: str,
    max_power_w: int,
    tou_soc: float,
) -> None:
    """
    SELLING_FIRST with max sell / solar power set to ``max_power_w`` (e.g. EV station job powerWt).
    ``tou_soc`` should be low enough to allow discharge during the session (see Deye TOU template).
    """
    await assert_inverter_owned(device_sn)
    sn = device_sn.strip()
    rp = _clamp_sell_power_w(max_power_w)
    await _post_strategy_dynamic_control(_body_selling_first(sn, float(tou_soc), rp))


async def restore_zero_export_ct_current_soc(device_sn: str) -> None:
    """ZERO_EXPORT_TO_CT with TOU SoC = max(15%, current SoC) — template power from DEYE_DYNAMIC_CONTROL_RATED_POWER_W."""
    await assert_inverter_owned(device_sn)
    sn = device_sn.strip()
    rated = settings.DEYE_DYNAMIC_CONTROL_RATED_POWER_W
    soc_map = await fetch_soc_map_refresh([sn])
    soc = soc_map.get(sn)
    if soc is None:
        tou_soc = _ZERO_EXPORT_CT_DEFAULT_TOU_SOC_PCT
    else:
        tou_soc = max(_ZERO_EXPORT_CT_DEFAULT_TOU_SOC_PCT, round(float(soc), 2))
    await _post_strategy_dynamic_control(_body_zero_export_target_soc(sn, tou_soc, rated))


async def assert_inverter_owned(device_sn: str) -> None:
    sn = (device_sn or "").strip()
    items = await list_inverter_devices()
    allowed = {str(it.get("deviceSn") or "").strip() for it in items if it.get("deviceSn")}
    if sn not in allowed:
        raise ValueError(f"Inverter serial not in this account: {sn}")


_DISCHARGE_SOC_DELTA_MIN = 1.0
_DISCHARGE_SOC_DELTA_MAX = 100.0


async def _discharge_soc_delta_poll_loop_and_restore(
    sn: str,
    soc0_f: float,
    target: float,
    poll: float,
    timeout: float,
    rated: int,
) -> tuple[bool, float, Optional[str]]:
    """Poll until SoC at target; then ZERO_EXPORT_TO_CT with TOU SoC = max(15%, discharge target)."""
    hit_target = False
    last_soc: float = float(soc0_f)
    restore_error: Optional[str] = None
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(poll)
            refreshed = await fetch_soc_map_refresh([sn])
            cur = refreshed.get(sn)
            if cur is not None:
                last_soc = float(cur)
                if last_soc <= target + 0.08:
                    hit_target = True
                    break
    except Exception:
        logger.exception("Deye: discharge sequence failed before restore sn=%s", sn)
        raise
    finally:
        try:
            tou_soc_rest = max(_ZERO_EXPORT_CT_DEFAULT_TOU_SOC_PCT, round(float(target), 2))
            await _post_strategy_dynamic_control(_body_zero_export_target_soc(sn, tou_soc_rest, rated))
        except Exception as exc:
            restore_error = str(exc)
            logger.exception("Deye: ZERO_EXPORT_TO_CT restore failed sn=%s", sn)

    return hit_target, last_soc, restore_error


async def discharge_soc_delta_then_zero_export_ct(
    device_sn: str,
    soc_delta_pct: float,
    *,
    return_after_start: bool = False,
) -> dict[str, Any]:
    """
    1) Set workMode SELLING_FIRST via dynamicControl (discharge-friendly TOU template).
    2) Poll SoC until it drops by soc_delta_pct points or timeout.
    3) Set ZERO_EXPORT_TO_CT with TOU SoC = max(15%, discharge target SoC).

    soc_delta_pct: 1..100 (percentage points of SoC to shed; use ~100% of current SoC for full discharge).

    When return_after_start is True, step 1 is awaited and the HTTP handler can return
    immediately; steps 2–3 continue in a background task (for UI loaders).

    Warning: replaces the device's TOU schedule with the template (Deye API limitation).
    """
    delta = float(soc_delta_pct)
    if delta < _DISCHARGE_SOC_DELTA_MIN or delta > _DISCHARGE_SOC_DELTA_MAX:
        raise ValueError(
            f"soc_delta_pct must be between {_DISCHARGE_SOC_DELTA_MIN} and {_DISCHARGE_SOC_DELTA_MAX}"
        )

    await assert_inverter_owned(device_sn)
    sn = device_sn.strip()
    rated = settings.DEYE_DYNAMIC_CONTROL_RATED_POWER_W
    soc_map = await fetch_soc_map_refresh([sn])
    soc0 = soc_map.get(sn)
    if soc0 is None:
        raise ValueError("SOC not available from device — cannot run discharge sequence")
    soc0_f = float(soc0)
    if soc0_f < delta:
        raise ValueError(
            f"SOC below {delta:.0f}% — cannot target a {delta:.0f} percentage-point discharge"
        )

    target = max(0.0, soc0_f - delta)
    poll = max(5, settings.DEYE_DISCHARGE_SOC_POLL_SEC)
    timeout = max(60, settings.DEYE_DISCHARGE_SOC_TIMEOUT_SEC)
    # TOU soc floor = desired SoC after discharge target (Deye samples use low soc to allow discharge)
    tou_soc_discharge = round(target, 2)

    await _post_strategy_dynamic_control(_body_selling_first(sn, tou_soc_discharge, rated))

    if return_after_start:

        async def _bg_discharge() -> None:
            try:
                _, _, restore_error = await _discharge_soc_delta_poll_loop_and_restore(
                    sn, soc0_f, target, poll, timeout, rated
                )
                if restore_error:
                    logger.error(
                        "Deye: background discharge finished with restore error sn=%s err=%s",
                        sn,
                        restore_error,
                    )
            except Exception:
                logger.exception("Deye: background discharge task failed sn=%s", sn)

        asyncio.create_task(_bg_discharge())
        return {
            "deviceSn": sn,
            "socDeltaPercent": round(delta, 2),
            "startSoc": soc0_f,
            "targetSoc": float(target),
            "lastSoc": soc0_f,
            "hitTarget": False,
            "workModeRestored": None,
            "respondAfterStart": True,
        }

    hit_target, last_soc, restore_error = await _discharge_soc_delta_poll_loop_and_restore(
        sn, soc0_f, target, poll, timeout, rated
    )

    if restore_error:
        raise RuntimeError(f"Failed to restore ZERO_EXPORT_TO_CT: {restore_error}")

    return {
        "deviceSn": sn,
        "socDeltaPercent": round(delta, 2),
        "startSoc": soc0_f,
        "targetSoc": float(target),
        "lastSoc": last_soc,
        "hitTarget": hit_target,
        "workModeRestored": "ZERO_EXPORT_TO_CT",
        "respondAfterStart": False,
    }


async def discharge_two_percent_then_zero_export_ct(device_sn: str) -> dict[str, Any]:
    """Backward-compatible name: fixed 2 percentage-point drop."""
    return await discharge_soc_delta_then_zero_export_ct(device_sn, 2.0)


_CHARGE_SOC_DELTA_ALLOWED: tuple[int, ...] = (2, 10, 20, 50, 100)


async def _charge_soc_delta_poll_loop_and_restore(
    sn: str,
    soc0_f: float,
    target: float,
    poll: float,
    timeout: float,
    rated: int,
) -> tuple[bool, float, Optional[str]]:
    """Poll until SoC reaches charge target; then set ZERO_EXPORT_TO_CT TOU SoC to that target (not 15%)."""
    hit_target = False
    last_soc: float = float(soc0_f)
    restore_error: Optional[str] = None
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(poll)
            refreshed = await fetch_soc_map_refresh([sn])
            cur = refreshed.get(sn)
            if cur is not None:
                last_soc = float(cur)
                if last_soc >= target - 0.08:
                    hit_target = True
                    break
    except Exception:
        logger.exception("Deye: charge sequence failed before restore sn=%s", sn)
        raise
    finally:
        try:
            tou_soc_rest = round(float(target), 2)
            await _post_strategy_dynamic_control(_body_zero_export_target_soc(sn, tou_soc_rest, rated))
        except Exception as exc:
            restore_error = str(exc)
            logger.exception("Deye: ZERO_EXPORT_TO_CT restore failed after charge sn=%s", sn)

    return hit_target, last_soc, restore_error


async def charge_soc_delta_then_zero_export_ct(
    device_sn: str,
    soc_delta_pct: float,
    *,
    return_after_start: bool = False,
) -> dict[str, Any]:
    """
    1) Set ZERO_EXPORT_TO_CT with a high TOU SoC target (current SoC + delta, capped at 100).
    2) Poll until SoC rises by approximately soc_delta_pct or timeout.
    3) Re-apply ZERO_EXPORT_TO_CT with TOU SoC set to the charge target (keeps that level in slots).

    soc_delta_pct: one of 2, 10, 20, 50, 100 (percentage points to add toward 100% SoC).

    When return_after_start is True, step 1 is awaited and the caller may return immediately;
    steps 2–3 continue in a background task.
    """
    delta_f = float(soc_delta_pct)
    delta_i = int(round(delta_f))
    if delta_i not in _CHARGE_SOC_DELTA_ALLOWED:
        allowed = ", ".join(str(x) for x in _CHARGE_SOC_DELTA_ALLOWED)
        raise ValueError(f"soc_delta_pct for charge must be one of: {allowed}")

    await assert_inverter_owned(device_sn)
    sn = device_sn.strip()
    rated = settings.DEYE_DYNAMIC_CONTROL_RATED_POWER_W
    soc_map = await fetch_soc_map_refresh([sn])
    soc0 = soc_map.get(sn)
    if soc0 is None:
        raise ValueError("SOC not available from device — cannot run charge sequence")
    soc0_f = float(soc0)
    target = min(100.0, soc0_f + float(delta_i))
    if soc0_f >= target - 0.05:
        raise ValueError(
            f"SOC already at or above charge target (~{target:.1f}%) — nothing to add by {delta_i}%"
        )

    poll = max(5, settings.DEYE_DISCHARGE_SOC_POLL_SEC)
    timeout = max(60, settings.DEYE_DISCHARGE_SOC_TIMEOUT_SEC)
    tou_soc_charge = round(target, 2)

    await _post_strategy_dynamic_control(_body_zero_export_target_soc(sn, tou_soc_charge, rated))

    if return_after_start:

        async def _bg_charge() -> None:
            try:
                _, _, restore_error = await _charge_soc_delta_poll_loop_and_restore(
                    sn, soc0_f, target, poll, timeout, rated
                )
                if restore_error:
                    logger.error(
                        "Deye: background charge finished with restore error sn=%s err=%s",
                        sn,
                        restore_error,
                    )
            except Exception:
                logger.exception("Deye: background charge task failed sn=%s", sn)

        asyncio.create_task(_bg_charge())
        return {
            "deviceSn": sn,
            "socDeltaPercent": float(delta_i),
            "startSoc": soc0_f,
            "targetSoc": float(target),
            "lastSoc": soc0_f,
            "hitTarget": False,
            "workModeRestored": None,
            "respondAfterStart": True,
        }

    hit_target, last_soc, restore_error = await _charge_soc_delta_poll_loop_and_restore(
        sn, soc0_f, target, poll, timeout, rated
    )

    if restore_error:
        raise RuntimeError(f"Failed to restore ZERO_EXPORT_TO_CT: {restore_error}")

    return {
        "deviceSn": sn,
        "socDeltaPercent": float(delta_i),
        "startSoc": soc0_f,
        "targetSoc": float(target),
        "lastSoc": last_soc,
        "hitTarget": hit_target,
        "workModeRestored": "ZERO_EXPORT_TO_CT",
        "respondAfterStart": False,
    }
