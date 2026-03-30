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


OREE_DAM_DAILY_SYNC_HOUR_KYIV: int = _env_int("OREE_DAM_DAILY_SYNC_HOUR_KYIV", 13, 0, 23)
OREE_DAM_DAILY_SYNC_MINUTE_KYIV: int = _env_int("OREE_DAM_DAILY_SYNC_MINUTE_KYIV", 0, 0, 59)

# Persist Deye SoC to DB on a fixed interval (all inverters from listWithDevice; UTC 5-min buckets).
DEYE_SOC_SNAPSHOT_ENABLED: bool = _env_bool("DEYE_SOC_SNAPSHOT_ENABLED", True)
DEYE_SOC_SNAPSHOT_INTERVAL_SEC: int = _env_int("DEYE_SOC_SNAPSHOT_INTERVAL_SEC", 300, 60, 3600)
