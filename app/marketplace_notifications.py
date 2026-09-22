"""Telegram alerts for new marketplace location submissions."""

from __future__ import annotations

import html
import logging
from typing import Any

from app import settings
from app.telegram_notify import send_telegram_message

logger = logging.getLogger(__name__)


def _format_contract(value: Any) -> str:
    if value is True:
        return "Так"
    if value is False:
        return "Ні"
    return "—"


def _build_submission_message(row) -> str:
    locations = row.locations or []
    location_lines = []
    for index, loc in enumerate(locations[:3], start=1):
        label = html.escape(str(loc.get("label") or "—"))
        location_lines.append(f"{index}. {label}")
    if len(locations) > 3:
        location_lines.append(f"… +{len(locations) - 3}")

    admin_url = settings.MARKETPLACE_ADMIN_UI_URL
    lines = [
        "<b>Нова заявка B2B маркетплейс</b>",
        "",
        f"Тип: <b>{html.escape(str(row.request_type or ''))}</b>",
        f"Імʼя: {html.escape(str(row.name or ''))}",
        f"Телефон: {html.escape(str(row.phone or ''))}",
        f"Потужність: {html.escape(str(row.kw_available or ''))} кВт",
        f"Договір на розподіл: {_format_contract(row.distribution_contract)}",
        f"Точок на карті: {len(locations)}",
    ]
    if location_lines:
        lines.append("Локації:")
        lines.extend(location_lines)
    if row.distance_meters is not None:
        lines.append(f"Відстань до приєднання: {row.distance_meters} м")
    if row.price_per_kwh_extra is not None:
        lines.append(f"Ціна за кВт·год (додатково): {float(row.price_per_kwh_extra):.1f} ₴")
    if row.monthly_price_parking is not None:
        lines.append(f"Місячна ціна за паркомісце: {int(row.monthly_price_parking)} ₴")
    lines.extend(
        [
            f"ID: <code>{html.escape(str(row.id))}</code>",
            "",
            f'<a href="{html.escape(admin_url)}">Відкрити модерацію</a>',
        ]
    )
    return "\n".join(lines)


async def notify_marketplace_submission_pending(row) -> None:
    message = _build_submission_message(row)
    try:
        ok = await send_telegram_message(message)
        if ok:
            logger.info("Marketplace submission alert sent for %s", row.id)
        else:
            logger.warning("Marketplace submission alert skipped for %s", row.id)
    except Exception as exc:
        logger.error("Failed to send marketplace submission alert for %s: %s", row.id, exc)
