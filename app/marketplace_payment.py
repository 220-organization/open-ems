"""Monobank invoice helpers for marketplace location unlock / publication / heatmap."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Dict, Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import UUID

from app import settings

logger = logging.getLogger(__name__)

MONOBANK_INVOICE_CREATE_URL = "https://api.monobank.ua/api/merchant/invoice/create"
MONOBANK_INVOICE_PAYMENT_INFO_URL = (
    "https://api.monobank.ua/api/merchant/invoice/payment-info?invoiceId="
)

DEFAULT_PAYMENT_TOKEN = "m3T8ApHvapXSmUL1yLZHYlw"

PAYMENT_DESCRIPTION = (
    "Доступ до контактних даних власника локації маркетплейсу 220-km.com"
)
LOOKING_INFO_PAYMENT_DESCRIPTION = (
    "Доступ до контактних даних заявки «Шукаю локацію» маркетплейсу 220-km.com"
)
PUBLICATION_PAYMENT_DESCRIPTION = "Публікація заявки на маркетплейсі локацій 220-km.com"
HEATMAP_PAYMENT_DESCRIPTION = (
    "Доступ до heatmap маркетплейсу 220-km.com (детальний zoom до кінця дня)"
)


def payment_token() -> str:
    return (settings.MARKETPLACE_PAYMENT_TOKEN or DEFAULT_PAYMENT_TOKEN).strip()


def propose_info_payment_amount_cents() -> int:
    return max(100, int(settings.MARKETPLACE_PROPOSE_INFO_PAYMENT_CENTS))


def looking_info_payment_amount_cents() -> int:
    return max(100, int(settings.MARKETPLACE_LOOKING_INFO_PAYMENT_CENTS))


def publication_payment_amount_cents() -> int:
    return max(100, int(settings.MARKETPLACE_PUBLICATION_PAYMENT_CENTS))


def heatmap_payment_amount_cents() -> int:
    return max(100, int(settings.MARKETPLACE_HEATMAP_PAYMENT_CENTS))


def payment_callback_base() -> str:
    return settings.MARKETPLACE_PAYMENT_CALLBACK_BASE.rstrip("/")


def marketplace_pay_redirect_base() -> str:
    return settings.MARKETPLACE_PAY_REDIRECT_BASE.strip().rstrip("/")


def resolve_marketplace_pay_redirect_base(redirect_base_url: Optional[str]) -> str:
    candidate = (redirect_base_url or "").strip().rstrip("/")
    if candidate:
        return candidate
    return marketplace_pay_redirect_base()


def is_marketplace_test_payment_enabled() -> bool:
    if settings.MARKETPLACE_ALLOW_TEST_PAYMENT:
        return True
    # Local split-dev (API only) enables test payments by default.
    return not bool(settings.OPEN_EMS_SERVE_SPA)


def _delay_before_mono_api_call() -> None:
    time.sleep(random.uniform(0.5, 2.0))


def _call_monobank(
    url: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    _delay_before_mono_api_call()
    headers = {
        "Content-Type": "application/json",
        "X-Token": token or payment_token(),
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(url, data=data, headers=headers, method=method)
    try:
        with urlrequest.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        logger.error("Monobank API error %s: %s", exc.code, detail)
        raise RuntimeError(f"Monobank API error ({exc.code})") from exc
    except urlerror.URLError as exc:
        logger.error("Monobank API unreachable: %s", exc)
        raise RuntimeError("Monobank API unreachable") from exc


def _webhook_url() -> str:
    return f"{payment_callback_base()}/api/marketplace/payments/mono-callback"


def create_marketplace_info_invoice(
    *,
    payment_id: UUID,
    location_id: UUID,
    redirect_url: str,
    amount_cents: Optional[int] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    amount = amount_cents if amount_cents is not None else propose_info_payment_amount_cents()
    desc = description or PAYMENT_DESCRIPTION
    payload = {
        "amount": amount,
        "ccy": 980,
        "merchantPaymInfo": {
            "reference": str(payment_id),
            "destination": desc,
            "comment": desc,
            "basketOrder": [
                {
                    "name": "Location owner contact info",
                    "qty": 1,
                    "sum": amount,
                    "total": amount,
                    "unit": "шт",
                    "code": str(location_id),
                }
            ],
        },
        "redirectUrl": redirect_url,
        "webHookUrl": _webhook_url(),
        "validity": 3600,
        "paymentType": "debit",
    }
    return _call_monobank(MONOBANK_INVOICE_CREATE_URL, method="POST", payload=payload)


def create_marketplace_publication_invoice(
    *,
    payment_id: UUID,
    redirect_url: str,
) -> Dict[str, Any]:
    amount_cents = publication_payment_amount_cents()
    payload = {
        "amount": amount_cents,
        "ccy": 980,
        "merchantPaymInfo": {
            "reference": str(payment_id),
            "destination": PUBLICATION_PAYMENT_DESCRIPTION,
            "comment": PUBLICATION_PAYMENT_DESCRIPTION,
            "basketOrder": [
                {
                    "name": "Marketplace location publication",
                    "qty": 1,
                    "sum": amount_cents,
                    "total": amount_cents,
                    "unit": "шт",
                    "code": "publication",
                }
            ],
        },
        "redirectUrl": redirect_url,
        "webHookUrl": _webhook_url(),
        "validity": 3600,
        "paymentType": "debit",
    }
    return _call_monobank(MONOBANK_INVOICE_CREATE_URL, method="POST", payload=payload)


def create_marketplace_heatmap_invoice(
    *,
    payment_id: UUID,
    redirect_url: str,
) -> Dict[str, Any]:
    amount_cents = heatmap_payment_amount_cents()
    payload = {
        "amount": amount_cents,
        "ccy": 980,
        "merchantPaymInfo": {
            "reference": str(payment_id),
            "destination": HEATMAP_PAYMENT_DESCRIPTION,
            "comment": HEATMAP_PAYMENT_DESCRIPTION,
            "basketOrder": [
                {
                    "name": "Marketplace heatmap zoom access",
                    "qty": 1,
                    "sum": amount_cents,
                    "total": amount_cents,
                    "unit": "шт",
                    "code": "heatmap_zoom",
                }
            ],
        },
        "redirectUrl": redirect_url,
        "webHookUrl": _webhook_url(),
        "validity": 3600,
        "paymentType": "debit",
    }
    return _call_monobank(MONOBANK_INVOICE_CREATE_URL, method="POST", payload=payload)


def fetch_invoice_status(invoice_id: str) -> Optional[str]:
    if not invoice_id:
        return None
    try:
        data = _call_monobank(f"{MONOBANK_INVOICE_PAYMENT_INFO_URL}{invoice_id}")
    except RuntimeError:
        return None
    status = data.get("status")
    return str(status).upper() if status else None
