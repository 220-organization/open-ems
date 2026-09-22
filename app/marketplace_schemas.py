"""Pydantic schemas for marketplace locations API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class MarketplaceRequestType(str, Enum):
    PROPOSE = "PROPOSE"
    LOOKING = "LOOKING"


class MarketplaceStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"


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
