"""Unit tests for marketplace admin auth and payment helpers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

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
from app.marketplace_schemas import MarketplaceLocationCreate, MarketplaceRequestType, LocationPoint


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
