"""Pydantic schemas for marketplace locations API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class MarketplaceRequestType(str, Enum):
    PROPOSE = "PROPOSE"
    LOOKING = "LOOKING"


class MarketplaceStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"


class MinRentYears(str, Enum):
    ONE = "1"
    TWO = "2"
    THREE = "3"
    FIVE = "5"
    FIVE_PLUS = "5+"


class LandlordLegalForm(str, Enum):
    FOP = "FOP"
    TOV = "TOV"


def _reject_parking_future_below_now(now: Optional[int], future: Optional[int]) -> None:
    if now is not None and future is not None and future < now:
        raise ValueError("parking_spaces_future must be at least parking_spaces_now")


class LocationPoint(BaseModel):
    label: str
    lat: float
    lng: float
    radius_km: Optional[float] = None
    bbox: Optional[List[float]] = None


class MarketplaceLocationCreate(BaseModel):
    request_type: MarketplaceRequestType
    name: str
    phone: str
    kw_available: str
    distribution_contract: Optional[bool] = None
    messenger: Optional[str] = None
    locations: List[LocationPoint] = Field(default_factory=list)
    parking_photos: List[str] = Field(default_factory=list)
    connection_point_photos: List[str] = Field(default_factory=list)
    distribution_contract_photos: List[str] = Field(default_factory=list)
    distance_meters: Optional[int] = None
    price_per_kwh_extra: Optional[float] = None
    monthly_price_parking: Optional[int] = None
    min_rent_years: Optional[MinRentYears] = None
    restroom_coffee_nearby: Optional[bool] = None
    more_stations_possible: Optional[bool] = None
    parking_spaces_now: Optional[int] = Field(default=None, ge=1)
    parking_spaces_future: Optional[int] = Field(default=None, ge=1)
    landlord_legal_form: Optional[LandlordLegalForm] = None

    @field_validator("name", "phone", "kw_available")
    @classmethod
    def strip_required(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("Field is required")
        return normalized

    @field_validator("locations")
    @classmethod
    def validate_locations(cls, value: List[LocationPoint]) -> List[LocationPoint]:
        if not value:
            raise ValueError("At least one location is required")
        return value

    @model_validator(mode="after")
    def require_propose_lease_terms(self):
        if self.request_type != MarketplaceRequestType.PROPOSE:
            return self
        required = {
            "min_rent_years": self.min_rent_years,
            "restroom_coffee_nearby": self.restroom_coffee_nearby,
            "more_stations_possible": self.more_stations_possible,
            "parking_spaces_now": self.parking_spaces_now,
            "parking_spaces_future": self.parking_spaces_future,
            "landlord_legal_form": self.landlord_legal_form,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"Required for a location offer: {', '.join(missing)}")
        photos = [item.strip() for item in (self.parking_photos or []) if (item or "").strip()]
        if not photos:
            raise ValueError("parking_photos is required")
        _reject_parking_future_below_now(self.parking_spaces_now, self.parking_spaces_future)
        return self


class MarketplaceLocationPublic(BaseModel):
    id: UUID
    request_type: MarketplaceRequestType
    kw_available: str
    distribution_contract: Optional[bool] = None
    locations: List[LocationPoint]
    parking_photos: List[str] = Field(default_factory=list)
    connection_point_photos: List[str] = Field(default_factory=list)
    distribution_contract_photos: List[str] = Field(default_factory=list)
    distance_meters: Optional[int] = None
    price_per_kwh_extra: Optional[float] = None
    monthly_price_parking: Optional[int] = None
    min_rent_years: Optional[MinRentYears] = None
    restroom_coffee_nearby: Optional[bool] = None
    more_stations_possible: Optional[bool] = None
    parking_spaces_now: Optional[int] = None
    parking_spaces_future: Optional[int] = None
    landlord_legal_form: Optional[LandlordLegalForm] = None
    view_count: int = 0
    created_on: datetime
    published_on: datetime

    model_config = {"from_attributes": True}


class MarketplaceLocationPendingPoint(BaseModel):
    lat: float
    lng: float


class MarketplaceLocationPending(BaseModel):
    """Teaser for a submission awaiting moderation: map point and kW only."""

    id: UUID
    kw_available: str
    status: MarketplaceStatus = MarketplaceStatus.PENDING
    locations: List[MarketplaceLocationPendingPoint] = Field(default_factory=list)


class MarketplaceLocationAdmin(BaseModel):
    id: UUID
    request_type: MarketplaceRequestType
    name: str
    phone: str
    kw_available: str
    distribution_contract: Optional[bool] = None
    messenger: Optional[str] = None
    locations: List[LocationPoint]
    parking_photos: List[str] = Field(default_factory=list)
    connection_point_photos: List[str] = Field(default_factory=list)
    distribution_contract_photos: List[str] = Field(default_factory=list)
    distance_meters: Optional[int] = None
    price_per_kwh_extra: Optional[float] = None
    monthly_price_parking: Optional[int] = None
    min_rent_years: Optional[MinRentYears] = None
    restroom_coffee_nearby: Optional[bool] = None
    more_stations_possible: Optional[bool] = None
    parking_spaces_now: Optional[int] = None
    parking_spaces_future: Optional[int] = None
    landlord_legal_form: Optional[LandlordLegalForm] = None
    view_count: int = 0
    status: MarketplaceStatus
    created_on: datetime
    updated_on: datetime

    model_config = {"from_attributes": True}


class MarketplaceLocationUpdate(BaseModel):
    status: Optional[MarketplaceStatus] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    kw_available: Optional[str] = None
    distribution_contract: Optional[bool] = None
    distance_meters: Optional[int] = None
    price_per_kwh_extra: Optional[float] = None
    monthly_price_parking: Optional[int] = None
    min_rent_years: Optional[MinRentYears] = None
    restroom_coffee_nearby: Optional[bool] = None
    more_stations_possible: Optional[bool] = None
    parking_spaces_now: Optional[int] = Field(default=None, ge=1)
    parking_spaces_future: Optional[int] = Field(default=None, ge=1)
    landlord_legal_form: Optional[LandlordLegalForm] = None
    parking_photos: Optional[List[str]] = None
    connection_point_photos: Optional[List[str]] = None
    distribution_contract_photos: Optional[List[str]] = None

    @model_validator(mode="after")
    def parking_future_covers_current(self):
        _reject_parking_future_below_now(self.parking_spaces_now, self.parking_spaces_future)
        return self

    @field_validator("name", "phone", "kw_available")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Field cannot be empty")
        return normalized


class MarketplaceLocationListPublicResponse(BaseModel):
    items: List[MarketplaceLocationPublic]


class MarketplaceLocationListPendingResponse(BaseModel):
    items: List[MarketplaceLocationPending]


class MarketplaceLocationListAdminResponse(BaseModel):
    items: List[MarketplaceLocationAdmin]


class MarketplacePendingCountResponse(BaseModel):
    pending_count: int


class MarketplaceLocationCreateResponse(BaseModel):
    id: UUID


class MarketplaceUploadResponse(BaseModel):
    url: str


class MarketplaceLocationRequestInfoResponse(BaseModel):
    view_count: int
    item: MarketplaceLocationPublic


class MarketplaceInfoPaymentCreate(BaseModel):
    redirect_base_url: Optional[str] = Field(
        None,
        description="Post-payment redirect base URL, e.g. https://220-km.com:9220/marketplace",
    )
    client_ui_id: Optional[str] = None


class MarketplaceInfoPaymentTestCreate(BaseModel):
    client_ui_id: Optional[str] = None


class MarketplaceInfoPaymentCreateResponse(BaseModel):
    payment_id: UUID
    page_url: str
    amount_cents: int


class MarketplaceLocationOwnerInfo(BaseModel):
    name: str
    phone: str
    distribution_contract_photos: List[str] = Field(default_factory=list)
    view_count: int = 0


class MarketplaceInfoPaymentStatusResponse(BaseModel):
    payment_id: UUID
    location_id: Optional[UUID] = None
    payment_kind: str = "location_info"
    status: str
    amount_cents: int
    owner_info: Optional[MarketplaceLocationOwnerInfo] = None


class AdminLoginRequest(BaseModel):
    password: str


class AdminLoginResponse(BaseModel):
    token: str
