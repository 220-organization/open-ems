"""Paid RDN consultation — Monobank checkout + status poll + support Telegram notify."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.rdn_consultation_payment import (
    MAX_AMOUNT_UAH,
    MIN_AMOUNT_UAH,
    create_consultation_invoice,
    fetch_invoice_status,
    is_test_payment_enabled,
    is_valid_amount_uah,
    with_query,
)
from app.telegram_notify import (
    format_rdn_consultation_callback_message,
    format_rdn_consultation_paid_message,
    send_telegram_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rdn-consultation", tags=["rdn-consultation"])

SUCCESS_STATUSES = frozenset({"SUCCESS"})
# In-memory map: our payment_id → invoice metadata (survives until process restart).
_PENDING: dict[str, dict] = {}


class PayCreateRequest(BaseModel):
    amount_uah: int = Field(
        ...,
        description=f"Consultation amount in UAH ({MIN_AMOUNT_UAH}–{MAX_AMOUNT_UAH})",
    )
    redirect_url: str = Field(..., min_length=8, max_length=2000)
    name: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)


class PayCreateResponse(BaseModel):
    payment_id: str
    invoice_id: str
    page_url: str
    amount_uah: int


class PayStatusResponse(BaseModel):
    payment_id: str
    invoice_id: str
    status: str
    amount_uah: int
    name: Optional[str] = None
    phone: Optional[str] = None


class PayTestRequest(BaseModel):
    amount_uah: int = Field(
        ...,
        description=f"Consultation amount in UAH ({MIN_AMOUNT_UAH}–{MAX_AMOUNT_UAH})",
    )
    name: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)


def _public_webhook_url(request: Request) -> Optional[str]:
    host = (request.headers.get("x-forwarded-host") or request.url.hostname or "").split(",")[0].strip()
    if not host or host in {"localhost", "127.0.0.1"}:
        return None
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    return f"{proto}://{host}/api/rdn-consultation/webhook"


def _status_response(payment_id: str, row: dict) -> PayStatusResponse:
    return PayStatusResponse(
        payment_id=payment_id,
        invoice_id=row["invoice_id"],
        status=str(row.get("status") or "created"),
        amount_uah=int(row["amount_uah"]),
        name=row.get("name"),
        phone=row.get("phone"),
    )


async def _notify_rdn_paid(row: dict) -> None:
    if str(row.get("status") or "").upper() not in SUCCESS_STATUSES:
        return
    if row.get("tg_notified") or row.get("tg_notify_started"):
        return
    row["tg_notify_started"] = True
    msg = format_rdn_consultation_paid_message(
        name=row.get("name") or "",
        phone=row.get("phone") or "",
        amount_uah=int(row.get("amount_uah") or 0),
    )
    ok = await send_telegram_message(msg)
    if ok:
        row["tg_notified"] = True
        logger.info("RDN consultation payment notified invoice=%s", row.get("invoice_id"))
    else:
        row["tg_notify_started"] = False
        logger.warning("RDN consultation TG notify failed invoice=%s", row.get("invoice_id"))


@router.post("/pay", response_model=PayCreateResponse)
async def create_pay(payload: PayCreateRequest, request: Request) -> PayCreateResponse:
    if not is_valid_amount_uah(payload.amount_uah):
        raise HTTPException(
            status_code=400,
            detail=f"amount_uah must be between {MIN_AMOUNT_UAH} and {MAX_AMOUNT_UAH}",
        )
    payment_id = str(uuid.uuid4())
    redirect_url = with_query(payload.redirect_url, rdnConsultPayment=payment_id)
    try:
        invoice = create_consultation_invoice(
            amount_uah=payload.amount_uah,
            redirect_url=redirect_url,
            reference=payment_id,
            webhook_url=_public_webhook_url(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception("Failed to create RDN consultation invoice")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    invoice_id = (invoice.get("invoiceId") or "").strip()
    page_url = (invoice.get("pageUrl") or "").strip()
    if not invoice_id or not page_url:
        raise HTTPException(status_code=502, detail="Invalid Monobank invoice response")

    _PENDING[payment_id] = {
        "invoice_id": invoice_id,
        "amount_uah": payload.amount_uah,
        "name": (payload.name or "").strip() or None,
        "phone": (payload.phone or "").strip() or None,
        "status": "created",
    }
    return PayCreateResponse(
        payment_id=payment_id,
        invoice_id=invoice_id,
        page_url=page_url,
        amount_uah=payload.amount_uah,
    )


@router.get("/payments/{payment_id}", response_model=PayStatusResponse)
async def get_payment_status(payment_id: str) -> PayStatusResponse:
    row = _PENDING.get(payment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    status = (row.get("status") or "created").upper()
    if status not in SUCCESS_STATUSES and status not in {"FAILURE", "EXPIRED", "REVERSED"}:
        remote = fetch_invoice_status(row["invoice_id"])
        if remote:
            status = remote
            row["status"] = status
    if status in SUCCESS_STATUSES:
        await _notify_rdn_paid(row)
    return _status_response(payment_id, row)


class InvoiceStatusRequest(BaseModel):
    invoice_id: str = Field(..., min_length=4, max_length=120)
    amount_uah: int = Field(
        ...,
        description=f"Consultation amount in UAH ({MIN_AMOUNT_UAH}–{MAX_AMOUNT_UAH})",
    )
    name: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)


@router.post("/invoice-status", response_model=PayStatusResponse)
async def post_invoice_status(payload: InvoiceStatusRequest) -> PayStatusResponse:
    """Fallback when in-memory payment map was lost after redirect (multi-restart)."""
    if not is_valid_amount_uah(payload.amount_uah):
        raise HTTPException(
            status_code=400,
            detail=f"amount_uah must be between {MIN_AMOUNT_UAH} and {MAX_AMOUNT_UAH}",
        )
    invoice_id = payload.invoice_id.strip()
    remote = fetch_invoice_status(invoice_id)
    if not remote:
        raise HTTPException(status_code=502, detail="Unable to fetch invoice status")
    row = next((r for r in _PENDING.values() if r.get("invoice_id") == invoice_id), None)
    if row is None:
        row = {
            "invoice_id": invoice_id,
            "amount_uah": payload.amount_uah,
            "name": (payload.name or "").strip() or None,
            "phone": (payload.phone or "").strip() or None,
            "status": remote,
        }
        _PENDING[f"invoice:{invoice_id}"] = row
    else:
        row["status"] = remote
        if payload.name:
            row["name"] = payload.name.strip()
        if payload.phone:
            row["phone"] = payload.phone.strip()
    if remote in SUCCESS_STATUSES:
        await _notify_rdn_paid(row)
    return PayStatusResponse(
        payment_id="",
        invoice_id=invoice_id,
        status=remote,
        amount_uah=int(row["amount_uah"]),
        name=row.get("name"),
        phone=row.get("phone"),
    )


@router.post("/webhook")
async def monobank_webhook(request: Request) -> dict[str, Any]:
    """Monobank invoice webhook — notify support as soon as payment succeeds."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": True}
    if not isinstance(body, dict):
        return {"ok": True}
    invoice_id = str(body.get("invoiceId") or "").strip()
    status = str(body.get("status") or "").upper()
    if not invoice_id:
        return {"ok": True}
    row = next((r for r in _PENDING.values() if r.get("invoice_id") == invoice_id), None)
    if row is None:
        return {"ok": True}
    if status:
        row["status"] = status
    if status in SUCCESS_STATUSES:
        await _notify_rdn_paid(row)
    return {"ok": True}


