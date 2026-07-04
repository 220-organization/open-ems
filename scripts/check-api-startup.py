#!/usr/bin/env python3
"""Verify FastAPI import + lifespan startup (catches missing scheduler imports).

Example failure this catches:
  NameError: name 'huawei_power_snapshot_loop' is not defined
when lifespan runs on prod with HUAWEI_* configured but main.py forgot the import.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Prod-like env so lifespan executes scheduler branches that depend on *._configured().
_PRECHECK_ENV = {
    "HUAWEI_ENABLED": "1",
    "HUAWEI_USER_NAME": "precheck",
    "HUAWEI_SYSTEM_CODE": "precheck",
    "HUAWEI_POWER_SNAPSHOT_ENABLED": "1",
    "HUAWEI_STATION_ENERGY_SNAPSHOT_ENABLED": "1",
    "UBETTER_ENABLED": "1",
    "UBETTER_PASSWORD": "precheck",
    "UBETTER_POWER_SNAPSHOT_ENABLED": "1",
    "DEYE_APP_ID": "precheck",
    "DEYE_APP_SECRET": "precheck",
    "DEYE_EMAIL": "precheck@example.com",
    "DEYE_PASSWORD": "precheck",
}


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    for key, value in _PRECHECK_ENV.items():
        os.environ.setdefault(key, value)

    async def _run() -> None:
        from app.main import app

        async with app.router.lifespan_context(app):
            pass

    try:
        asyncio.run(_run())
    except Exception as exc:
        print(f"ERROR: API startup check failed: {exc}", file=sys.stderr)
        return 1
    print("API startup check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
