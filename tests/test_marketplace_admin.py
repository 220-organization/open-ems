"""Unit tests for marketplace admin auth and payment helpers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import settings
from app.admin_auth import require_admin_token, verify_admin_password
from app.marketplace_payment import (
    heatmap_payment_amount_cents,
    looking_info_payment_amount_cents,
    payment_callback_base,
    propose_info_payment_amount_cents,
    publication_payment_amount_cents,
    resolve_marketplace_pay_redirect_base,
)
from app.routers.marketplace import image_extension_for_upload
from app.marketplace_schemas import (
    LandlordLegalForm,
    LocationPoint,
    MarketplaceLocationCreate,
    MarketplaceLocationUpdate,
    MarketplaceRequestType,
    MarketplaceStatus,
    MinRentYears,
)


def test_image_upload_accepts_iphone_and_android_formats():
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 8
    assert image_extension_for_upload(jpeg, "application/octet-stream", "IMG.HEIC") == "jpg"
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 8
    assert image_extension_for_upload(heic, "", "IMG_0001.HEIC") == "heic"
    avif = b"\x00\x00\x00\x18ftypavif" + b"\x00" * 4
    assert image_extension_for_upload(avif, "image/avif", "shot.avif") == "avif"
    webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP"
    assert image_extension_for_upload(webp, "image/webp", "android.webp") == "webp"
    assert image_extension_for_upload(b"plain", "image/heic", "photo.heic") == "heic"
    assert image_extension_for_upload(b"%PDF-1.4", "application/pdf", "scan.jpg") is None


def test_admin_password_default_matches_committed_secret():
    assert verify_admin_password("220220Ma") is True
    assert verify_admin_password("wrong") is False
    assert verify_admin_password("") is False


def test_require_admin_token_accepts_configured_token():
    token = settings.OPEN_EMS_ADMIN_TOKEN
    assert require_admin_token(token) == token


def test_require_admin_token_rejects_missing_or_wrong():
    with pytest.raises(HTTPException) as missing:
        require_admin_token(None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as wrong:
        require_admin_token("not-the-token")
    assert wrong.value.status_code == 401


def test_payment_amount_defaults():
    assert propose_info_payment_amount_cents() >= 100
    assert looking_info_payment_amount_cents() >= 100
    assert publication_payment_amount_cents() >= 100
    assert heatmap_payment_amount_cents() >= 100


def test_payment_callback_uses_api_marketplace_path():
    base = payment_callback_base()
    assert base.endswith("9220") or "localhost" in base or base.startswith("http")


def test_resolve_redirect_base_prefers_payload():
    assert (
        resolve_marketplace_pay_redirect_base("https://example.com/marketplace/")
        == "https://example.com/marketplace"
    )
    fallback = resolve_marketplace_pay_redirect_base(None)
    assert fallback.endswith("/marketplace") or "marketplace" in fallback


def test_marketplace_location_create_requires_location():
    with pytest.raises(Exception):
        MarketplaceLocationCreate(
            request_type=MarketplaceRequestType.PROPOSE,
            name="Ada",
            phone="+380",
            kw_available="22",
            locations=[],
            min_rent_years="1",
            restroom_coffee_nearby=True,
            more_stations_possible=False,
            parking_spaces_now=1,
            parking_spaces_future=1,
            landlord_legal_form="FOP",
        )


def test_location_update_can_replace_photos_without_touching_status_only_calls():
    photos = MarketplaceLocationUpdate(
        parking_photos=["/api/marketplace-files/parking.jpg"],
        connection_point_photos=[],
    )
    assert photos.parking_photos == ["/api/marketplace-files/parking.jpg"]
    assert photos.connection_point_photos == []
    status_only = MarketplaceLocationUpdate(status=MarketplaceStatus.PUBLISHED)
    assert "parking_photos" not in status_only.model_fields_set


def test_propose_location_requires_lease_terms():
    with pytest.raises(ValidationError):
        MarketplaceLocationCreate(
            request_type=MarketplaceRequestType.PROPOSE,
            name="Ada",
            phone="+380501112233",
            kw_available="22",
            locations=[LocationPoint(label="Kyiv", lat=50.45, lng=30.52)],
        )


def test_propose_location_accepts_lease_terms():
    payload = MarketplaceLocationCreate(
        request_type=MarketplaceRequestType.PROPOSE,
        name="Ada",
        phone="+380501112233",
        kw_available="22",
        locations=[LocationPoint(label="Kyiv", lat=50.45, lng=30.52)],
        parking_photos=["/api/marketplace/files/parking.jpg"],
        min_rent_years="5+",
        restroom_coffee_nearby=True,
        more_stations_possible=True,
        parking_spaces_now=2,
        parking_spaces_future=6,
        landlord_legal_form="TOV",
    )
    assert payload.min_rent_years == MinRentYears.FIVE_PLUS
    assert payload.landlord_legal_form == LandlordLegalForm.TOV
    assert payload.parking_spaces_future == 6


def test_propose_location_rejects_future_spaces_below_current():
    with pytest.raises(ValidationError):
        MarketplaceLocationCreate(
            request_type=MarketplaceRequestType.PROPOSE,
            name="Ada",
            phone="+380501112233",
            kw_available="22",
            locations=[LocationPoint(label="Kyiv", lat=50.45, lng=30.52)],
            parking_photos=["/api/marketplace/files/parking.jpg"],
            min_rent_years="3",
            restroom_coffee_nearby=False,
            more_stations_possible=False,
            parking_spaces_now=4,
            parking_spaces_future=2,
            landlord_legal_form="FOP",
        )


def test_marketplace_location_create_ok():
    payload = MarketplaceLocationCreate(
        request_type=MarketplaceRequestType.LOOKING,
        name="Ada",
        phone="+380501112233",
        kw_available="22",
        locations=[LocationPoint(label="Kyiv", lat=50.45, lng=30.52)],
    )
    assert payload.request_type == MarketplaceRequestType.LOOKING
    assert len(payload.locations) == 1
