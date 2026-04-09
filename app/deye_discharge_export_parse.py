"""Parse ``exportSession`` / hit flags from ``discharge_soc_delta_then_zero_export_ct`` API payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def parse_discharge_export_session_times(
    result: dict[str, Any],
) -> tuple[Optional[datetime], Optional[datetime], Optional[bool]]:
    """Read UTC bounds and hit-target from a discharge result dict."""
    raw = result.get("exportSession")
    hit_top = result.get("hitTarget")
    if not isinstance(raw, dict):
        return None, None, bool(hit_top) if isinstance(hit_top, bool) else None
    started = raw.get("startedAt")
    ended = raw.get("endedAt")
    hit = raw.get("hitTarget", hit_top)
    t0: Optional[datetime] = None
    t1: Optional[datetime] = None
    if isinstance(started, str) and started.strip():
        try:
            t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
        except ValueError:
            t0 = None
    if isinstance(ended, str) and ended.strip():
        try:
            t1 = datetime.fromisoformat(ended.replace("Z", "+00:00"))
            if t1.tzinfo is None:
                t1 = t1.replace(tzinfo=timezone.utc)
        except ValueError:
            t1 = None
    hit_b: Optional[bool] = bool(hit) if isinstance(hit, bool) else None
    if hit_b is None and isinstance(hit, (int, float)):
        hit_b = bool(hit)
    return t0, t1, hit_b
