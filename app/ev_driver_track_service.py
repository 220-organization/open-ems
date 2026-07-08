"""EV driver GPS track processing: jamming filter, stay compaction, trip building, open-data aggregates."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence

import httpx
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.ev_driver_cities import haversine_km, nearest_city
from app.models import EvDriverGpsRaw, EvDriverStay, EvDriverTrip
from app.oree_dam_service import KYIV

logger = logging.getLogger(__name__)

SOURCE_RANK = {"gps": 3, "cookie": 2, "ip": 1}

# Cached charging station coords (lat, lon) from B2B roaming API.
_station_coords_cache: tuple[float, list[tuple[float, float]]] = (0.0, [])


@dataclass(frozen=True)
class TrackPoint:
    driver_id: str
    recorded_at: datetime
    lat: float
    lon: float
    source: str
    accuracy_m: Optional[float] = None


@dataclass
class StayDraft:
    driver_id: str
    lat: float
    lon: float
    started_at: datetime
    ended_at: datetime
    point_count: int
    best_source: str
    is_charging_guess: bool = False


@dataclass
class TripDraft:
    driver_id: str
    kyiv_day: date
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    origin_city: Optional[str]
    dest_city: Optional[str]
    distance_km: float
    route_points: list[list[float]]
    charge_stop_count: int
    started_at: datetime
    ended_at: datetime


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def kyiv_day_of(dt: datetime) -> date:
    return _ensure_utc(dt).astimezone(KYIV).date()


def _source_better(a: str, b: str) -> str:
    return a if SOURCE_RANK.get(a, 0) >= SOURCE_RANK.get(b, 0) else b


def filter_gps_jamming(
    points: Sequence[TrackPoint],
    *,
    max_jump_km: float | None = None,
    max_speed_kmh: float | None = None,
) -> tuple[list[TrackPoint], list[TrackPoint]]:
    """
  Walk points in time order per Kyiv day; drop jumps > max_jump_km or impossible speed.
  Returns (accepted, dropped).
    """
    max_jump = max_jump_km if max_jump_km is not None else settings.EV_TRACKER_MAX_DAY_JUMP_KM
    max_speed = max_speed_kmh if max_speed_kmh is not None else settings.EV_TRACKER_MAX_SPEED_KMH

    sorted_pts = sorted(points, key=lambda p: p.recorded_at)
    accepted: list[TrackPoint] = []
    dropped: list[TrackPoint] = []
    anchor_by_day: dict[date, TrackPoint] = {}

    for pt in sorted_pts:
        day = kyiv_day_of(pt.recorded_at)
        anchor = anchor_by_day.get(day)
        if anchor is None:
            accepted.append(pt)
            anchor_by_day[day] = pt
            continue

        dist_km = haversine_km(anchor.lat, anchor.lon, pt.lat, pt.lon)
        dt_h = max(1e-9, (_ensure_utc(pt.recorded_at) - _ensure_utc(anchor.recorded_at)).total_seconds() / 3600.0)
        speed = dist_km / dt_h

        if dist_km > max_jump or speed > max_speed:
            dropped.append(pt)
            continue

        accepted.append(pt)
        anchor_by_day[day] = pt

    return accepted, dropped


def _cluster_radius_km() -> float:
    return settings.EV_TRACKER_STAY_RADIUS_M / 1000.0


def cluster_stays(
    points: Sequence[TrackPoint],
    *,
    min_minutes: int | None = None,
) -> list[StayDraft]:
    """Greedy stay clusters within radius; min duration filter."""
    min_dur = timedelta(minutes=min_minutes if min_minutes is not None else settings.EV_TRACKER_STAY_MIN_MINUTES)
    radius_km = _cluster_radius_km()
    sorted_pts = sorted(points, key=lambda p: p.recorded_at)

    stays: list[StayDraft] = []
    cluster: list[TrackPoint] = []

    def flush_cluster() -> None:
        nonlocal cluster
        if not cluster:
            return
        started = cluster[0].recorded_at
        ended = cluster[-1].recorded_at
        if ended - started < min_dur:
            cluster = []
            return
        lat = sum(p.lat for p in cluster) / len(cluster)
        lon = sum(p.lon for p in cluster) / len(cluster)
        best = cluster[0].source
        for p in cluster[1:]:
            best = _source_better(best, p.source)
        stays.append(
            StayDraft(
                driver_id=cluster[0].driver_id,
                lat=lat,
                lon=lon,
                started_at=started,
                ended_at=ended,
                point_count=len(cluster),
                best_source=best,
            )
        )
        cluster = []

    for pt in sorted_pts:
        if not cluster:
            cluster = [pt]
            continue
        clat = sum(p.lat for p in cluster) / len(cluster)
        clon = sum(p.lon for p in cluster) / len(cluster)
        if haversine_km(clat, clon, pt.lat, pt.lon) <= radius_km:
            cluster.append(pt)
        else:
            flush_cluster()
            cluster = [pt]
    flush_cluster()
    return stays


def _stay_duration_minutes(stay: StayDraft) -> float:
    return (_ensure_utc(stay.ended_at) - _ensure_utc(stay.started_at)).total_seconds() / 60.0


def mark_charging_stays(
    stays: list[StayDraft],
    station_coords: Sequence[tuple[float, float]],
    *,
    station_radius_m: float | None = None,
) -> None:
    """In-place: flag stays that look like charging stops."""
    radius_km = (station_radius_m if station_radius_m is not None else settings.EV_TRACKER_CHARGE_STATION_RADIUS_M) / 1000.0
    n = len(stays)
    for i, stay in enumerate(stays):
        dur_min = _stay_duration_minutes(stay)
        near_station = any(haversine_km(stay.lat, stay.lon, slat, slon) <= radius_km for slat, slon in station_coords)
        mid_route = (
            i > 0
            and i < n - 1
            and 15 <= dur_min <= 180
            and (_ensure_utc(stay.started_at) - _ensure_utc(stays[i - 1].ended_at)).total_seconds() > 60
            and (_ensure_utc(stays[i + 1].started_at) - _ensure_utc(stay.ended_at)).total_seconds() > 60
        )
        if near_station or mid_route:
            stay.is_charging_guess = True


def _douglas_peucker(points: list[tuple[float, float]], epsilon_km: float) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points

    def perp_dist(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        if a == b:
            return haversine_km(p[0], p[1], a[0], a[1])
        # Approximate perpendicular distance using cross-track on sphere (small segments).
        d_ax = haversine_km(a[0], a[1], p[0], p[1])
        d_ab = haversine_km(a[0], a[1], b[0], b[1])
        if d_ab < 1e-9:
            return d_ax
        d_bx = haversine_km(b[0], b[1], p[0], p[1])
        s = (d_ax + d_bx + d_ab) / 2
        area = max(0.0, s * (s - d_ax) * (s - d_bx) * (s - d_ab))
        height = 2 * math.sqrt(area) / d_ab if d_ab > 0 else d_ax
        return height

    def simplify(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(pts) < 3:
            return pts
        a, b = pts[0], pts[-1]
        max_d = 0.0
        idx = 0
        for i in range(1, len(pts) - 1):
            d = perp_dist(pts[i], a, b)
            if d > max_d:
                max_d = d
                idx = i
        if max_d <= epsilon_km:
            return [a, b]
        left = simplify(pts[: idx + 1])
        right = simplify(pts[idx:])
        return left[:-1] + right

    return simplify(points)


def build_trips(
    points: Sequence[TrackPoint],
    stays: Sequence[StayDraft],
    *,
    min_trip_km: float | None = None,
) -> list[TripDraft]:
    """Movement between consecutive stays forms a trip when distance >= min_trip_km."""
    min_km = min_trip_km if min_trip_km is not None else settings.EV_TRACKER_MIN_TRIP_KM
    if len(stays) < 2:
        return []

    trips: list[TripDraft] = []
    gps_points = [p for p in points if p.source == "gps"]

    for i in range(len(stays) - 1):
        origin = stays[i]
        dest = stays[i + 1]
        window_start = origin.ended_at
        window_end = dest.started_at
        if window_end <= window_start:
            continue

        segment = [
            p
            for p in gps_points
            if window_start <= p.recorded_at <= window_end
        ]
        if len(segment) < 2:
            segment_pts = [(origin.lat, origin.lon), (dest.lat, dest.lon)]
        else:
            segment_pts = [(p.lat, p.lon) for p in segment]

        simplified = _douglas_peucker(segment_pts, epsilon_km=1.0)
        distance = sum(
            haversine_km(simplified[j][0], simplified[j][1], simplified[j + 1][0], simplified[j + 1][1])
            for j in range(len(simplified) - 1)
        )
        if distance < min_km:
            continue

        charge_stops = sum(
            1
            for s in stays
            if s.is_charging_guess and window_start <= s.started_at <= window_end
        )

        trips.append(
            TripDraft(
                driver_id=origin.driver_id,
                kyiv_day=kyiv_day_of(window_start),
                origin_lat=origin.lat,
                origin_lon=origin.lon,
                dest_lat=dest.lat,
                dest_lon=dest.lon,
                origin_city=nearest_city(origin.lat, origin.lon),
                dest_city=nearest_city(dest.lat, dest.lon),
                distance_km=round(distance, 2),
                route_points=[[lat, lon] for lat, lon in simplified],
                charge_stop_count=charge_stops,
                started_at=window_start,
                ended_at=window_end,
            )
        )
    return trips


async def fetch_charging_station_coords() -> list[tuple[float, float]]:
    """Cached EVUA + device stations from B2B API (~1h TTL)."""
    import time

    global _station_coords_cache
    now = time.monotonic()
    cached_at, coords = _station_coords_cache
    if coords and now - cached_at < 3600:
        return coords

    out: list[tuple[float, float]] = []
    base = settings.B2B_API_BASE_URL.rstrip("/")
    paths = ("/api/roaming/evua/stations", "/api/device/v2/station/all")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for path in paths:
                try:
                    resp = await client.get(f"{base}{path}")
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    rows = data if isinstance(data, list) else data.get("items") or data.get("stations") or []
                    for row in rows:
                        lat = row.get("lat") or row.get("latitude")
                        lon = row.get("lon") or row.get("longitude") or row.get("lng")
                        if lat is None or lon is None:
                            continue
                        try:
                            out.append((float(lat), float(lon)))
                        except (TypeError, ValueError):
                            continue
                except Exception:
                    continue
    except Exception as exc:
        logger.debug("charging station coords fetch failed: %s", exc)
        return coords

    _station_coords_cache = (now, out)
    return out


async def process_unprocessed_raw(session: AsyncSession) -> dict[str, int]:
    """Process settled unprocessed raw rows into stays/trips."""
    settle = timedelta(minutes=settings.EV_TRACKER_SETTLE_MINUTES)
    cutoff = datetime.now(timezone.utc) - settle

    driver_rows = await session.execute(
        select(EvDriverGpsRaw.driver_id)
        .where(EvDriverGpsRaw.processed.is_(False), EvDriverGpsRaw.recorded_at < cutoff)
        .distinct()
    )
    driver_ids = [r[0] for r in driver_rows.all()]
    if not driver_ids:
        return {"drivers": 0, "stays": 0, "trips": 0, "dropped": 0}

    station_coords = await fetch_charging_station_coords()
    stats = {"drivers": 0, "stays": 0, "trips": 0, "dropped": 0}

    for driver_id in driver_ids:
        raw_rows = await session.execute(
            select(EvDriverGpsRaw)
            .where(
                EvDriverGpsRaw.driver_id == driver_id,
                EvDriverGpsRaw.processed.is_(False),
                EvDriverGpsRaw.recorded_at < cutoff,
            )
            .order_by(EvDriverGpsRaw.recorded_at)
        )
        raw_list = raw_rows.scalars().all()
        if not raw_list:
            continue

        points = [
            TrackPoint(
                driver_id=r.driver_id,
                recorded_at=r.recorded_at,
                lat=r.lat,
                lon=r.lon,
                source=r.source,
                accuracy_m=r.accuracy_m,
            )
            for r in raw_list
        ]
        accepted, dropped = filter_gps_jamming(points)
        stats["dropped"] += len(dropped)

        stays = cluster_stays(accepted)
        mark_charging_stays(stays, station_coords)
        trips = build_trips(accepted, stays)

        for stay in stays:
            stmt = insert(EvDriverStay).values(
                driver_id=stay.driver_id,
                lat=stay.lat,
                lon=stay.lon,
                started_at=stay.started_at,
                ended_at=stay.ended_at,
                point_count=stay.point_count,
                best_source=stay.best_source,
                is_charging_guess=stay.is_charging_guess,
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["driver_id", "started_at"])
            await session.execute(stmt)
            stats["stays"] += 1

        for trip in trips:
            await session.execute(
                insert(EvDriverTrip).values(
                    driver_id=trip.driver_id,
                    kyiv_day=trip.kyiv_day,
                    origin_lat=trip.origin_lat,
                    origin_lon=trip.origin_lon,
                    dest_lat=trip.dest_lat,
                    dest_lon=trip.dest_lon,
                    origin_city=trip.origin_city,
                    dest_city=trip.dest_city,
                    distance_km=trip.distance_km,
                    route_points=trip.route_points,
                    charge_stop_count=trip.charge_stop_count,
                    started_at=trip.started_at,
                    ended_at=trip.ended_at,
                )
            )
            stats["trips"] += 1

        await session.execute(
            text(
                """
                UPDATE ev_driver_gps_raw
                SET processed = TRUE
                WHERE driver_id = :driver_id
                  AND processed = FALSE
                  AND recorded_at < :cutoff
                """
            ),
            {"driver_id": driver_id, "cutoff": cutoff},
        )
        stats["drivers"] += 1

    return stats


async def cleanup_old_raw(session: AsyncSession) -> int:
    """Delete processed raw rows older than retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.EV_TRACKER_RAW_RETENTION_DAYS)
    result = await session.execute(
        delete(EvDriverGpsRaw).where(EvDriverGpsRaw.processed.is_(True), EvDriverGpsRaw.recorded_at < cutoff)
    )
    return int(result.rowcount or 0)


