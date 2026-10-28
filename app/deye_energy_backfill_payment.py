"""Monobank invoice helpers for paid Deye energy backfill (22 UAH per day)."""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Dict, Optional

from app.rdn_consultation_payment import (
    _call_monobank,
    amount_uah_to_cents,
    MONOBANK_INVOICE_CREATE_URL,
    with_query,
)

logger = logging.getLogger(__name__)

BACKFILL_UAH_PER_DAY = 22
BACKFILL_ACCESS_PASSWORD = "AA9220YD"
BACKFILL_PAYMENT_DESCRIPTION = "Open EMS · Deye kWh backfill"
BACKFILL_MAX_DAYS = 400
BACKFILL_MAX_AMOUNT_UAH = BACKFILL_UAH_PER_DAY * BACKFILL_MAX_DAYS


def is_backfill_free_enabled() -> bool:
    """
    Free backfill without Monobank — local ./run-local.sh only.

    Do **not** key off OPEN_EMS_SERVE_SPA: production can also run SPA=0 and must still charge.
    """
    raw = (os.environ.get("DEYE_BACKFILL_ALLOW_FREE") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def backfill_amount_uah(days: int) -> int:
    n = max(0, int(days))
    return n * BACKFILL_UAH_PER_DAY


def is_valid_backfill_amount_uah(amount_uah: int, days: int) -> bool:
    try:
        value = int(amount_uah)
        d = int(days)
    except (TypeError, ValueError):
        return False
    if d < 1 or d > BACKFILL_MAX_DAYS:
        return False
    return value == backfill_amount_uah(d) and 0 < value <= BACKFILL_MAX_AMOUNT_UAH


def access_password_ok(submitted: Optional[str]) -> bool:
    got = (submitted or "").strip()
    if not got:
        return False
    return hmac.compare_digest(got, BACKFILL_ACCESS_PASSWORD)


def create_backfill_invoice(
    *,
    amount_uah: int,
    days: int,
    redirect_url: str,
    reference: str,
    webhook_url: Optional[str] = None,
    description: str = BACKFILL_PAYMENT_DESCRIPTION,
) -> Dict[str, Any]:
    if not is_valid_backfill_amount_uah(amount_uah, days):
        raise ValueError(f"Unsupported backfill amount_uah={amount_uah} days={days}")
    amount_cents = amount_uah_to_cents(amount_uah)
    dest = f"{description} ({days} дн.)"
    payload: Dict[str, Any] = {
        "amount": amount_cents,
        "ccy": 980,
        "merchantPaymInfo": {
            "reference": reference,
            "destination": dest,
            "comment": dest,
            "basketOrder": [
                {
                    "name": dest,
                    "qty": days,
                    "sum": amount_uah_to_cents(BACKFILL_UAH_PER_DAY),
                    "total": amount_cents,
                    "unit": "дн",
                    "code": f"deye-backfill-{days}d-{amount_uah}",
                }
            ],
        },
        "redirectUrl": redirect_url,
        "validity": 3600,
        "paymentType": "debit",
    }
    if webhook_url:
        payload["webHookUrl"] = webhook_url
    return _call_monobank(MONOBANK_INVOICE_CREATE_URL, method="POST", payload=payload)


__all__ = [
    "BACKFILL_UAH_PER_DAY",
    "BACKFILL_ACCESS_PASSWORD",
    "access_password_ok",
    "backfill_amount_uah",
    "create_backfill_invoice",
    "is_valid_backfill_amount_uah",
    "with_query",
]
