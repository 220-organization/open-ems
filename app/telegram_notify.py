"""Telegram notifications for Open EMS (support 220 chat)."""

from __future__ import annotations

import html
import logging
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from app import settings

logger = logging.getLogger(__name__)


async def send_telegram_message(text_msg: str, *, chat_id: Optional[str] = None) -> bool:
    """
    Send HTML message to support chat.
    Returns True on success. Never raises — logs failures.
    """
    token = (settings.TELEGRAM_API_TOKEN or "").strip()
    target = (chat_id or settings.TELEGRAM_SUPPORT_CHAT_ID or "").strip()
    if not token or not target:
        logger.warning("Telegram notify skipped: token or chat_id missing")
        return False
    params = {
        "chat_id": target,
        "text": text_msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    url = f"https://api.telegram.org/bot{token}/sendMessage?{urlencode(params)}"
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                logger.error(
                    "Telegram send failed status=%s body=%s",
                    resp.status_code,
                    (resp.text or "")[:300],
                )
                return False
        return True
    except Exception:
        logger.exception("Telegram send failed")
        return False


def format_bess_lead_message(
    *,
    kind: str,
    channel: Optional[str] = None,
    preset_id: Optional[str] = None,
    business_type: Optional[str] = None,
    units: Optional[int] = None,
    total_usd: Optional[float] = None,
    contact: Optional[str] = None,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    kit: Optional[dict[str, Any]] = None,
) -> str:
    """Build Ukrainian HTML alert for Order BESS contact / discount lead."""
    biz_labels = {
        "fop": "ФОП (без ПДВ)",
        "vat": "Платник ПДВ",
        "cash": "За готівку",
    }
    channel_labels = {
        "telegram": "Telegram",
        "whatsapp": "WhatsApp",
    }
    title = {
        "offer": "Хоче пропозицію Order BESS",
        "contact": "Хоче пропозицію Order BESS",
        "discount": "Хоче знижку Order BESS",
    }.get(kind, "Order BESS")
    hashtag = {
        "offer": "#OrderBessOffer",
        "contact": "#OrderBessOffer",
        "discount": "#OrderBessDiscount",
    }.get(kind, "#OrderBess")

    kw = kit.get("kw") if isinstance(kit, dict) else None
    kwh = kit.get("kwh") if isinstance(kit, dict) else None
    lines_count = None
    if isinstance(kit, dict) and isinstance(kit.get("lines"), list):
        lines_count = len(kit["lines"])

    lines = [
        f"<b>{html.escape(title)}</b>",
        "",
    ]
    if channel:
        lines.append(f"Канал: <b>{html.escape(channel_labels.get(channel, channel))}</b>")
    if name:
        lines.append(f"Імʼя: {html.escape(name)}")
    if phone:
        lines.append(f"Телефон: {html.escape(phone)}")
    if contact and not (name or phone):
        lines.append(f"Контакт клієнта: {html.escape(contact)}")
    if preset_id:
        lines.append(f"Пресет: <code>{html.escape(str(preset_id))}</code>")
    if business_type:
        lines.append(
            f"Тип ціни: {html.escape(biz_labels.get(business_type, business_type))}"
        )
    if kw is not None or kwh is not None:
        lines.append(f"Комплект: {html.escape(str(kw or '—'))} кВт + {html.escape(str(kwh or '—'))} кВт·год")
    if units is not None:
        lines.append(f"Кількість комплектів: <b>{int(units)}</b>")
        if total_usd is not None:
            order_total = float(total_usd) * int(units)
            lines.append(
                f"Сума ×{int(units)}: <b>${order_total:,.2f}</b>".replace(",", " ")
            )
    if total_usd is not None:
        lines.append(f"Сума за 1 комплект: <b>${float(total_usd):,.2f}</b>".replace(",", " "))
    if lines_count is not None:
        lines.append(f"Позицій у BOM: {lines_count}")
    lines.extend(["", hashtag, "https://ems.220-km.com/order-bess"])
    return "\n".join(lines)
