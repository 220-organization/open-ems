"""Buy requests from the charger catalogs — phone callback leads to support chat."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.telegram_notify import (
    format_charger_buy_request_message,
    send_telegram_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/charger-buy-request", tags=["charger-buy-request"])

MIN_PHONE_LEN = 5


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
async def create_buy_request(payload: BuyRequestBody) -> BuyRequestResponse:
    """Notify support chat about a buy request. The user never leaves the catalog."""
    phone = (payload.phone or "").strip()
    if len(phone) < MIN_PHONE_LEN:
        raise HTTPException(status_code=400, detail="phone is required")

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

    logger.info(
        "Charger buy request notified catalog=%s sku=%s",
        payload.catalog,
        payload.sku,
    )
    return BuyRequestResponse(ok=True, notified=True)
