"""Approximate client IP geolocation for driver tracker (city-level fallback)."""

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ip -> (monotonic_ts, lat, lon)
_cache: dict[str, tuple[float, float, float]] = {}
_CACHE_TTL_SEC = 86400.0


def _normalize_ip(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    ip = raw.split(",")[0].strip()
    if not ip or ip in ("127.0.0.1", "::1", "unknown"):
        return None
    return ip


def client_ip_from_headers(forwarded_for: Optional[str], client_host: Optional[str]) -> Optional[str]:
    return _normalize_ip(forwarded_for) or _normalize_ip(client_host)


async def resolve_ip_lat_lon(ip: Optional[str]) -> Optional[tuple[float, float]]:
    """City-level lat/lon from public IP; cached 24h. Returns None on failure."""
    normalized = _normalize_ip(ip)
    if not normalized:
        return None

    now = time.monotonic()
    cached = _cache.get(normalized)
    if cached and now - cached[0] < _CACHE_TTL_SEC:
        return cached[1], cached[2]

    url = f"http://ip-api.com/json/{normalized}?fields=status,lat,lon"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
        if response.status_code != 200:
            return None
        data = response.json()
        if data.get("status") != "success":
            return None
        lat = float(data["lat"])
        lon = float(data["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        _cache[normalized] = (now, lat, lon)
        return lat, lon
    except Exception as exc:
        logger.debug("IP geolocation failed for %s: %s", normalized, exc)
        return None
