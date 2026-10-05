"""Telegram alerts for new marketplace location submissions."""

from __future__ import annotations

import html
import logging
from typing import Any

from app import settings
from app.telegram_notify import send_telegram_message

logger = logging.getLogger(__name__)


_MIN_RENT_LABELS = {
    "1": "1 рік",
    "2": "2 роки",
    "3": "3 роки",
    "5": "5 років",
    "5+": "5+ років",
}


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
        lines.append(f"Орендна плата за одне паркомісце: {int(row.monthly_price_parking)} ₴/міс")
    if getattr(row, "min_rent_years", None):
        rent_label = _MIN_RENT_LABELS.get(str(row.min_rent_years), str(row.min_rent_years))
        lines.append(f"Мінімальний строк оренди: {html.escape(rent_label)}")
    if getattr(row, "restroom_coffee_nearby", None) is not None:
        lines.append(f"Вбиральня і кава поруч: {_format_contract(row.restroom_coffee_nearby)}")
    if getattr(row, "more_stations_possible", None) is not None:
        lines.append(f"Більше станцій у майбутньому: {_format_contract(row.more_stations_possible)}")
    if getattr(row, "parking_spaces_now", None) is not None:
        lines.append(f"Паркомісць зараз: {int(row.parking_spaces_now)}")
    if getattr(row, "parking_spaces_future", None) is not None:
        lines.append(f"Паркомісць на перспективу: {int(row.parking_spaces_future)}")
    if getattr(row, "landlord_legal_form", None):
        lines.append(f"Орендодавець: {html.escape(str(row.landlord_legal_form))}")
    lines.extend(
        [
            f"ID: <code>{html.escape(str(row.id))}</code>",
            "",
            f'<a href="{html.escape(admin_url)}">Відкрити модерацію</a>',
        ]
    )
    if str(row.request_type or "").upper() == "PROPOSE":
        lines.extend(["", "#new_location_proposed"])
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
