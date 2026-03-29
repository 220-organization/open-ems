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


# When False, FastAPI does not serve React build or legacy power_flow HTML (split dev: CRA on its own port).
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
