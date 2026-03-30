"""Per-IP sliding-window rate limit (in-process). Behind a reverse proxy, configure X-Forwarded-For."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Deque, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def client_ip_from_request(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host
    return "unknown"


def should_rate_limit_path(path: str) -> bool:
    if path == "/health":
        return False
    if path.startswith("/static/"):
        return False
    return True


class InMemoryIpRateLimiter:
    """Sliding window: at most `max_hits` timestamps per client in the last `window_sec`."""

    def __init__(self, max_hits: int, window_sec: float) -> None:
        self._max_hits = max_hits
        self.window_sec = window_sec
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, client_id: str) -> tuple[bool, int]:
        """Returns (allowed, current_count_in_window)."""
        now = time.monotonic()
        cutoff = now - self.window_sec
        async with self._lock:
            q = self._hits[client_id]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self._max_hits:
                return False, len(q)
            q.append(now)
            return True, len(q)


class PerIpRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable,
        *,
        limiter: InMemoryIpRateLimiter,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._enabled:
            return await call_next(request)
        path = request.url.path
        if not should_rate_limit_path(path):
            return await call_next(request)

        client_id = client_ip_from_request(request)
        allowed, _n = await self._limiter.allow(client_id)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests from this address. Try again in about one minute.",
                },
                headers={"Retry-After": str(int(self._limiter.window_sec))},
            )
        return await call_next(request)
