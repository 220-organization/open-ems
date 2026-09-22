"""Marketplace locations API (public browse/submit + admin moderation + payments)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import marketplace_service as crud
from app import settings
from app.admin_auth import require_admin_token, verify_admin_password
from app.db import get_db
from app.marketplace_notifications import notify_marketplace_submission_pending
from app.marketplace_payment import (
    LOOKING_INFO_PAYMENT_DESCRIPTION,
    PAYMENT_DESCRIPTION,
    create_marketplace_heatmap_invoice,
    create_marketplace_info_invoice,
    create_marketplace_publication_invoice,
    fetch_invoice_status,
    heatmap_payment_amount_cents,
    is_marketplace_test_payment_enabled,
    looking_info_payment_amount_cents,
    propose_info_payment_amount_cents,
    publication_payment_amount_cents,
    resolve_marketplace_pay_redirect_base,
)
from app.marketplace_schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    MarketplaceInfoPaymentCreate,
    MarketplaceInfoPaymentCreateResponse,
    MarketplaceInfoPaymentStatusResponse,
    MarketplaceInfoPaymentTestCreate,
    MarketplaceLocationAdmin,
    MarketplaceLocationCreate,
    MarketplaceLocationCreateResponse,
    MarketplaceLocationListAdminResponse,
    MarketplaceLocationListPendingResponse,
    MarketplaceLocationListPublicResponse,
    MarketplaceLocationOwnerInfo,
    MarketplaceLocationPending,
    MarketplaceLocationPendingPoint,
    MarketplaceLocationPublic,
    MarketplaceLocationRequestInfoResponse,
    MarketplaceLocationUpdate,
    MarketplacePendingCountResponse,
    MarketplaceRequestType,
    MarketplaceUploadResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

ALLOWED_UPLOAD_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/pjpeg",
    "image/png",
    "image/webp",
}
FILES_MARKER = "/api/marketplace-files/"


def marketplace_data_dir() -> Path:
    path = Path(settings.MARKETPLACE_DATA_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _public_url(relative_path: str) -> str:
    base = settings.MARKETPLACE_PUBLIC_BASE_URL
    if base:
        return f"{base}{relative_path}"
    return relative_path


def _marketplace_relative_path(path_or_url: str) -> Optional[str]:
    if not path_or_url:
        return None
    raw = str(path_or_url).strip()
    path_part = raw
    if raw.startswith("http://") or raw.startswith("https://"):
        try:
            path_part = urlparse(raw).path or ""
        except Exception:
            return None
    for marker in (FILES_MARKER, "/marketplace-files/"):
        if marker in path_part:
            relative = path_part.split(marker, 1)[1]
            if relative and ".." not in relative and not relative.startswith("/"):
                return relative
    return None


def _normalize_photo_url(path_or_url: str) -> Optional[str]:
    relative = _marketplace_relative_path(path_or_url)
    if not relative:
        return None
    return f"{FILES_MARKER}{relative}"


def _normalize_photo_urls(urls) -> list:
    out = []
    for url in urls or []:
        normalized = _normalize_photo_url(url)
        if normalized:
            out.append(normalized)
    return out


def _marketplace_file_exists(path_or_url: str) -> bool:
    relative = _marketplace_relative_path(path_or_url)
    if not relative:
        return False
    return (marketplace_data_dir() / relative).is_file()


def _filter_existing_photo_urls(urls):
    existing = []
    for url in urls or []:
        normalized = _normalize_photo_url(url)
        if not normalized:
            continue
        if _marketplace_file_exists(normalized):
            existing.append(_public_url(normalized) if settings.MARKETPLACE_PUBLIC_BASE_URL else normalized)
    return existing


def _row_to_public(row) -> MarketplaceLocationPublic:
    return MarketplaceLocationPublic(
        id=row.id,
        request_type=row.request_type,
        kw_available=row.kw_available,
        distribution_contract=row.distribution_contract,
        locations=row.locations or [],
        parking_photos=_filter_existing_photo_urls(row.parking_photos),
        connection_point_photos=_filter_existing_photo_urls(row.connection_point_photos),
        distribution_contract_photos=_filter_existing_photo_urls(row.distribution_contract_photos),
        distance_meters=row.distance_meters,
        price_per_kwh_extra=float(row.price_per_kwh_extra) if row.price_per_kwh_extra is not None else None,
        monthly_price_parking=row.monthly_price_parking,
        view_count=int(row.view_count or 0),
        created_on=row.created_on,
        published_on=row.updated_on,
    )


def _row_to_admin(row) -> MarketplaceLocationAdmin:
    return MarketplaceLocationAdmin(
        id=row.id,
        request_type=row.request_type,
        name=row.name,
        phone=row.phone,
        kw_available=row.kw_available,
        distribution_contract=row.distribution_contract,
        messenger=row.messenger,
        locations=row.locations or [],
        parking_photos=row.parking_photos or [],
        connection_point_photos=row.connection_point_photos or [],
        distribution_contract_photos=row.distribution_contract_photos or [],
        distance_meters=row.distance_meters,
        price_per_kwh_extra=float(row.price_per_kwh_extra) if row.price_per_kwh_extra is not None else None,
        monthly_price_parking=row.monthly_price_parking,
        view_count=int(row.view_count or 0),
        status=row.status,
        created_on=row.created_on,
        updated_on=row.updated_on,
    )


def _row_to_pending(row) -> MarketplaceLocationPending:
    points = [
        MarketplaceLocationPendingPoint(lat=loc["lat"], lng=loc["lng"])
        for loc in (row.locations or [])
        if loc.get("lat") is not None and loc.get("lng") is not None
    ]
    return MarketplaceLocationPending(
        id=row.id,
        kw_available=row.kw_available,
        locations=points,
    )


def _row_to_owner_info(row) -> MarketplaceLocationOwnerInfo:
    return MarketplaceLocationOwnerInfo(
        name=row.name,
        phone=row.phone,
        distribution_contract_photos=_filter_existing_photo_urls(row.distribution_contract_photos),
        view_count=int(row.view_count or 0),
    )


SUCCESS_STATUSES = {"SUCCESS"}
TERMINAL_FAILURE_STATUSES = {"FAILURE", "EXPIRED", "REVERSED"}
INFO_UNLOCK_PAYMENT_KINDS = frozenset({"location_info", "looking_info"})


async def _sync_payment_status_from_monobank(db: AsyncSession, payment_row):
    if payment_row.status in SUCCESS_STATUSES or payment_row.status in TERMINAL_FAILURE_STATUSES:
        return payment_row
    remote_status = fetch_invoice_status(payment_row.invoice_id)
    if not remote_status or remote_status == payment_row.status:
        return payment_row
    return await crud.update_marketplace_info_payment_status(db, payment_row.id, remote_status)


async def _build_payment_status_response(db: AsyncSession, payment_row):
    payment_row = await _sync_payment_status_from_monobank(db, payment_row)
    owner_info = None
    payment_kind = getattr(payment_row, "payment_kind", None) or "location_info"
    if (
        payment_row.status in SUCCESS_STATUSES
        and payment_kind in INFO_UNLOCK_PAYMENT_KINDS
        and payment_row.location_id
    ):
        location = await crud.get_marketplace_location(db, payment_row.location_id)
        if location is not None:
            owner_info = _row_to_owner_info(location)
    return MarketplaceInfoPaymentStatusResponse(
        payment_id=payment_row.id,
        location_id=payment_row.location_id,
        payment_kind=payment_kind,
        status=payment_row.status,
        amount_cents=payment_row.amount_cents,
        owner_info=owner_info,
    )


@admin_router.post("/login", response_model=AdminLoginResponse)
async def admin_login(payload: AdminLoginRequest):
    if not verify_admin_password(payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    return AdminLoginResponse(token=settings.OPEN_EMS_ADMIN_TOKEN)


@router.post("/uploads", response_model=MarketplaceUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_marketplace_file(file: UploadFile = File(...)):
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    data = await file.read()
    if len(data) > settings.MARKETPLACE_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    ext_map = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/pjpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    ext = ext_map.get(content_type, "jpg")
    filename = f"{uuid.uuid4()}.{ext}"
    target = marketplace_data_dir() / filename
    target.write_bytes(data)
    if not target.is_file() or target.stat().st_size != len(data):
        logger.error("Marketplace upload failed to persist at %s", target)
        raise HTTPException(status_code=500, detail="Failed to persist uploaded file")
    logger.info("Marketplace upload saved %s (%s bytes)", filename, len(data))

    relative = f"{FILES_MARKER}{filename}"
    return MarketplaceUploadResponse(url=_public_url(relative))


@router.post("/locations", response_model=MarketplaceLocationCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_marketplace_location_public(
    payload: MarketplaceLocationCreate,
    db: AsyncSession = Depends(get_db),
):
    payload = payload.model_copy(
        update={
            "parking_photos": _normalize_photo_urls(payload.parking_photos),
            "connection_point_photos": _normalize_photo_urls(payload.connection_point_photos),
            "distribution_contract_photos": _normalize_photo_urls(payload.distribution_contract_photos),
        }
    )
    row = await crud.create_marketplace_location(db, payload)
    try:
        await notify_marketplace_submission_pending(row)
    except Exception:
        pass
    return MarketplaceLocationCreateResponse(id=row.id)


@router.get("/locations", response_model=MarketplaceLocationListPublicResponse)
async def list_marketplace_locations_public(
    request_type: Optional[MarketplaceRequestType] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    rows = await crud.list_public_marketplace_locations(db, request_type=request_type)
    return MarketplaceLocationListPublicResponse(items=[_row_to_public(row) for row in rows])


@router.get("/locations/pending", response_model=MarketplaceLocationListPendingResponse)
async def list_pending_marketplace_locations_public(db: AsyncSession = Depends(get_db)):
    rows = await crud.list_pending_marketplace_locations(db)
    return MarketplaceLocationListPendingResponse(items=[_row_to_pending(row) for row in rows])


@router.post("/locations/{row_id}/pay", response_model=MarketplaceInfoPaymentCreateResponse)
async def pay_for_marketplace_location_info(
    row_id: uuid.UUID,
    payload: MarketplaceInfoPaymentCreate,
    db: AsyncSession = Depends(get_db),
):
    row = await crud.get_marketplace_location(db, row_id)
    if row is None or row.status != "PUBLISHED":
        raise HTTPException(status_code=404, detail="Marketplace location not found")

    if row.request_type == "LOOKING":
        amount_cents = looking_info_payment_amount_cents()
        payment_kind = "looking_info"
        description = LOOKING_INFO_PAYMENT_DESCRIPTION
    else:
        amount_cents = propose_info_payment_amount_cents()
        payment_kind = "location_info"
        description = PAYMENT_DESCRIPTION

    payment_id = uuid.uuid4()
    redirect_base = resolve_marketplace_pay_redirect_base(payload.redirect_base_url)
    query = urlencode(
        {
            "marketplacePayment": str(payment_id),
            "marketplaceLocation": str(row_id),
        }
    )
    redirect_url = f"{redirect_base}?{query}"

    try:
        invoice = create_marketplace_info_invoice(
            payment_id=payment_id,
            location_id=row_id,
            redirect_url=redirect_url,
            amount_cents=amount_cents,
            description=description,
        )
    except RuntimeError as exc:
        logger.exception("Failed to create marketplace payment invoice")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    invoice_id = invoice.get("invoiceId")
    page_url = invoice.get("pageUrl")
    if not invoice_id or not page_url:
        raise HTTPException(status_code=502, detail="Invalid Monobank invoice response")

    await crud.create_marketplace_info_payment(
        db,
        payment_id=payment_id,
        location_id=row_id,
        invoice_id=invoice_id,
        amount_cents=amount_cents,
        client_ui_id=(payload.client_ui_id or "").strip() or None,
        payment_kind=payment_kind,
    )
    await crud.increment_marketplace_view_count(db, row_id)

    return MarketplaceInfoPaymentCreateResponse(
        payment_id=payment_id,
        page_url=page_url,
        amount_cents=amount_cents,
    )


@router.post("/locations/{row_id}/pay-test", response_model=MarketplaceInfoPaymentStatusResponse)
async def test_pay_for_marketplace_location_info(
    row_id: uuid.UUID,
    payload: MarketplaceInfoPaymentTestCreate,
    db: AsyncSession = Depends(get_db),
):
    if not is_marketplace_test_payment_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    row = await crud.get_marketplace_location(db, row_id)
    if row is None or row.status != "PUBLISHED":
        raise HTTPException(status_code=404, detail="Marketplace location not found")

    if row.request_type == "LOOKING":
        amount_cents = looking_info_payment_amount_cents()
        payment_kind = "looking_info"
    else:
        amount_cents = propose_info_payment_amount_cents()
        payment_kind = "location_info"

    payment_id = uuid.uuid4()
    await crud.create_marketplace_info_payment(
        db,
        payment_id=payment_id,
        location_id=row_id,
        invoice_id=f"local-test-{payment_id}",
        amount_cents=amount_cents,
        client_ui_id=(payload.client_ui_id or "").strip() or None,
        payment_kind=payment_kind,
    )
    await crud.update_marketplace_info_payment_status(db, payment_id, "SUCCESS")
    await crud.increment_marketplace_view_count(db, row_id)

    payment_row = await crud.get_marketplace_info_payment(db, payment_id)
    if payment_row is None:
        raise HTTPException(status_code=500, detail="Failed to create test payment")
    return await _build_payment_status_response(db, payment_row)


@router.post("/publication/pay", response_model=MarketplaceInfoPaymentCreateResponse)
async def pay_for_marketplace_publication(
    payload: MarketplaceInfoPaymentCreate,
    db: AsyncSession = Depends(get_db),
):
    amount_cents = publication_payment_amount_cents()
    payment_id = uuid.uuid4()
    redirect_base = resolve_marketplace_pay_redirect_base(payload.redirect_base_url)
    redirect_url = f"{redirect_base}?{urlencode({'marketplacePublicationPayment': str(payment_id)})}"

    try:
        invoice = create_marketplace_publication_invoice(
            payment_id=payment_id,
            redirect_url=redirect_url,
        )
    except RuntimeError as exc:
        logger.exception("Failed to create marketplace publication payment invoice")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    invoice_id = invoice.get("invoiceId")
    page_url = invoice.get("pageUrl")
    if not invoice_id or not page_url:
        raise HTTPException(status_code=502, detail="Invalid Monobank invoice response")

    await crud.create_marketplace_info_payment(
        db,
        payment_id=payment_id,
        location_id=None,
        invoice_id=invoice_id,
        amount_cents=amount_cents,
        client_ui_id=(payload.client_ui_id or "").strip() or None,
        payment_kind="publication",
    )
    return MarketplaceInfoPaymentCreateResponse(
        payment_id=payment_id,
        page_url=page_url,
        amount_cents=amount_cents,
    )


@router.post("/publication/pay-test", response_model=MarketplaceInfoPaymentStatusResponse)
async def test_pay_for_marketplace_publication(
    payload: MarketplaceInfoPaymentTestCreate,
    db: AsyncSession = Depends(get_db),
):
    if not is_marketplace_test_payment_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    amount_cents = publication_payment_amount_cents()
    payment_id = uuid.uuid4()
    await crud.create_marketplace_info_payment(
        db,
        payment_id=payment_id,
        location_id=None,
        invoice_id=f"local-test-publication-{payment_id}",
        amount_cents=amount_cents,
        client_ui_id=(payload.client_ui_id or "").strip() or None,
        payment_kind="publication",
    )
    await crud.update_marketplace_info_payment_status(db, payment_id, "SUCCESS")
    payment_row = await crud.get_marketplace_info_payment(db, payment_id)
    if payment_row is None:
        raise HTTPException(status_code=500, detail="Failed to create test payment")
    return await _build_payment_status_response(db, payment_row)


@router.post("/heatmap/pay", response_model=MarketplaceInfoPaymentCreateResponse)
async def pay_for_marketplace_heatmap_zoom(
    payload: MarketplaceInfoPaymentCreate,
    db: AsyncSession = Depends(get_db),
):
    amount_cents = heatmap_payment_amount_cents()
    payment_id = uuid.uuid4()
    redirect_base = resolve_marketplace_pay_redirect_base(payload.redirect_base_url)
    redirect_url = f"{redirect_base}?{urlencode({'marketplaceHeatmapPayment': str(payment_id)})}"

    try:
        invoice = create_marketplace_heatmap_invoice(
            payment_id=payment_id,
            redirect_url=redirect_url,
        )
    except RuntimeError as exc:
        logger.exception("Failed to create marketplace heatmap payment invoice")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    invoice_id = invoice.get("invoiceId")
    page_url = invoice.get("pageUrl")
    if not invoice_id or not page_url:
        raise HTTPException(status_code=502, detail="Invalid Monobank invoice response")

    await crud.create_marketplace_info_payment(
        db,
        payment_id=payment_id,
        location_id=None,
        invoice_id=invoice_id,
        amount_cents=amount_cents,
        client_ui_id=(payload.client_ui_id or "").strip() or None,
        payment_kind="heatmap_zoom",
    )
    return MarketplaceInfoPaymentCreateResponse(
        payment_id=payment_id,
        page_url=page_url,
        amount_cents=amount_cents,
    )


@router.post("/heatmap/pay-test", response_model=MarketplaceInfoPaymentStatusResponse)
async def test_pay_for_marketplace_heatmap_zoom(
    payload: MarketplaceInfoPaymentTestCreate,
    db: AsyncSession = Depends(get_db),
):
    if not is_marketplace_test_payment_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    payment_id = uuid.uuid4()
    await crud.create_marketplace_info_payment(
        db,
        payment_id=payment_id,
        location_id=None,
        invoice_id=f"local-test-heatmap-{payment_id}",
        amount_cents=0,
        client_ui_id=(payload.client_ui_id or "").strip() or None,
        payment_kind="heatmap_zoom",
    )
    await crud.update_marketplace_info_payment_status(db, payment_id, "SUCCESS")
    payment_row = await crud.get_marketplace_info_payment(db, payment_id)
    if payment_row is None:
        raise HTTPException(status_code=500, detail="Failed to create test payment")
    return await _build_payment_status_response(db, payment_row)


@router.get("/payments/{payment_id}", response_model=MarketplaceInfoPaymentStatusResponse)
async def get_marketplace_payment_status(
    payment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    payment_row = await crud.get_marketplace_info_payment(db, payment_id)
    if payment_row is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return await _build_payment_status_response(db, payment_row)


class MonoCallbackBody(BaseModel):
    invoiceId: Optional[str] = None
    status: Optional[str] = None
    reference: Optional[str] = None


@router.post("/payments/mono-callback")
async def marketplace_payment_mono_callback(
    payload: MonoCallbackBody,
    db: AsyncSession = Depends(get_db),
):
    payment_row = None
    if payload.reference:
        try:
            payment_id = uuid.UUID(payload.reference)
            payment_row = await crud.get_marketplace_info_payment(db, payment_id)
        except ValueError:
            payment_row = None
    if payment_row is None and payload.invoiceId:
        payment_row = await crud.get_marketplace_info_payment_by_invoice(db, payload.invoiceId)
    if payment_row is None:
        logger.warning("Marketplace payment callback for unknown invoice: %s", payload.invoiceId)
        return {"ok": True}

    status_value = (payload.status or fetch_invoice_status(payment_row.invoice_id) or "").upper()
    if status_value:
        await crud.update_marketplace_info_payment_status(db, payment_row.id, status_value)
    return {"ok": True}


@router.post("/locations/{row_id}/request-info", response_model=MarketplaceLocationRequestInfoResponse)
async def request_marketplace_location_info(
    row_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    row = await crud.increment_marketplace_view_count(db, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Marketplace location not found")
    public_item = _row_to_public(row)
    return MarketplaceLocationRequestInfoResponse(view_count=public_item.view_count, item=public_item)


@router.get("/locations/admin/pending-count", response_model=MarketplacePendingCountResponse)
async def count_pending_marketplace_locations_admin(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
):
    pending_count = await crud.count_pending_marketplace_locations(db)
    return MarketplacePendingCountResponse(pending_count=pending_count)


@router.get("/locations/admin", response_model=MarketplaceLocationListAdminResponse)
async def list_marketplace_locations_admin(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
):
    rows = await crud.list_admin_marketplace_locations(db)
    return MarketplaceLocationListAdminResponse(items=[_row_to_admin(row) for row in rows])


@router.put("/locations/{row_id}", response_model=MarketplaceLocationAdmin)
async def update_marketplace_location_admin(
    row_id: uuid.UUID,
    payload: MarketplaceLocationUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
):
    row = await crud.update_marketplace_location(db, row_id, payload)
    if row is None:
        raise HTTPException(status_code=404, detail="Marketplace location not found")
    return _row_to_admin(row)


@router.delete("/locations/{row_id}", response_model=MarketplaceLocationAdmin)
async def delete_marketplace_location_admin(
    row_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
):
    row = await crud.delete_marketplace_location(db, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Marketplace location not found")
    return _row_to_admin(row)
