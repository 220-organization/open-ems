"""ICS feed of admin bookings so Google Calendar can subscribe."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app import settings

KYIV = ZoneInfo("Europe/Kyiv")
SLOT_MINUTES = 60
_LABEL = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[,\s]+(\d{1,2}):(\d{2}))?")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2}))?")
_CANCELLED = frozenset({"cancelled", "canceled", "deleted", "rejected", "hidden"})


def calendar_feed_token() -> str:
    """Stable secret for the public ICS URL. Not the admin API token."""
    explicit = (os.environ.get("OPEN_EMS_ADMIN_CALENDAR_TOKEN") or "").strip()
    if explicit:
        return explicit
    secret = (settings.OPEN_EMS_ADMIN_TOKEN or "open-ems").encode("utf-8")
    return hmac.new(secret, b"admin-calendar-ics", hashlib.sha256).hexdigest()


def calendar_feed_token_ok(provided: Optional[str]) -> bool:
    expected = calendar_feed_token()
    given = (provided or "").strip()
    if not expected or not given:
        return False
    return hmac.compare_digest(expected, given)


def public_origin() -> str:
    base = (settings.MARKETPLACE_PUBLIC_BASE_URL or "").strip().rstrip("/")
    if base:
        return base
    callback = (settings.MARKETPLACE_PAYMENT_CALLBACK_BASE or "").strip().rstrip("/")
    if callback:
        return callback
    return "https://220-km.com:9220"


def feed_url() -> str:
    token = quote(calendar_feed_token(), safe="")
    return f"{public_origin()}/api/admin/calendar.ics?token={token}"


def google_subscribe_url(feed: Optional[str] = None) -> str:
    """Open Google Calendar. ``cid`` must be webcal; an https cid is rejected."""
    target = feed or feed_url()
    if target.startswith("https://"):
        target = "webcal://" + target[len("https://"):]
    elif target.startswith("http://"):
        target = "webcal://" + target[len("http://"):]
    return "https://calendar.google.com/calendar/u/0/r?cid=" + quote(target, safe="")


def parse_slot(label: Optional[str]) -> Optional[datetime]:
    text = (label or "").strip()
    if not text:
        return None
    match = _LABEL.match(text)
    if match and match.group(4) is not None:
        start = datetime(
            int(match.group(3)),
            int(match.group(2)),
            int(match.group(1)),
            int(match.group(4)),
            int(match.group(5)),
            tzinfo=KYIV,
        )
        return start
    match = _ISO.match(text)
    if match and match.group(4) is not None:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            tzinfo=KYIV,
        )
    return None


def event_kind_label(row: dict[str, Any]) -> str:
    kind = str(row.get("kind") or "").strip().lower()
    group = str(row.get("calendar_group") or "").strip().lower()
    if kind == "bess_discount":
        return "Знижка ДБЖ"
    if kind.startswith("bess") or group == "bess":
        return "ДБЖ"
    if kind == "station" or group == "station":
        return "Станція"
    if kind == "callback":
        return "Дзвінок"
    return "Оплата"


def _ics_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold(line: str) -> str:
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts: list[str] = []
    start = 0
    first = True
    while start < len(encoded):
        limit = 75 if first else 74
        end = min(start + limit, len(encoded))
        while end > start:
            try:
                chunk = encoded[start:end].decode("utf-8")
            except UnicodeDecodeError:
                end -= 1
                continue
            parts.append(chunk)
            start = end
            break
        else:
            parts.append("?")
            start += 1
        first = False
    return "\r\n ".join(parts)


def _utc_stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _description(row: dict[str, Any], *, admin_url: str) -> str:
    lines = [f"{event_kind_label(row)} · {row.get('status') or ''}".strip(" ·")]
    phone = (row.get("phone") or "").strip()
    if phone:
        lines.append(f"Телефон: {phone}")
    title = (row.get("title") or "").strip()
    if title:
        lines.append(title)
    amount = row.get("amount_uah")
    if amount not in (None, ""):
        lines.append(f"Сума: {amount} грн")
    amount_label = (row.get("amount_label") or "").strip()
    if amount_label:
        lines.append(f"Сума: {amount_label}")
    description = (row.get("description") or "").strip()
    if description:
        lines.append(description)
    if admin_url:
        lines.append(admin_url)
    return "\n".join(lines)[:1800]


def _summary(row: dict[str, Any]) -> str:
    name = (row.get("name") or "").strip() or "—"
    status = (row.get("status") or "").strip()
    label = event_kind_label(row)
    tail = f"{label} · {status}" if status else label
    return f"{name} — {tail}"


def _uid(row: dict[str, Any]) -> str:
    source = str(row.get("source") or row.get("calendar_group") or "admin").strip() or "admin"
    row_id = str(row.get("id") or "").strip() or "row"
    return f"{source}-{row_id}@220-km.com"


def build_ics(items: list[dict[str, Any]], *, admin_url: str = "") -> str:
    now = datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//220-km.com//Admin//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:220 km admin",
        "X-WR-TIMEZONE:Europe/Kyiv",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    dated: list[tuple[datetime, dict[str, Any]]] = []
    for row in items:
        start = parse_slot(row.get("slot_label")) or parse_slot(row.get("slot_id"))
        if start is None:
            continue
        dated.append((start, row))
    dated.sort(key=lambda pair: pair[0])
    for start, row in dated:
        end = start + timedelta(minutes=SLOT_MINUTES)
        status = str(row.get("status") or "").strip().lower()
        ics_status = "CANCELLED" if status in _CANCELLED else "CONFIRMED"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{_ics_text(_uid(row))}",
                f"DTSTAMP:{_utc_stamp(now)}",
                f"DTSTART:{_utc_stamp(start)}",
                f"DTEND:{_utc_stamp(end)}",
                f"SUMMARY:{_ics_text(_summary(row))}",
                f"DESCRIPTION:{_ics_text(_description(row, admin_url=admin_url))}",
                f"STATUS:{ics_status}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
