"""Aggregate metrics from ``deye_soc_sample`` (5‑minute buckets)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def sum_grid_export_kwh_between(
    session: AsyncSession,
    device_sn: str,
    start: datetime,
    end: datetime,
) -> float:
    """
    Approximate kWh exported to grid (grid_power_w < 0) between ``start`` and ``end`` inclusive
    on ``bucket_start`` (same formula as fleet landing totals: |W| / 12000 per row).
    """
    sn = (device_sn or "").strip()
    if not sn or start is None or end is None:
        return 0.0
    if end < start:
        return 0.0
    r = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(
                CASE WHEN grid_power_w < 0 THEN ABS(grid_power_w)::double precision / 12000.0
                ELSE 0 END
            ), 0)::double precision
            FROM deye_soc_sample
            WHERE device_sn = :sn
              AND bucket_start >= :t0
              AND bucket_start <= :t1
            """
        ),
        {"sn": sn, "t0": start, "t1": end},
    )
    v = r.scalar_one()
    return float(v or 0.0)
