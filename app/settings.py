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
OREE_DAM_LAZY_FETCH_MAX: int = _env_int("OREE_DAM_LAZY_FETCH_MAX", 0, 0, 50)

# Persist Deye SoC to DB on a fixed interval (all inverters from listWithDevice; UTC 5-min buckets).
DEYE_SOC_SNAPSHOT_ENABLED: bool = _env_bool("DEYE_SOC_SNAPSHOT_ENABLED", True)
DEYE_SOC_SNAPSHOT_INTERVAL_SEC: int = _env_int("DEYE_SOC_SNAPSHOT_INTERVAL_SEC", 300, 60, 3600)

# POST /strategy/dynamicControl — template power (W) for timeUseSettingItems; also maxSell/maxSolar when SELLING_FIRST.
DEYE_DYNAMIC_CONTROL_RATED_POWER_W: int = _env_int("DEYE_DYNAMIC_CONTROL_RATED_POWER_W", 10_000, 500, 200_000)
# discharge-2pct: poll SoC and max wait (blocking HTTP — raise reverse-proxy read timeouts if needed).
DEYE_DISCHARGE_SOC_POLL_SEC: int = _env_int("DEYE_DISCHARGE_SOC_POLL_SEC", 15, 5, 120)
DEYE_DISCHARGE_SOC_TIMEOUT_SEC: int = _env_int("DEYE_DISCHARGE_SOC_TIMEOUT_SEC", 1800, 120, 7200)

# Backend: discharge ~2% SoC once per (Kyiv calendar day, inverter, DAM peak hour) when pref enabled.
DEYE_PEAK_AUTO_DISCHARGE_SCHEDULER_ENABLED: bool = _env_bool("DEYE_PEAK_AUTO_DISCHARGE_SCHEDULER_ENABLED", True)
DEYE_PEAK_AUTO_DISCHARGE_INTERVAL_SEC: int = _env_int("DEYE_PEAK_AUTO_DISCHARGE_INTERVAL_SEC", 600, 20, 600)

# Backend: charge SoC toward target once per (Kyiv day, inverter, DAM minimum-price hour) when pref enabled.
DEYE_LOW_DAM_CHARGE_SCHEDULER_ENABLED: bool = _env_bool("DEYE_LOW_DAM_CHARGE_SCHEDULER_ENABLED", True)
DEYE_LOW_DAM_CHARGE_INTERVAL_SEC: int = _env_int("DEYE_LOW_DAM_CHARGE_INTERVAL_SEC", 600, 20, 600)

# Per-client IP HTTP rate limit (sliding 60s window, in-process memory). Trust X-Forwarded-For only behind a trusted proxy.
RATE_LIMIT_ENABLED: bool = _env_bool("RATE_LIMIT_ENABLED", True)
RATE_LIMIT_PER_IP_PER_MINUTE: int = _env_int("RATE_LIMIT_PER_IP_PER_MINUTE", 200, 1, 10_000)
