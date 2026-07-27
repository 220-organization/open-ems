"""Paid RDN consultation — Monobank checkout + status poll."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.rdn_consultation_payment import (
    ALLOWED_AMOUNTS_UAH,
    create_consultation_invoice,
    fetch_invoice_status,
    is_test_payment_enabled,
    with_query,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rdn-consultation", tags=["rdn-consultation"])

SUCCESS_STATUSES = frozenset({"SUCCESS"})
# In-memory map: our payment_id → invoice metadata (survives until process restart).
_PENDING: dict[str, dict] = {}


class PayCreateRequest(BaseModel):
    amount_uah: int = Field(..., description="One of 2200, 4400, 8800")
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
    amount_uah: int = Field(..., description="One of 2200, 4400, 8800")
    name: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)


@router.post("/pay", response_model=PayCreateResponse)
def create_pay(payload: PayCreateRequest) -> PayCreateResponse:
    if payload.amount_uah not in ALLOWED_AMOUNTS_UAH:
        raise HTTPException(
            status_code=400,
            detail=f"amount_uah must be one of {sorted(ALLOWED_AMOUNTS_UAH)}",
        )
    payment_id = str(uuid.uuid4())
    redirect_url = with_query(payload.redirect_url, rdnConsultPayment=payment_id)
    try:
        invoice = create_consultation_invoice(
            amount_uah=payload.amount_uah,
            redirect_url=redirect_url,
            reference=payment_id,
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
def get_payment_status(payment_id: str) -> PayStatusResponse:
    row = _PENDING.get(payment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    status = (row.get("status") or "created").upper()
    if status not in SUCCESS_STATUSES and status not in {"FAILURE", "EXPIRED", "REVERSED"}:
        remote = fetch_invoice_status(row["invoice_id"])
        if remote:
            status = remote
            row["status"] = status
    return PayStatusResponse(
        payment_id=payment_id,
        invoice_id=row["invoice_id"],
        status=status,
        amount_uah=int(row["amount_uah"]),
        name=row.get("name"),
        phone=row.get("phone"),
    )


class InvoiceStatusRequest(BaseModel):
    invoice_id: str = Field(..., min_length=4, max_length=120)
    amount_uah: int = Field(..., description="One of 2200, 4400, 8800")
    name: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)


@router.post("/invoice-status", response_model=PayStatusResponse)
def post_invoice_status(payload: InvoiceStatusRequest) -> PayStatusResponse:
    """Fallback when in-memory payment map was lost after redirect (multi-restart)."""
    if payload.amount_uah not in ALLOWED_AMOUNTS_UAH:
        raise HTTPException(
            status_code=400,
            detail=f"amount_uah must be one of {sorted(ALLOWED_AMOUNTS_UAH)}",
        )
    remote = fetch_invoice_status(payload.invoice_id.strip())
    if not remote:
        raise HTTPException(status_code=502, detail="Unable to fetch invoice status")
    return PayStatusResponse(
        payment_id="",
        invoice_id=payload.invoice_id.strip(),
        status=remote,
        amount_uah=payload.amount_uah,
        name=(payload.name or "").strip() or None,
        phone=(payload.phone or "").strip() or None,
    )


@router.post("/pay-test", response_model=PayStatusResponse)
def create_test_pay(payload: PayTestRequest) -> PayStatusResponse:
    """Local/dev only: mark payment SUCCESS without Monobank."""
    if not is_test_payment_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if payload.amount_uah not in ALLOWED_AMOUNTS_UAH:
        raise HTTPException(
            status_code=400,
            detail=f"amount_uah must be one of {sorted(ALLOWED_AMOUNTS_UAH)}",
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
    return PayStatusResponse(
        payment_id=payment_id,
        invoice_id=invoice_id,
        status="SUCCESS",
        amount_uah=payload.amount_uah,
        name=_PENDING[payment_id]["name"],
        phone=_PENDING[payment_id]["phone"],
    )
