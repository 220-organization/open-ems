"""Estimate BESS nominal capacity (kWh) from the last deep discharge energy balance.

During a discharge window:
    battery_kwh ≈ load_kwh − grid_import_kwh − solar_kwh
    nominal_kwh ≈ battery_kwh / (soc_start − soc_end) × 100
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deye_flow_balance import FLOW_BALANCE_PV_FACTOR, device_uses_flow_balance

logger = logging.getLogger(__name__)

MIN_DEEP_SOC_DELTA_PCT = 10.0
MIN_BATTERY_ENERGY_KWH = 0.5
MAX_SESSION_LOOKBACK = 8
# Fallback window when legacy rows only have success_at (no exportSession bounds).
_INFERRED_SESSION_LOOKBACK_HOURS = 3


@dataclass(frozen=True)
class DischargeSessionWindow:
    device_sn: str
    start_at: datetime
    end_at: datetime
    hit_target: Optional[bool]
    source: str


def estimate_capacity_kwh_from_balance(
    *,
    load_kwh: float,
    grid_import_kwh: float,
    solar_kwh: float,
    soc_start: Optional[float],
    soc_end: Optional[float],
    hit_target: Optional[bool] = None,
) -> Optional[float]:
    """Return nominal kWh when the window looks like a deep discharge."""
    if soc_start is None or soc_end is None:
        return None
    soc_delta = float(soc_start) - float(soc_end)
    if soc_delta < MIN_DEEP_SOC_DELTA_PCT:
        return None
    if soc_end > 25.0 and hit_target is not True:
        return None
    battery_kwh = float(load_kwh) - float(grid_import_kwh) - float(solar_kwh)
    if battery_kwh < MIN_BATTERY_ENERGY_KWH:
        return None
    return battery_kwh / (soc_delta / 100.0)


def _pv_factor_for_device(device_sn: str) -> float:
    return float(FLOW_BALANCE_PV_FACTOR) if device_uses_flow_balance(device_sn) else 1.0


async def _list_recent_discharge_sessions(session: AsyncSession) -> list[DischargeSessionWindow]:
    r = await session.execute(
        text(
            """
            WITH sessions AS (
                SELECT
                    device_sn,
                    COALESCE(
                        export_session_start_at,
                        success_at - make_interval(hours => :lookback_hours)
                    ) AS start_at,
                    COALESCE(export_session_end_at, success_at) AS end_at,
                    discharge_hit_target AS hit_target,
                    success_at,
                    'manual' AS source
                FROM deye_manual_discharge_session
                WHERE (
                    export_session_start_at IS NOT NULL
                    AND export_session_end_at IS NOT NULL
                ) OR success_at IS NOT NULL
                UNION ALL
                SELECT
                    device_sn,
                    COALESCE(
                        export_session_start_at,
                        success_at - make_interval(hours => :lookback_hours)
                    ),
                    COALESCE(export_session_end_at, success_at),
                    peak_discharge_hit_target,
                    success_at,
                    'peak'
                FROM deye_peak_auto_discharge_fired
                WHERE (
                    export_session_start_at IS NOT NULL
                    AND export_session_end_at IS NOT NULL
                ) OR success_at IS NOT NULL
            ),
            ranked AS (
                SELECT
                    device_sn,
                    start_at,
                    end_at,
                    hit_target,
                    source,
                    ROW_NUMBER() OVER (
                        PARTITION BY device_sn
                        ORDER BY end_at DESC NULLS LAST, success_at DESC NULLS LAST
                    ) AS rn
                FROM sessions
                WHERE start_at IS NOT NULL
                  AND end_at IS NOT NULL
                  AND end_at > start_at
            )
            SELECT device_sn, start_at, end_at, hit_target, source
            FROM ranked
            WHERE rn <= :max_lookback
            ORDER BY device_sn, end_at DESC
            """
        ),
        {
            "max_lookback": MAX_SESSION_LOOKBACK,
            "lookback_hours": _INFERRED_SESSION_LOOKBACK_HOURS,
        },
    )
    out: list[DischargeSessionWindow] = []
    for row in r.all():
        sn = str(row[0] or "").strip()
        if not sn:
            continue
        out.append(
            DischargeSessionWindow(
                device_sn=sn,
                start_at=row[1],
                end_at=row[2],
                hit_target=bool(row[3]) if row[3] is not None else None,
                source=str(row[4] or ""),
            )
        )
    return out


async def _session_energy_and_soc(
    session: AsyncSession,
    device_sn: str,
    start_at: datetime,
    end_at: datetime,
) -> Optional[tuple[float, float, float, Optional[float], Optional[float], int]]:
    """(load_kwh, grid_import_kwh, solar_kwh, soc_start, soc_end, energy_sample_count)."""
    pv_factor = _pv_factor_for_device(device_sn)
    r = await session.execute(
        text(
            """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN load_power_w > 0 THEN load_power_w::double precision / 12000.0
                        WHEN grid_power_w IS NOT NULL AND battery_power_w IS NOT NULL THEN
                            GREATEST(
                                0.0,
                                COALESCE(grid_power_w, 0)::double precision
                                + :pv_factor * COALESCE(
                                    pv_generation_w, pv_power_w, 0
                                )::double precision
                                + COALESCE(battery_power_w, 0)::double precision
                            ) / 12000.0
                        ELSE 0.0
                    END
                ), 0)::double precision,
                COALESCE(SUM(
                    CASE WHEN grid_power_w > 0 THEN grid_power_w::double precision / 12000.0
                    ELSE 0 END
                ), 0)::double precision,
                COALESCE(SUM(
                    CASE WHEN COALESCE(pv_generation_w, pv_power_w, 0) > 0
                    THEN COALESCE(pv_generation_w, pv_power_w)::double precision / 12000.0
                    ELSE 0 END
                ), 0)::double precision,
                (
                    SELECT MAX(s2.soc_percent)
                    FROM deye_soc_sample s2
                    WHERE s2.device_sn = :sn
                      AND s2.bucket_start >= :t0
                      AND s2.bucket_start <= :t1
                      AND s2.soc_percent IS NOT NULL
                ),
                (
                    SELECT MIN(s3.soc_percent)
                    FROM deye_soc_sample s3
                    WHERE s3.device_sn = :sn
                      AND s3.bucket_start >= :t0
                      AND s3.bucket_start <= :t1
                      AND s3.soc_percent IS NOT NULL
                ),
                COUNT(*) FILTER (
                    WHERE load_power_w IS NOT NULL
                       OR (grid_power_w IS NOT NULL AND battery_power_w IS NOT NULL)
                )::int
            FROM deye_soc_sample
            WHERE device_sn = :sn
              AND bucket_start >= :t0
              AND bucket_start <= :t1
            """
        ),
        {"sn": device_sn, "t0": start_at, "t1": end_at, "pv_factor": pv_factor},
    )
    row = r.one_or_none()
    if row is None:
        return None
    energy_samples = int(row[5] or 0)
    if energy_samples < 1:
        return None
    return (
        float(row[0] or 0.0),
        float(row[1] or 0.0),
        float(row[2] or 0.0),
        float(row[3]) if row[3] is not None else None,
        float(row[4]) if row[4] is not None else None,
        energy_samples,
    )


async def estimate_device_capacity_kwh(session: AsyncSession, device_sn: str) -> Optional[float]:
    """Nominal kWh from the latest qualifying deep discharge for one inverter."""
    sn = (device_sn or "").strip()
    if not sn:
        return None
    sessions = [s for s in await _list_recent_discharge_sessions(session) if s.device_sn == sn]
    for win in sessions:
        metrics = await _session_energy_and_soc(session, sn, win.start_at, win.end_at)
        if metrics is None:
            continue
        load_kwh, grid_kwh, solar_kwh, soc_start, soc_end, _ = metrics
        cap = estimate_capacity_kwh_from_balance(
            load_kwh=load_kwh,
            grid_import_kwh=grid_kwh,
            solar_kwh=solar_kwh,
            soc_start=soc_start,
            soc_end=soc_end,
            hit_target=win.hit_target,
        )
        if cap is not None:
            return cap
    return None


async def fleet_battery_capacity_summary(session: AsyncSession) -> dict[str, Any]:
    """
    Sum nominal kWh across devices calibrated from their last deep discharge.
    Also returns current stored kWh using the latest SoC sample per device.
    """
    sessions = await _list_recent_discharge_sessions(session)
    by_device: dict[str, list[DischargeSessionWindow]] = {}
    for win in sessions:
        by_device.setdefault(win.device_sn, []).append(win)

    per_device_kwh: dict[str, float] = {}
    for sn, wins in by_device.items():
        for win in wins:
            metrics = await _session_energy_and_soc(session, sn, win.start_at, win.end_at)
            if metrics is None:
                continue
            load_kwh, grid_kwh, solar_kwh, soc_start, soc_end, _ = metrics
            cap = estimate_capacity_kwh_from_balance(
                load_kwh=load_kwh,
                grid_import_kwh=grid_kwh,
                solar_kwh=solar_kwh,
                soc_start=soc_start,
                soc_end=soc_end,
                hit_target=win.hit_target,
            )
            if cap is not None:
                per_device_kwh[sn] = cap
                break

    total_capacity_kwh = sum(per_device_kwh.values())
    current_stored_kwh = 0.0
    current_devices = 0
    if per_device_kwh:
        r = await session.execute(
            text(
                """
                SELECT DISTINCT ON (device_sn)
                    device_sn,
                    soc_percent
                FROM deye_soc_sample
                WHERE device_sn = ANY(:sns)
                  AND soc_percent IS NOT NULL
                ORDER BY device_sn, bucket_start DESC
                """
            ),
            {"sns": list(per_device_kwh.keys())},
        )
        for row in r.all():
            sn = str(row[0] or "").strip()
            soc = float(row[1]) if row[1] is not None else None
            cap = per_device_kwh.get(sn)
            if sn and cap is not None and soc is not None and soc >= 0:
                current_stored_kwh += (soc / 100.0) * cap
                current_devices += 1

    return {
        "ok": True,
        "totalCapacityKwh": round(total_capacity_kwh, 1) if total_capacity_kwh > 0 else None,
        "totalCapacityMwh": round(total_capacity_kwh / 1000.0, 2) if total_capacity_kwh > 0 else None,
        "currentStoredKwh": round(current_stored_kwh, 1) if current_stored_kwh > 0 else None,
        "currentStoredMwh": round(current_stored_kwh / 1000.0, 2) if current_stored_kwh > 0 else None,
        "calibratedDeviceCount": len(per_device_kwh),
        "deviceCapacitiesKwh": {k: round(v, 1) for k, v in per_device_kwh.items()},
    }
