import os
from pathlib import Path

from dotenv import load_dotenv

# Load open-ems/.env into the process environment (local dev; Docker/k8s can still inject vars).
_APP_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_APP_ROOT / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default


# When False, FastAPI does not serve the React production build (split dev: CRA on its own port).
# Docker/production: unset or true. Local ./run-local.sh sets OPEN_EMS_SERVE_SPA=0.
OPEN_EMS_SERVE_SPA: bool = _env_bool("OPEN_EMS_SERVE_SPA", True)

# Upstream public B2B API (same paths as Spring B2BPublicController).
# Production React uses REACT_APP_HOST + REACT_APP_PORT → https://220-km.com:8080
B2B_API_BASE_URL: str = os.environ.get("B2B_API_BASE_URL", "https://220-km.com:8080").rstrip("/")

# Deye Cloud Open API (developer portal — not the same as the web UI session).
# Token: POST /account/token?appId=… ; plants/devices: POST /station/listWithDevice
DEYE_API_BASE_URL: str = os.environ.get(
    "DEYE_API_BASE_URL",
    "https://eu1-developer.deyecloud.com/v1.0",
).rstrip("/")
DEYE_APP_ID: str = (os.environ.get("DEYE_APP_ID") or "").strip()
DEYE_APP_SECRET: str = (os.environ.get("DEYE_APP_SECRET") or "").strip()
DEYE_EMAIL: str = (os.environ.get("DEYE_EMAIL") or "").strip()
DEYE_PASSWORD: str = os.environ.get("DEYE_PASSWORD") or ""
DEYE_COMPANY_ID: str = (os.environ.get("DEYE_COMPANY_ID") or "0").strip()

# OREE / DAM API (same as Java OreeDamPriceSyncService — api.oree.com.ua).
OREE_API_BASE_URL: str = os.environ.get(
    "OREE_API_BASE_URL",
    "https://api.oree.com.ua/index.php/api",
).rstrip("/")
OREE_API_DAM_PRICES_PATH: str = (os.environ.get("OREE_API_DAM_PRICES_PATH") or "/damprices").strip()
OREE_API_DAM_INDEXES_PATH: str = (os.environ.get("OREE_API_DAM_INDEXES_PATH") or "/damindexes").strip()
OREE_API_KEY: str = (os.environ.get("OREE_API_KEY") or os.environ.get("OREE_API_API_KEY") or "").strip()
OREE_COMPARE_ZONE_EIC: str = (
    os.environ.get("OREE_COMPARE_ZONE_EIC") or "10Y1001C--000182"
).strip()

# Daily OREE → DB sync (Europe/Kiev wall clock).
OREE_DAM_DAILY_SYNC_ENABLED: bool = _env_bool("OREE_DAM_DAILY_SYNC_ENABLED", True)