def _round_cell(lat: float, lon: float, precision: int = 2) -> tuple[float, float]:
    return round(lat, precision), round(lon, precision)


async def aggregate_heatmap_points(session: AsyncSession, days: int = 90) -> list[dict[str, Any]]:
    """Anonymized heatmap cells from stays + trip corridors."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    cells: dict[tuple[float, float], float] = {}

    # Stays: dwell-weighted, charging bonus.
    stay_rows = await session.execute(
        select(EvDriverStay).where(EvDriverStay.started_at >= since)
    )
    for stay in stay_rows.scalars().all():
        cell = _round_cell(stay.lat, stay.lon)
        dwell_min = max(1.0, (_ensure_utc(stay.ended_at) - _ensure_utc(stay.started_at)).total_seconds() / 60.0)
        weight = min(10.0, dwell_min / 10.0)
        if stay.is_charging_guess:
            weight *= 2.0
        cells[cell] = cells.get(cell, 0.0) + weight

    trip_rows = await session.execute(select(EvDriverTrip).where(EvDriverTrip.started_at >= since))
    for trip in trip_rows.scalars().all():
        pts = trip.route_points if isinstance(trip.route_points, list) else json.loads(trip.route_points or "[]")
        for pt in pts:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                continue
            cell = _round_cell(float(pt[0]), float(pt[1]))
            cells[cell] = cells.get(cell, 0.0) + 0.5

    return [{"lat": lat, "lng": lon, "count": int(max(1, round(w)))} for (lat, lon), w in cells.items()]


async def aggregate_popular_routes(session: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    since_day = (datetime.now(KYIV).date() - timedelta(days=max(1, days)))
    sql = text(
        """
        SELECT
            COALESCE(origin_city, 'Unknown') AS origin_city,
            COALESCE(dest_city, 'Unknown') AS dest_city,
            COUNT(*)::int AS trip_count,
            COUNT(DISTINCT driver_id)::int AS unique_drivers,
            AVG(distance_km)::double precision AS avg_distance_km,
            AVG(charge_stop_count)::double precision AS avg_charge_stops
        FROM ev_driver_trip
        WHERE kyiv_day >= :since_day
          AND origin_city IS NOT NULL
          AND dest_city IS NOT NULL
          AND origin_city <> dest_city
        GROUP BY origin_city, dest_city
        ORDER BY trip_count DESC
        LIMIT 50
        """
    )
    rows = await session.execute(sql, {"since_day": since_day})
    return [
        {
            "originCity": r.origin_city,
            "destCity": r.dest_city,
            "tripCount": int(r.trip_count),
            "uniqueDrivers": int(r.unique_drivers),
            "avgDistanceKm": round(float(r.avg_distance_km or 0), 1),
            "avgChargeStops": round(float(r.avg_charge_stops or 0), 2),
        }
        for r in rows.mappings().all()
    ]


async def aggregate_open_data_summary(session: AsyncSession, days: int = 30) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    since_day = datetime.now(KYIV).date() - timedelta(days=max(1, days))

    active_drivers = await session.scalar(
        select(func.count(func.distinct(EvDriverGpsRaw.driver_id))).where(EvDriverGpsRaw.recorded_at >= since)
    )
    pings = await session.scalar(select(func.count()).select_from(EvDriverGpsRaw).where(EvDriverGpsRaw.recorded_at >= since))
    stays = await session.scalar(select(func.count()).select_from(EvDriverStay).where(EvDriverStay.started_at >= since))
    trips = await session.scalar(select(func.count()).select_from(EvDriverTrip).where(EvDriverTrip.kyiv_day >= since_day))
    total_km = await session.scalar(
        select(func.coalesce(func.sum(EvDriverTrip.distance_km), 0.0)).where(EvDriverTrip.kyiv_day >= since_day)
    )
    charging_stops = await session.scalar(
        select(func.count()).select_from(EvDriverStay).where(
            EvDriverStay.started_at >= since, EvDriverStay.is_charging_guess.is_(True)
        )
    )

    source_sql = text(
        """
        SELECT source, COUNT(*)::int AS cnt
        FROM ev_driver_gps_raw
        WHERE recorded_at >= :since
        GROUP BY source
        """
    )
    source_rows = await session.execute(source_sql, {"since": since})
    source_breakdown = {r.source: int(r.cnt) for r in source_rows.mappings().all()}

    series_sql = text(
        """
        SELECT
            kyiv_day AS day,
            COUNT(DISTINCT driver_id)::int AS drivers,
            COUNT(*)::int AS trips,
            COALESCE(SUM(distance_km), 0)::double precision AS km
        FROM ev_driver_trip
        WHERE kyiv_day >= :since_day
        GROUP BY kyiv_day
        ORDER BY kyiv_day
        """
    )
    series_rows = await session.execute(series_sql, {"since_day": since_day})
    series = [
        {
            "day": r.day.isoformat() if hasattr(r.day, "isoformat") else str(r.day),
            "drivers": int(r.drivers),
            "trips": int(r.trips),
            "km": round(float(r.km or 0), 1),
        }
        for r in series_rows.mappings().all()
    ]

    return {
        "days": days,
        "activeDrivers": int(active_drivers or 0),
        "pingsIngested": int(pings or 0),
        "stays": int(stays or 0),
        "trips": int(trips or 0),
        "totalKm": round(float(total_km or 0), 1),
        "chargingStops": int(charging_stops or 0),
        "sourceBreakdown": source_breakdown,
        "series": series,
    }


async def aggregate_charging_demand(session: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    sql = text(
        """
        SELECT
            ROUND(lat::numeric, 2)::double precision AS lat,
            ROUND(lon::numeric, 2)::double precision AS lon,
            COUNT(*)::int AS charging_stays,
            COUNT(DISTINCT (driver_id, (started_at AT TIME ZONE 'Europe/Kiev')::date))::int AS unique_driver_days,
            AVG(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60.0)::double precision AS avg_stay_minutes
        FROM ev_driver_stay
        WHERE started_at >= :since
          AND is_charging_guess = TRUE
        GROUP BY ROUND(lat::numeric, 2), ROUND(lon::numeric, 2)
        ORDER BY charging_stays DESC
        LIMIT 100
        """
    )
    rows = await session.execute(sql, {"since": since})
    return [
        {
            "lat": float(r.lat),
            "lng": float(r.lon),
            "chargingStays": int(r.charging_stays),
            "uniqueDriverDays": int(r.unique_driver_days),
            "avgStayMinutes": round(float(r.avg_stay_minutes or 0), 1),
        }
        for r in rows.mappings().all()
    ]
