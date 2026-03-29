#!/usr/bin/env python3
"""
Run Flyway migrate using DATABASE_URL (postgresql://...).
Used when Flyway CLI is installed in the image (e.g. RUN_FLYWAY_ON_START=true).
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.parse


def _jdbc_url(parsed: urllib.parse.ParseResult) -> str:
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    path = (parsed.path or "/").lstrip("/")
    db = path.split("/")[0] if path else ""
    if not db:
        raise ValueError("DATABASE_URL must include a database name in the path")
    base = f"jdbc:postgresql://{host}:{port}/{db}"
    if parsed.query:
        return f"{base}?{parsed.query}"
    return base


def main() -> int:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]

    # Strip SQLAlchemy async driver prefix if present (e.g. postgresql+asyncpg://)
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        if "+" in scheme:
            scheme = scheme.split("+", 1)[0]
            raw = f"{scheme}://{rest}"

    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("postgresql", "postgres"):
        print("DATABASE_URL must be a postgresql:// URL for Flyway", file=sys.stderr)
        return 1

    jdbc = _jdbc_url(parsed)
    user = urllib.parse.unquote(parsed.username or "")
    password = urllib.parse.unquote(parsed.password or "")

    sql_dir = os.environ.get("FLYWAY_SQL_DIR", "/app/db/migration/postgres/common")
    cmd = [
        "flyway",
        f"-url={jdbc}",
        f"-user={user}",
        f"-password={password}",
        "-connectRetries=60",
        f"-locations=filesystem:{sql_dir}",
        "migrate",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
