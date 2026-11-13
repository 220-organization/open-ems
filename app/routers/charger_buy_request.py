"""Buy requests from the charger catalogs — phone callback leads to support chat."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, Literal, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.rate_limit_middleware import client_ip_from_request
from app.telegram_notify import (
    format_charger_buy_request_message,
    send_telegram_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/charger-buy-request", tags=["charger-buy-request"])

MIN_PHONE_LEN = 5
MAX_BUY_REQUESTS_PER_IP_PER_DAY = 2
_KYIV = ZoneInfo("Europe/Kyiv")

# ip -> (kyiv_date_iso, count) for successful submissions today
_ip_day_counts: Dict[str, Tuple[str, int]] = {}
_ip_day_lock = asyncio.Lock()


def _today_kyiv_iso() -> str:
    return datetime.now(_KYIV).date().isoformat()


async def buy_request_allowed_for_ip(ip: str) -> tuple[bool, int]:
    """Return (allowed, used_today) without recording a hit."""
    day = _today_kyiv_iso()
    async with _ip_day_lock:
        prev_day, count = _ip_day_counts.get(ip, (day, 0))
        if prev_day != day:
            count = 0
        return count < MAX_BUY_REQUESTS_PER_IP_PER_DAY, count


async def record_buy_request_for_ip(ip: str) -> int:
    """Increment the daily counter for a successful submission. Returns new count."""
    day = _today_kyiv_iso()
    async with _ip_day_lock:
        prev_day, count = _ip_day_counts.get(ip, (day, 0))
        if prev_day != day:
            count = 0
        count += 1
        _ip_day_counts[ip] = (day, count)
        return count


def reset_buy_request_rate_limits_for_tests() -> None:
    _ip_day_counts.clear()


class BuyRequestBody(BaseModel):
    catalog: Literal["home", "commercial"]
    phone: str = Field(max_length=40)
    name: Optional[str] = Field(None, max_length=200)
    title: Optional[str] = Field(None, max_length=300)
    sku: Optional[str] = Field(None, max_length=120)
    price: Optional[str] = Field(None, max_length=60)
    page_url: Optional[str] = Field(None, max_length=600)
    product_url: Optional[str] = Field(None, max_length=600)


class BuyRequestResponse(BaseModel):
    ok: bool = True
    notified: bool = False


@router.post("", response_model=BuyRequestResponse)
async def create_buy_request(
    payload: BuyRequestBody, request: Request
) -> BuyRequestResponse:
    """Notify support chat about a buy request. The user never leaves the catalog."""
    phone = (payload.phone or "").strip()
    if len(phone) < MIN_PHONE_LEN:
        raise HTTPException(status_code=400, detail="phone is required")

    client_ip = client_ip_from_request(request)
    allowed, used = await buy_request_allowed_for_ip(client_ip)
    if not allowed:
        logger.warning(
            "Charger buy request rate-limited ip=%s used=%s/%s",
            client_ip,
            used,
            MAX_BUY_REQUESTS_PER_IP_PER_DAY,
        )
        raise HTTPException(
            status_code=429,
            detail="Too many buy requests from this IP today (max 2 per day)",
            headers={"Retry-After": "86400"},
        )

    msg = format_charger_buy_request_message(
        catalog=payload.catalog,
        phone=phone,
        name=(payload.name or "").strip() or None,
        title=(payload.title or "").strip() or None,
        sku=(payload.sku or "").strip() or None,
        price=(payload.price or "").strip() or None,
        page_url=(payload.page_url or "").strip() or None,
        product_url=(payload.product_url or "").strip() or None,
    )
    notified = await send_telegram_message(msg)
    if not notified:
        raise HTTPException(status_code=502, detail="Unable to notify support")

    new_count = await record_buy_request_for_ip(client_ip)
    logger.info(
        "Charger buy request notified catalog=%s sku=%s ip=%s day_count=%s",
        payload.catalog,
        payload.sku,
        client_ip,
        new_count,
    )
    return BuyRequestResponse(ok=True, notified=True)