@router.post("/pay-test", response_model=PayStatusResponse)
async def create_test_pay(payload: PayTestRequest) -> PayStatusResponse:
    """Local/dev only: mark payment SUCCESS without Monobank."""
    if not is_test_payment_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if not is_valid_amount_uah(payload.amount_uah):
        raise HTTPException(
            status_code=400,
            detail=f"amount_uah must be between {MIN_AMOUNT_UAH} and {MAX_AMOUNT_UAH}",
        )
    payment_id = str(uuid.uuid4())
    invoice_id = f"local-test-{payment_id}"
    _PENDING[payment_id] = {
        "invoice_id": invoice_id,
        "amount_uah": payload.amount_uah,
        "name": (payload.name or "").strip() or None,
        "phone": (payload.phone or "").strip() or None,
        "status": "SUCCESS",
    }
    await _notify_rdn_paid(_PENDING[payment_id])
    return _status_response(payment_id, _PENDING[payment_id])


class CallbackRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., min_length=5, max_length=40)


class CallbackResponse(BaseModel):
    ok: bool = True
    notified: bool = False


@router.post("/callback", response_model=CallbackResponse)
async def create_callback(payload: CallbackRequest) -> CallbackResponse:
    """Notify support chat about a callback request. Does not open Telegram for the user."""
    name = payload.name.strip()
    phone = payload.phone.strip()
    if len(name) < 1 or len(phone) < 5:
        raise HTTPException(status_code=400, detail="name and phone are required")
    msg = format_rdn_consultation_callback_message(name=name, phone=phone)
    notified = await send_telegram_message(msg)
    if not notified:
        raise HTTPException(status_code=502, detail="Unable to notify support")
    logger.info("RDN consultation callback notified name=%s", name)
    return CallbackResponse(ok=True, notified=True)