def _env_int(name: str, default: int, min_v: int, max_v: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return max(min_v, min(max_v, v))


def _parse_oree_sync_hours_kyiv() -> tuple[int, ...]:
    """
    Europe/Kiev wall-clock hours for scheduled OREE DAM pulls (comma-separated), default 12–15.
    If OREE_DAM_SYNC_HOURS_KYIV is unset, OREE_DAM_DAILY_SYNC_HOUR_KYIV (single hour) is still honored.
    """
    raw = (os.environ.get("OREE_DAM_SYNC_HOURS_KYIV") or "").strip()
    if raw:
        hs: list[int] = []
        for part in raw.split(","):
            p = part.strip()
            if not p:
                continue
            try:
                h = int(p)
                if 0 <= h <= 23:
                    hs.append(h)
            except ValueError:
                pass
        return tuple(sorted(set(hs))) if hs else (12, 13, 14, 15)
    legacy = (os.environ.get("OREE_DAM_DAILY_SYNC_HOUR_KYIV") or "").strip()
    if legacy:
        try:
            h = int(legacy)
            if 0 <= h <= 23:
                return (h,)
        except ValueError:
            pass
    return (12, 13, 14, 15)


# Scheduled OREE DAM sync: these Kyiv hours (see oree_dam_scheduler).
OREE_DAM_SYNC_HOURS_KYIV: tuple[int, ...] = _parse_oree_sync_hours_kyiv()
OREE_DAM_DAILY_SYNC_MINUTE_KYIV: int = _env_int("OREE_DAM_DAILY_SYNC_MINUTE_KYIV", 0, 0, 59)

# Allow POST /api/dam/sync (off by default — OREE only via daily scheduler).
OREE_DAM_MANUAL_SYNC_ENABLED: bool = _env_bool("OREE_DAM_MANUAL_SYNC_ENABLED", False)

# Max on-demand OREE pulls via GET /api/dam/chart-day when DB empty for Kyiv tomorrow (0 = off; UI never triggers OREE).
OREE_DAM_LAZY_FETCH_MAX: int = _env_int("OREE_DAM_LAZY_FETCH_MAX", 5, 0, 50)

# ENTSO-E Transparency Platform REST API — day-ahead prices (DocumentType A44 / ProcessType A01).
# Token: https://transparency.entsoe.eu/ → My Account → generate token; see docs/ENTSOE_TRANSPARENCY_DAM.md
ENTSOE_API_BASE_URL: str = os.environ.get(
    "ENTSOE_API_BASE_URL",
    "https://web-api.tp.entsoe.eu/api",
).rstrip("/")
ENTSOE_SECURITY_TOKEN: str = (os.environ.get("ENTSOE_SECURITY_TOKEN") or "").strip()
# Transparency REST: recommended User-Agent (identify your client); see ENTSO-E usage policy.
ENTSOE_HTTP_USER_AGENT: str = (
    os.environ.get("ENTSOE_HTTP_USER_AGENT") or "OpenEMS/1.0 (open-ems; ENTSO-E Transparency)"
).strip()


# Always persisted by daily ENTSO-E sync (same zones as DAM chart overlays / picker). Not configurable via env.
_ENTSOE_DAM_ZONE_EICS_BASE: tuple[str, ...] = (
    "10YES-REE------0",  # Spain (ES)
    "10YPL-AREA-----S",  # Poland (PL)
    "10Y1001C--000182",  # Ukraine (UA / UA_ENTSO)
)


def _parse_entsoe_zone_eics() -> tuple[str, ...]:
    """
    Built-in ES/PL/UA plus optional extras from ENTSOE_DAM_ZONE_EICS (comma-separated EICs).
    Extras are merged and de-duplicated — env cannot remove chart zones.
    """
    raw = (os.environ.get("ENTSOE_DAM_ZONE_EICS") or "").strip()
    extras = tuple(x.strip() for x in raw.split(",") if x.strip()) if raw else ()
    seen: set[str] = set()
    out: list[str] = []
    for z in _ENTSOE_DAM_ZONE_EICS_BASE:
        if z not in seen:
            seen.add(z)
            out.append(z)
    for z in extras:
        if z not in seen:
            seen.add(z)
            out.append(z)
    return tuple(out)


ENTSOE_DAM_ZONE_EICS: tuple[str, ...] = _parse_entsoe_zone_eics()

# IANA zone for delivery-day midnight bounds (periodStart/periodEnd in UTC).
ENTSOE_DOMAIN_TIMEZONE: dict[str, str] = {
    "10YES-REE------0": "Europe/Madrid",
    "10YPL-AREA-----S": "Europe/Warsaw",
    "10Y1001C--000182": "Europe/Kyiv",  # Ukraine (UCTE) — same EIC as OREE_COMPARE_ZONE_EIC
}

ENTSOE_ZONE_ALIASES: dict[str, str] = {
    "ES": "10YES-REE------0",
    "PL": "10YPL-AREA-----S",
    "UA_ENTSO": "10Y1001C--000182",
}

ENTSOE_DAM_DAILY_SYNC_ENABLED: bool = _env_bool("ENTSOE_DAM_DAILY_SYNC_ENABLED", True)

# When True, skip a scheduled run if every ENTSOE_DAM_ZONE_EICS zone already has 24 hourly rows for the delivery day.
# When False (default), always pull ES/PL (etc.) at each Brussels window so DB stays refreshed.
ENTSOE_DAM_DAILY_SYNC_SKIP_IF_COMPLETE: bool = _env_bool("ENTSOE_DAM_DAILY_SYNC_SKIP_IF_COMPLETE", False)


def _parse_entsoe_sync_hours_brussels() -> tuple[int, ...]:
    raw = (os.environ.get("ENTSOE_DAM_SYNC_HOURS_BRUSSELS") or "").strip()
    if raw:
        hs: list[int] = []
        for part in raw.split(","):
            p = part.strip()
            if not p:
                continue
            try:
                h = int(p)
                if 0 <= h <= 23:
                    hs.append(h)
            except ValueError:
                pass
        return tuple(sorted(set(hs))) if hs else (12, 13, 14, 15)
    return (12, 13, 14, 15)


ENTSOE_DAM_SYNC_HOURS_BRUSSELS: tuple[int, ...] = _parse_entsoe_sync_hours_brussels()
ENTSOE_DAM_DAILY_SYNC_MINUTE_BRUSSELS: int = _env_int("ENTSOE_DAM_DAILY_SYNC_MINUTE_BRUSSELS", 0, 0, 59)
ENTSOE_DAM_MANUAL_SYNC_ENABLED: bool = _env_bool("ENTSOE_DAM_MANUAL_SYNC_ENABLED", False)

# GET /api/dam/entsoe/chart-day: if DB has no prices for the requested delivery day, fetch ENTSO-E once and upsert (backfill).
ENTSOE_CHART_DAY_LAZY_FETCH: bool = _env_bool("ENTSOE_CHART_DAY_LAZY_FETCH", True)

# Persist Deye SoC to DB on a fixed interval (all inverters from listWithDevice; UTC 5-min buckets).
DEYE_SOC_SNAPSHOT_ENABLED: bool = _env_bool("DEYE_SOC_SNAPSHOT_ENABLED", True)
DEYE_SOC_SNAPSHOT_INTERVAL_SEC: int = _env_int("DEYE_SOC_SNAPSHOT_INTERVAL_SEC", 300, 60, 3600)

# POST /strategy/dynamicControl — template power (W) for timeUseSettingItems; also maxSell/maxSolar when SELLING_FIRST.
DEYE_DYNAMIC_CONTROL_RATED_POWER_W: int = _env_int("DEYE_DYNAMIC_CONTROL_RATED_POWER_W", 10_000, 500, 200_000)
# discharge-2pct: poll SoC and max wait (blocking HTTP — raise reverse-proxy read timeouts if needed).
DEYE_DISCHARGE_SOC_POLL_SEC: int = _env_int("DEYE_DISCHARGE_SOC_POLL_SEC", 15, 5, 120)
DEYE_DISCHARGE_SOC_TIMEOUT_SEC: int = _env_int("DEYE_DISCHARGE_SOC_TIMEOUT_SEC", 14400, 120, 28800)

# Backend: discharge ~2% SoC once per (Kyiv calendar day, inverter, DAM peak hour) when pref enabled.
DEYE_PEAK_AUTO_DISCHARGE_SCHEDULER_ENABLED: bool = _env_bool("DEYE_PEAK_AUTO_DISCHARGE_SCHEDULER_ENABLED", True)
DEYE_PEAK_AUTO_DISCHARGE_INTERVAL_SEC: int = _env_int("DEYE_PEAK_AUTO_DISCHARGE_INTERVAL_SEC", 600, 20, 600)

# Backend: charge SoC toward target once per (Kyiv day, inverter, DAM minimum-price hour) when pref enabled.
DEYE_LOW_DAM_CHARGE_SCHEDULER_ENABLED: bool = _env_bool("DEYE_LOW_DAM_CHARGE_SCHEDULER_ENABLED", True)
DEYE_LOW_DAM_CHARGE_INTERVAL_SEC: int = _env_int("DEYE_LOW_DAM_CHARGE_INTERVAL_SEC", 600, 20, 600)

# EV port binding: inverter label must contain ``evport<station>`` (e.g. ``evport738``). Poll 220-km station status and
# match export power to job powerWt while state is IN_PROGRESS (see deye_ev_port_export_service). Active only when DEYE_* is set.
DEYE_EV_PORT_EXPORT_INTERVAL_SEC: int = _env_int("DEYE_EV_PORT_EXPORT_INTERVAL_SEC", 30, 15, 300)
# GET /api/device/v2/station/status — public clientUiId (override with ``clientui<token>`` in the inverter label).
EV_PORT_DEVICE_CLIENT_UI_ID: str = (os.environ.get("EV_PORT_DEVICE_CLIENT_UI_ID") or "dtbhrny").strip() or "dtbhrny"
# TOU SoC floor while SELLING_FIRST tracks an active EV job (low value allows discharge / export).
DEYE_EV_PORT_EXPORT_TOU_SOC_PCT: int = _env_int("DEYE_EV_PORT_EXPORT_TOU_SOC_PCT", 15, 1, 100)

# Per-client IP HTTP rate limit (sliding 60s window, in-process memory). Trust X-Forwarded-For only behind a trusted proxy.
RATE_LIMIT_ENABLED: bool = _env_bool("RATE_LIMIT_ENABLED", True)
RATE_LIMIT_PER_IP_PER_MINUTE: int = _env_int("RATE_LIMIT_PER_IP_PER_MINUTE", 200, 1, 10_000)
