"""In-memory ring buffer for recent application log lines (UI tail view)."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Optional

_handler: Optional["RingBufferHandler"] = None


class RingBufferHandler(logging.Handler):
    """Keep the last N formatted log lines for GET /api/server-logs."""

    def __init__(self, capacity: int = 500):
        super().__init__()
        self._buf: deque[str] = deque(maxlen=max(50, int(capacity)))
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock:
                self._buf.append(msg)
        except Exception:
            self.handleError(record)

    def tail(self, limit: int = 50) -> list[str]:
        n = max(1, min(int(limit), len(self._buf) or 1, 500))
        with self._lock:
            return list(self._buf)[-n:]


def install_log_buffer(capacity: int = 500) -> RingBufferHandler:
    global _handler
    if _handler is not None:
        return _handler
    handler = RingBufferHandler(capacity)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.addHandler(handler)
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        if handler not in lg.handlers:
            lg.addHandler(handler)
    _handler = handler
    return handler


def log_buffer_tail(limit: int = 50) -> list[str]:
    if _handler is None:
        return []
    return _handler.tail(limit)
