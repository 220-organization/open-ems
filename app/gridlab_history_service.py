"""Backfill GridLab hourly history (SoC, meter deltas, energy flows) into PostgreSQL."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.gridlab_api import (
    get_history_flows,
    get_history_meter,
    get_history_soc,
    gridlab_configured,
)
from app.models import GridLabHourlyFlow, GridLabHourlyMeter, GridLabHourlySoc
from app.oree_dam_service import KYIV

logger = logging.getLogger(__name__)

# Vendor limits from External BESS API spec.
FLOWS_METER_MAX_DAYS = 31
SOC_MAX_DAYS = 7


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _optional_int(value: object) -> Optional[int]:
    f = _optional_float(value)
    if f is None:
        return None
    return int(f) if f == int(f) else int(round(f))


def _parse_ts(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def clamp_date_range_to_today(
    date_from: date, date_to: date, *, today: Optional[date] = None
) -> Optional[tuple[date, date]]:
    """
    Clamp to [date_from, min(date_to, today)]. Returns None if the range is empty
    (e.g. entirely in the future — would yield HTTP 422 from GridLab).
    """
    today_kyiv = today if today is not None else datetime.now(KYIV).date()
    start = date_from
    end = min(date_to, today_kyiv)
    if end < start:
        return None
    return start, end


def iter_date_chunks(
    date_from: date,
    date_to: date,
    *,
    max_days: int,
    today: Optional[date] = None,
) -> list[tuple[date, date]]:
    """
    Split an inclusive date range into chunks of at most ``max_days`` calendar days.
    Future dates are clamped to today before chunking.
    """
    clamped = clamp_date_range_to_today(date_from, date_to, today=today)
    if clamped is None:
        return []
    start, end = clamped
    limit = max(1, int(max_days))
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        # Inclusive range of ``limit`` days: cur .. cur+(limit-1)
        chunk_end = min(cur + timedelta(days=limit - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def configured_history_meter_ids() -> list[int]:
    """PCC + PV + LOAD + EV meter IDs used for hourly backfill (deduped, ordered)."""
    ids: list[int] = []
    for mid in (
        settings.GRIDLAB_PCC_METER_ID,
        settings.GRIDLAB_PV_METER_ID,
        settings.GRIDLAB_LOAD_METER_ID,
        *settings.GRIDLAB_EV_METER_IDS,
    ):
        m = int(mid)
        if m > 0 and m not in ids:
            ids.append(m)
    return ids


async def upsert_hourly_soc_row(
    session: AsyncSession,
    device_id: int,
    target_date: date,
    hour: int,
    *,
    soc_percent: Optional[float],
    sample_ts: Optional[datetime],
) -> None:
    if not (0 <= hour <= 23):
        return
    stmt = pg_insert(GridLabHourlySoc).values(
        device_id=device_id,
        target_date=target_date,
        hour=hour,
        soc_percent=soc_percent,
        sample_ts=sample_ts,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["device_id", "target_date", "hour"],
        set_={
            "soc_percent": func.coalesce(stmt.excluded.soc_percent, GridLabHourlySoc.soc_percent),
            "sample_ts": func.coalesce(stmt.excluded.sample_ts, GridLabHourlySoc.sample_ts),
        },
    )
    await session.execute(stmt)


async def upsert_hourly_meter_row(
    session: AsyncSession,
    device_id: int,
    meter_id: int,
    target_date: date,
    hour: int,
    *,
    energy_import_kwh: Optional[float],
    energy_export_kwh: Optional[float],
    avg_power_kw: Optional[float],
    samples: Optional[int],
) -> None:
    if not (0 <= hour <= 23):
        return
    stmt = pg_insert(GridLabHourlyMeter).values(
        device_id=device_id,
        meter_id=meter_id,
        target_date=target_date,
        hour=hour,
        energy_import_kwh=energy_import_kwh,
        energy_export_kwh=energy_export_kwh,
        avg_power_kw=avg_power_kw,
        samples=samples,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["device_id", "meter_id", "target_date", "hour"],
        set_={
            "energy_import_kwh": func.coalesce(
                stmt.excluded.energy_import_kwh, GridLabHourlyMeter.energy_import_kwh
            ),
            "energy_export_kwh": func.coalesce(
                stmt.excluded.energy_export_kwh, GridLabHourlyMeter.energy_export_kwh
            ),
            "avg_power_kw": func.coalesce(
                stmt.excluded.avg_power_kw, GridLabHourlyMeter.avg_power_kw
            ),
            "samples": func.coalesce(stmt.excluded.samples, GridLabHourlyMeter.samples),
        },
    )
    await session.execute(stmt)


async def upsert_hourly_flow_row(
    session: AsyncSession,
    device_id: int,
    target_date: date,
    hour: int,
    row: dict[str, Any],
) -> None:
    if not (0 <= hour <= 23):
        return
    fields = {
        "pv_total": _optional_float(row.get("pv_total")),
        "pv_to_bess": _optional_float(row.get("pv_to_bess")),
        "pv_to_grid": _optional_float(row.get("pv_to_grid")),
        "grid_to_bess": _optional_float(row.get("grid_to_bess")),
        "bess_to_grid": _optional_float(row.get("bess_to_grid")),
        "bess_to_load": _optional_float(row.get("bess_to_load")),
        "grid_to_load": _optional_float(row.get("grid_to_load")),
        "load": _optional_float(row.get("load")),
        "losses": _optional_float(row.get("losses")),
        "fiscal_grid_import": _optional_float(row.get("fiscal_grid_import")),
        "fiscal_grid_export": _optional_float(row.get("fiscal_grid_export")),
    }
    if all(v is None for v in fields.values()):
        # Still store the hour slot so we know it was queried (all null = no measurement).
        pass
    stmt = pg_insert(GridLabHourlyFlow).values(
        device_id=device_id,
        target_date=target_date,
        hour=hour,
        **fields,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["device_id", "target_date", "hour"],
        set_={k: func.coalesce(getattr(stmt.excluded, k), getattr(GridLabHourlyFlow, k)) for k in fields},
    )
    await session.execute(stmt)


async def sync_soc_history(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    *,
    device_id: Optional[int] = None,
) -> int:
    """Pull /history/soc in ≤7-day chunks; upsert rows. Returns hours upserted."""
    if not gridlab_configured():
        return 0
    did = int(device_id if device_id is not None else settings.GRIDLAB_DEVICE_ID)
    n = 0
    for chunk_from, chunk_to in iter_date_chunks(date_from, date_to, max_days=SOC_MAX_DAYS):
        try:
            payload = await get_history_soc(chunk_from, chunk_to)
        except Exception:
            logger.exception(
                "GridLab history/soc failed for %s..%s", chunk_from, chunk_to
            )
            continue
        hours = payload.get("hours") if isinstance(payload, dict) else None
        if not isinstance(hours, list):
            continue
        for row in hours:
            if not isinstance(row, dict):
                continue
            try:
                td = date.fromisoformat(str(row.get("target_date") or ""))
            except ValueError:
                continue
            hour = _optional_int(row.get("hour"))
            if hour is None:
                continue
            await upsert_hourly_soc_row(
                session,
                did,
                td,
                hour,
                soc_percent=_optional_float(row.get("soc_percent")),
                sample_ts=_parse_ts(row.get("timestamp")),
            )
            n += 1
    return n


async def sync_meter_history(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    *,
    device_id: Optional[int] = None,
    meter_ids: Optional[list[int]] = None,
) -> int:
    """Pull /history/meter/{id} for configured meters; upsert. Returns hours upserted."""
    if not gridlab_configured():
        return 0
    did = int(device_id if device_id is not None else settings.GRIDLAB_DEVICE_ID)
    mids = meter_ids if meter_ids is not None else configured_history_meter_ids()
    n = 0
    for meter_id in mids:
        for chunk_from, chunk_to in iter_date_chunks(
            date_from, date_to, max_days=FLOWS_METER_MAX_DAYS
        ):
            try:
                payload = await get_history_meter(meter_id, chunk_from, chunk_to)
            except Exception:
                logger.exception(
                    "GridLab history/meter/%s failed for %s..%s",
                    meter_id,
                    chunk_from,
                    chunk_to,
                )
                continue
            hours = payload.get("hours") if isinstance(payload, dict) else None
            if not isinstance(hours, list):
                continue
            for row in hours:
                if not isinstance(row, dict):
                    continue
                try:
                    td = date.fromisoformat(str(row.get("target_date") or ""))
                except ValueError:
                    continue
                hour = _optional_int(row.get("hour"))
                if hour is None:
                    continue
                # Preserve nulls (no measurement) — do not coerce to 0.
                await upsert_hourly_meter_row(
                    session,
                    did,
                    meter_id,
                    td,
                    hour,
                    energy_import_kwh=_optional_float(row.get("energy_import_kwh")),
                    energy_export_kwh=_optional_float(row.get("energy_export_kwh")),
                    avg_power_kw=_optional_float(row.get("avg_power_kw")),
                    samples=_optional_int(row.get("samples")),
                )
                n += 1
    return n


async def sync_flows_history(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    *,
    device_id: Optional[int] = None,
) -> int:
    """
    Pull /history/flows in ≤31-day chunks.
    Empty ``hours`` is normal for device 16 (as of 2026-07) — not an error.
    """
    if not gridlab_configured():
        return 0
    did = int(device_id if device_id is not None else settings.GRIDLAB_DEVICE_ID)
    n = 0
    for chunk_from, chunk_to in iter_date_chunks(
        date_from, date_to, max_days=FLOWS_METER_MAX_DAYS
    ):
        try:
            payload = await get_history_flows(chunk_from, chunk_to)
        except Exception:
            logger.exception(
                "GridLab history/flows failed for %s..%s", chunk_from, chunk_to
            )
            continue
        hours = payload.get("hours") if isinstance(payload, dict) else None
        if not isinstance(hours, list):
            continue
        if not hours:
            logger.debug(
                "GridLab history/flows empty for %s..%s (device %s)",
                chunk_from,
                chunk_to,
                did,
            )
            continue
        for row in hours:
            if not isinstance(row, dict):
                continue
            try:
                td = date.fromisoformat(str(row.get("target_date") or ""))
            except ValueError:
                continue
            hour = _optional_int(row.get("hour"))
            if hour is None:
                continue
            await upsert_hourly_flow_row(session, did, td, hour, row)
            n += 1
    return n


async def sync_all_history(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    *,
    device_id: Optional[int] = None,
) -> dict[str, int]:
    """Sync SoC + meters + flows for the given range. Idempotent."""
    soc_n = await sync_soc_history(session, date_from, date_to, device_id=device_id)
    meter_n = await sync_meter_history(session, date_from, date_to, device_id=device_id)
    flow_n = await sync_flows_history(session, date_from, date_to, device_id=device_id)
    await session.commit()
    return {"socHours": soc_n, "meterHours": meter_n, "flowHours": flow_n}


async def history_tables_empty(session: AsyncSession, device_id: int) -> bool:
    """True when no hourly SoC rows exist for the device (trigger initial backfill)."""
    result = await session.execute(
        select(func.count())
        .select_from(GridLabHourlySoc)
        .where(GridLabHourlySoc.device_id == device_id)
    )
    return int(result.scalar_one() or 0) == 0


async def run_daily_history_sync(session: AsyncSession) -> dict[str, int]:
    """Sync yesterday + today (Kyiv). Used by the wall-clock scheduler."""
    today = datetime.now(KYIV).date()
    yesterday = today - timedelta(days=1)
    return await sync_all_history(session, yesterday, today)


async def run_startup_backfill_if_empty(session: AsyncSession) -> Optional[dict[str, int]]:
    """If hourly SoC table is empty, backfill GRIDLAB_HISTORY_BACKFILL_DAYS."""
    device_id = int(settings.GRIDLAB_DEVICE_ID)
    if not await history_tables_empty(session, device_id):
        return None
    today = datetime.now(KYIV).date()
    days = max(1, int(settings.GRIDLAB_HISTORY_BACKFILL_DAYS))
    date_from = today - timedelta(days=days - 1)
    logger.info(
        "GridLab history: empty DB — backfilling %s..%s (%s day(s))",
        date_from,
        today,
        days,
    )
    return await sync_all_history(session, date_from, today, device_id=device_id)
