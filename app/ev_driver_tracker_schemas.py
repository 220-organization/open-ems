"""Pydantic schemas for EV driver GPS tracker API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class EvDriverTrackPointIn(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    ts: int = Field(..., description="Unix timestamp in milliseconds")
    source: Literal["gps", "cookie", "ip"] = "gps"
    accuracyM: Optional[float] = Field(default=None, alias="accuracyM")

    model_config = {"populate_by_name": True}

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not -90 <= v <= 90:
            raise ValueError("lat out of range")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not -180 <= v <= 180:
            raise ValueError("lng out of range")
        return v


class EvDriverPointsIn(BaseModel):
    driverId: str = Field(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    points: list[EvDriverTrackPointIn] = Field(..., min_length=1, max_length=200)


class EvDriverPointsOut(BaseModel):
    ok: bool = True
    accepted: int = 0
    dropped: int = 0


class HeatmapPointOut(BaseModel):
    lat: float
    lng: float
    count: int


class HeatmapPointsOut(BaseModel):
    ok: bool = True
    points: list[HeatmapPointOut]


class PopularRouteOut(BaseModel):
    originCity: str
    destCity: str
    tripCount: int
    uniqueDrivers: int
    avgDistanceKm: float
    avgChargeStops: float


class PopularRoutesOut(BaseModel):
    ok: bool = True
    days: int
    routes: list[PopularRouteOut]


class ChargingDemandCellOut(BaseModel):
    lat: float
    lng: float
    chargingStays: int
    uniqueDriverDays: int
    avgStayMinutes: float


class ChargingDemandOut(BaseModel):
    ok: bool = True
    days: int
    cells: list[ChargingDemandCellOut]


class SummarySeriesPoint(BaseModel):
    day: str
    drivers: int
    trips: int
    km: float


class OpenDataSummaryOut(BaseModel):
    ok: bool = True
    days: int
    activeDrivers: int
    pingsIngested: int
    stays: int
    trips: int
    totalKm: float
    chargingStops: int
    sourceBreakdown: dict[str, int]
    series: list[SummarySeriesPoint]
