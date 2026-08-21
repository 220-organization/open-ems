"""Monobank invoice helpers for paid RDN consultation (Open EMS)."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Any, Dict, Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

MONOBANK_INVOICE_CREATE_URL = "https://api.monobank.ua/api/merchant/invoice/create"
MONOBANK_INVOICE_STATUS_URL = "https://api.monobank.ua/api/merchant/invoice/status?invoiceId="
MONOBANK_INVOICE_PAYMENT_INFO_URL = (
    "https://api.monobank.ua/api/merchant/invoice/payment-info?invoiceId="
)

# Same merchant token default as marketplace (220-km Monobank acquiring).
DEFAULT_PAYMENT_TOKEN = "m3T8ApHvapXSmUL1yLZHYlw"

# Amount must be an integer multiple of 100 within [MIN, MAX].
MIN_AMOUNT_UAH = 200
MAX_AMOUNT_UAH = 20_000
AMOUNT_STEP_UAH = 100

PAYMENT_DESCRIPTION = "Консультація з налаштування Open EMS (Вирій ЕМС)"


def is_valid_amount_uah(amount_uah: int) -> bool:
    try:
        value = int(amount_uah)
    except (TypeError, ValueError):
        return False
    if value < MIN_AMOUNT_UAH or value > MAX_AMOUNT_UAH:
        return False
    return value % AMOUNT_STEP_UAH == 0


def payment_token() -> str:
    return (
        os.environ.get("RDN_CONSULTATION_PAYMENT_TOKEN")
        or os.environ.get("MARKETPLACE_PAYMENT_TOKEN")
        or DEFAULT_PAYMENT_TOKEN
    ).strip()


def is_test_payment_enabled() -> bool:
    """
    Explicit RDN_CONSULTATION_ALLOW_TEST_PAYMENT wins.
    Default ON for local split-dev (OPEN_EMS_SERVE_SPA=0 from ./run-local.sh).
    """
    raw = (os.environ.get("RDN_CONSULTATION_ALLOW_TEST_PAYMENT") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    spa = (os.environ.get("OPEN_EMS_SERVE_SPA") or "1").strip().lower()
    return spa in ("0", "false", "no", "off")


def amount_uah_to_cents(amount_uah: int) -> int:
    return int(amount_uah) * 100


def with_query(url: str, **extra: Any) -> str:
    parts = urlparse((url or "").strip())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in extra.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = str(value)
    return urlunparse(parts._replace(query=urlencode(query)))


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


def create_consultation_invoice(
    *,
    amount_uah: int,
    redirect_url: str,
    reference: str,
    webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    if not is_valid_amount_uah(amount_uah):
        raise ValueError(
            f"Unsupported amount_uah: {amount_uah} "
            f"(allowed {MIN_AMOUNT_UAH}–{MAX_AMOUNT_UAH})"
        )
    amount_cents = amount_uah_to_cents(amount_uah)
    payload: Dict[str, Any] = {
        "amount": amount_cents,
        "ccy": 980,
        "merchantPaymInfo": {
            "reference": reference,
            "destination": PAYMENT_DESCRIPTION,
            "comment": PAYMENT_DESCRIPTION,
            "basketOrder": [
                {
                    "name": PAYMENT_DESCRIPTION,
                    "qty": 1,
                    "sum": amount_cents,
                    "total": amount_cents,
                    "unit": "шт",
                    "code": f"rdn-consult-{amount_uah}",
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


def fetch_invoice_status(invoice_id: str) -> Optional[str]:
    if not invoice_id:
        return None
    try:
        data = _call_monobank(f"{MONOBANK_INVOICE_STATUS_URL}{invoice_id}")
    except RuntimeError:
        try:
            data = _call_monobank(f"{MONOBANK_INVOICE_PAYMENT_INFO_URL}{invoice_id}")
        except RuntimeError:
            return None
    status = data.get("status")
    return str(status).upper() if status else None
