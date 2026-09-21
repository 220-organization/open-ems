"""Emulated RDN consultation calendar: 3 windows/day for the next 2 weeks, ~20% busy."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
SLOT_DAYS = 14
BUSY_RATIO = 0.20
# Three consultation windows per Kyiv calendar day.
WINDOWS: tuple[time, ...] = (time(10, 0), time(14, 0), time(18, 0))


def _kyiv_now(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(KYIV)
    if now.tzinfo is None:
        return now.replace(tzinfo=KYIV)
    return now.astimezone(KYIV)


def slot_id_for(day: date, window: time) -> str:
    return f"{day.isoformat()}T{window.strftime('%H:%M')}"


def slot_label_uk(slot_id: str) -> str:
    """Human label in Ukrainian-style ``21.09.2026, 14:00``."""
    try:
        day_s, hm = slot_id.split("T", 1)
        y, m, d = day_s.split("-")
        return f"{d}.{m}.{y}, {hm}"
    except ValueError:
        return slot_id


def _busy_ids(candidate_ids: list[str]) -> set[str]:
    """Stable ~20% busy set (hash order, not random per request)."""
    if not candidate_ids:
        return set()
    n_busy = int(round(len(candidate_ids) * BUSY_RATIO))
    ranked = sorted(
        candidate_ids,
        key=lambda sid: hashlib.sha256(sid.encode("utf-8")).hexdigest(),
    )
    return set(ranked[:n_busy])


def list_consultation_days(now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Next ``SLOT_DAYS`` Kyiv days, each with 3 windows. Past windows are not bookable."""
    now_k = _kyiv_now(now)
    today = now_k.date()
    future_ids: list[str] = []
    skeleton: list[dict[str, Any]] = []
    for offset in range(SLOT_DAYS):
        day = today + timedelta(days=offset)
        windows: list[dict[str, Any]] = []
        for window in WINDOWS:
            start = datetime.combine(day, window, tzinfo=KYIV)
            sid = slot_id_for(day, window)
            past = start <= now_k
            windows.append(
                {
                    "id": sid,
                    "start": start.isoformat(),
                    "label": window.strftime("%H:%M"),
                    "past": past,
                }
            )
            if not past:
                future_ids.append(sid)
        skeleton.append({"date": day.isoformat(), "windows": windows})

    busy = _busy_ids(future_ids)
    days: list[dict[str, Any]] = []
    for row in skeleton:
        windows_out: list[dict[str, Any]] = []
        for w in row["windows"]:
            is_busy = (not w["past"]) and w["id"] in busy
            available = (not w["past"]) and (not is_busy)
            windows_out.append(
                {
                    "id": w["id"],
                    "start": w["start"],
                    "label": w["label"],
                    "busy": is_busy,
                    "past": w["past"],
                    "available": available,
                }
            )
        days.append(
            {
                "date": row["date"],
                "windows": windows_out,
                "hasAvailable": any(w["available"] for w in windows_out),
            }
        )
    return days


def find_slot(slot_id: str, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    sid = (slot_id or "").strip()
    if not sid:
        return None
    for day in list_consultation_days(now):
        for window in day["windows"]:
            if window["id"] == sid:
                return window
    return None


def require_available_slot(slot_id: Optional[str], now: Optional[datetime] = None) -> dict[str, Any]:
    """Return the window dict or raise ValueError."""
    found = find_slot(slot_id or "", now)
    if found is None:
        raise ValueError("Unknown or expired consultation slot")
    if not found.get("available"):
        raise ValueError("Consultation slot is not available")
    return found
