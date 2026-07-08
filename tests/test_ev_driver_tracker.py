"""Unit tests for EV driver GPS track processing."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.ev_driver_cities import haversine_km, nearest_city
from app.ev_driver_track_service import (
    StayDraft,
    TrackPoint,
    build_trips,
    cluster_stays,
    filter_gps_jamming,
    mark_charging_stays,
)


def _pt(
    driver_id: str,
    lat: float,
    lon: float,
    minutes: int,
    *,
    source: str = "gps",
    base: Optional[datetime] = None,
) -> TrackPoint:
    start = base or datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    return TrackPoint(
        driver_id=driver_id,
        recorded_at=start + timedelta(minutes=minutes),
        lat=lat,
        lon=lon,
        source=source,
    )


def test_filter_gps_jamming_drops_2000km_teleport():
    base = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    points = [
        TrackPoint("d1", base, 50.45, 30.52, "gps"),
        TrackPoint("d1", base + timedelta(minutes=5), 55.75, 37.62, "gps"),  # Moscow spoof
        TrackPoint("d1", base + timedelta(minutes=10), 50.46, 30.53, "gps"),
    ]
    accepted, dropped = filter_gps_jamming(points, max_jump_km=2000, max_speed_kmh=350)
    assert len(dropped) == 1
    assert dropped[0].lat == 55.75
    assert len(accepted) == 2
    assert accepted[-1].lat == 50.46


def test_filter_gps_jamming_drops_impossible_speed():
    base = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    points = [
        TrackPoint("d1", base, 50.45, 30.52, "gps"),
        TrackPoint("d1", base + timedelta(minutes=1), 49.84, 24.03, "gps"),  # Lviv in 1 min
    ]
    accepted, dropped = filter_gps_jamming(points, max_jump_km=2000, max_speed_kmh=350)
    assert len(accepted) == 1
    assert len(dropped) == 1


def test_cluster_stays_collapses_home_dots():
    driver = "driver-home"
    points = [
        _pt(driver, 50.450, 30.523, 0),
        _pt(driver, 50.451, 30.524, 2),
        _pt(driver, 50.450, 30.522, 5),
        _pt(driver, 50.451, 30.523, 12),
    ]
    stays = cluster_stays(points, min_minutes=10)
    assert len(stays) == 1
    assert stays[0].point_count == 4
    assert (stays[0].ended_at - stays[0].started_at) >= timedelta(minutes=10)


def test_mark_charging_stays_near_station():
    stay = StayDraft(
        driver_id="d1",
        lat=50.45,
        lon=30.52,
        started_at=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc),
        point_count=3,
        best_source="gps",
    )
    stays = [
        StayDraft("d1", 50.0, 30.0, stay.started_at - timedelta(hours=2), stay.started_at - timedelta(hours=1), 2, "gps"),
        stay,
        StayDraft("d1", 49.0, 31.0, stay.ended_at + timedelta(hours=1), stay.ended_at + timedelta(hours=2), 2, "gps"),
    ]
    mark_charging_stays(stays, [(50.4501, 30.5234)], station_radius_m=150)
    assert stays[1].is_charging_guess is True


def test_build_trips_kyiv_to_lviv():
    driver = "d-trip"
    base = datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)
    origin_stay = StayDraft(
        driver, 50.4501, 30.5234,
        base, base + timedelta(hours=1), 5, "gps",
    )
    dest_stay = StayDraft(
        driver, 49.8397, 24.0297,
        base + timedelta(hours=6), base + timedelta(hours=7), 5, "gps",
    )
    movement = [
        TrackPoint(driver, base + timedelta(hours=2), 50.5, 30.0, "gps"),
        TrackPoint(driver, base + timedelta(hours=3), 50.2, 29.0, "gps"),
        TrackPoint(driver, base + timedelta(hours=4), 50.0, 27.0, "gps"),
        TrackPoint(driver, base + timedelta(hours=5), 49.9, 25.5, "gps"),
    ]
    trips = build_trips(movement, [origin_stay, dest_stay], min_trip_km=20)
    assert len(trips) == 1
    assert trips[0].origin_city == "Kyiv"
    assert trips[0].dest_city == "Lviv"
    assert trips[0].distance_km >= 20
    assert len(trips[0].route_points) >= 2


def test_nearest_city_kyiv():
    assert nearest_city(50.45, 30.52) == "Kyiv"


def test_haversine_kyiv_lviv():
    d = haversine_km(50.4501, 30.5234, 49.8397, 24.0297)
    assert 450 < d < 550
