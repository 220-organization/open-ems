"""ROI helpers: consumption (load) kWh from deye_soc_sample + DAM at consumption hour (UAH).

PV generation is tracked separately; monetary ROI uses energy avoided on the grid at load time
(solar/battery shifts day production to night consumption).
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.deye_flow_balance import effective_pv_generation_watts
from app.deye_soc_service import deye_soc_balance_input_columns_ready
from app.models import DeyeSocSample
from app.oree_dam_service import KYIV, get_hourly_dam_uah_mwh


def _parse_start_utc(start_iso: str) -> Optional[datetime]:
    raw = (start_iso or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _linear_p(t0: datetime, p0: float, t1: datetime, p1: float, t: datetime) -> float:
    tot = (t1 - t0).total_seconds()
    if tot <= 0:
        return p0
    return p0 + (p1 - p0) * (t - t0).total_seconds() / tot


def _trapezoid_kwh_w(t0: datetime, p0: float, t1: datetime, p1: float) -> float:
    dt_s = (t1 - t0).total_seconds()
    if dt_s <= 0:
        return 0.0
    return ((p0 + p1) / 2.0) * dt_s / 3_600_000.0


def _accumulate_segment_value_uah(
    t0: datetime,
    p0: float,
    t1: datetime,
    p1: float,
    dam_uah_kwh_by_day: dict[date, list[Optional[float]]],
    daily_kwh: Optional[dict[date, float]] = None,
    daily_uah: Optional[dict[date, float]] = None,
) -> tuple[float, float, int]:
    """
    Split [t0,t1] along Kyiv hour boundaries; trapezoid-integrate power (W) to kWh per slice.
    DAM price is taken for the Kyiv hour of each slice (consumption time for load, gen time for PV).
    Returns (energy_kwh, value_uah, missing_dam_hours_count_increment).
    """
    total_kwh = 0.0
    total_uah = 0.0
    missing_slices = 0
    t = t0
    while t < t1:
        k_cur = t.astimezone(KYIV)
        d = k_cur.date()
        hour_floor = k_cur.replace(minute=0, second=0, microsecond=0)
        hour_end_local = hour_floor + timedelta(hours=1)
        t_hour_end = min(t1, hour_end_local.astimezone(timezone.utc))
        pt = _linear_p(t0, p0, t1, p1, t)
        pt_end = _linear_p(t0, p0, t1, p1, t_hour_end)
        kwh = _trapezoid_kwh_w(t, pt, t_hour_end, pt_end)
        total_kwh += kwh
        if daily_kwh is not None:
            daily_kwh[d] = daily_kwh.get(d, 0.0) + kwh
        row = dam_uah_kwh_by_day.get(d)
        h = k_cur.hour
        dam: Optional[float] = None
        if row is not None and len(row) == 24 and 0 <= h <= 23:
            dam = row[h]
        if dam is not None and dam > 0 and kwh > 0:
            uah_slice = kwh * dam
            total_uah += uah_slice
            if daily_uah is not None:
                daily_uah[d] = daily_uah.get(d, 0.0) + uah_slice
        elif kwh > 0 and (dam is None or dam <= 0):
            missing_slices += 1
        t = t_hour_end
    return total_kwh, total_uah, missing_slices


async def _preload_dam_uah_kwh(
    session: AsyncSession,
    d0: date,
    d1: date,
) -> dict[date, list[Optional[float]]]:
    out: dict[date, list[Optional[float]]] = {}
    zone = settings.OREE_COMPARE_ZONE_EIC
    cur = d0
    while cur <= d1:
        mwh = await get_hourly_dam_uah_mwh(session, cur, zone)
        uah_kwh: list[Optional[float]] = []
        for x in mwh:
            if x is None:
                uah_kwh.append(None)
            else:
                uah_kwh.append(float(x) / 1000.0)
        out[cur] = uah_kwh
        cur = cur + timedelta(days=1)
    return out


def _kyiv_previous_month_bounds_utc(now_utc: datetime) -> tuple[datetime, datetime, int, int]:
    """
    Previous calendar month in Europe/Kyiv.
    Returns (start_utc inclusive, end_utc exclusive, year, month) for that month.
    """
    k = now_utc.astimezone(KYIV)
    first_this_month = k.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_prev = first_this_month - timedelta(days=1)
    first_prev = last_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_utc = first_prev.astimezone(timezone.utc)
    end_utc = first_this_month.astimezone(timezone.utc)
    y, m = int(first_prev.year), int(first_prev.month)
    return start_utc, end_utc, y, m


def _empty_roi_payload() -> dict[str, Any]:
    return {
        "totalPvKwh": 0.0,
        "totalConsumptionKwh": 0.0,
        "totalValueUah": 0.0,
        "effectiveRateUahPerKwh": None,
        "sampleCount": 0,
        "segmentCount": 0,
        "missingDamSlices": 0,
        "detail": None,
        "startUsedIso": None,
        "endUsedIso": None,
        "dailyConsumptionKwh": [],
    }


async def _compute_roi_pv_kwh_value_uah_window(
    session: AsyncSession,
    device_sn: str,
    win_start_utc: datetime,
    win_end_utc: datetime,
    *,
    end_exclusive: bool,
) -> dict[str, Any]:
    """
    Integrate PV kWh and DAM UAH for samples in [win_start, win_end] if end_exclusive is False,
    else [win_start, win_end) when end_exclusive is True.
    """
    sn = (device_sn or "").strip()
    empty = _empty_roi_payload()
    if not sn:
        return {**empty, "detail": "invalid_start"}

    extras = await deye_soc_balance_input_columns_ready(session)
    if not extras:
        return {**empty, "detail": "pv_columns_unavailable"}

    end_cond = DeyeSocSample.bucket_start < win_end_utc if end_exclusive else DeyeSocSample.bucket_start <= win_end_utc
    result = await session.execute(
        select(DeyeSocSample.bucket_start, DeyeSocSample.pv_generation_w, DeyeSocSample.pv_power_w).where(
            DeyeSocSample.device_sn == sn,
            DeyeSocSample.bucket_start >= win_start_utc,
            end_cond,
            or_(DeyeSocSample.pv_generation_w.isnot(None), DeyeSocSample.pv_power_w.isnot(None)),
        ).order_by(DeyeSocSample.bucket_start)
    )
    rows = [(r[0], r[1], r[2]) for r in result.all()]

    times: list[datetime] = []
    powers: list[float] = []
    for bucket_start, pv_gen, pv_w in rows:
        pw: Optional[float] = None
        if pv_gen is not None:
            try:
                pw = float(pv_gen)
            except (TypeError, ValueError):
                pw = None
        if pw is None and pv_w is not None:
            try:
                pw = effective_pv_generation_watts(sn, float(pv_w))
            except (TypeError, ValueError):
                pw = None
        if pw is None:
            continue
        times.append(bucket_start if bucket_start.tzinfo else bucket_start.replace(tzinfo=timezone.utc))
        powers.append(pw)

    if len(times) < 2:
        return {
            **empty,
            "sampleCount": len(times),
            "detail": "insufficient_samples",
        }

    d0 = times[0].astimezone(KYIV).date()
    d1 = times[-1].astimezone(KYIV).date()
    dam_by_day = await _preload_dam_uah_kwh(session, d0, d1)

    total_pv_kwh = 0.0
    total_value_uah = 0.0
    missing_dam_slices = 0
    segments = 0

    for i in range(len(times) - 1):
        t0 = times[i]
        t1 = times[i + 1]
        p0 = powers[i]
        p1 = powers[i + 1]
        if t1 <= t0:
            continue
        kwh, uah, miss = _accumulate_segment_value_uah(t0, p0, t1, p1, dam_by_day)
        total_pv_kwh += kwh
        total_value_uah += uah
        missing_dam_slices += miss
        segments += 1

    return {
        "totalPvKwh": total_pv_kwh,
        "totalValueUah": total_value_uah,
        "sampleCount": len(times),
        "segmentCount": segments,
        "missingDamSlices": missing_dam_slices,
        "detail": None,
        "startUsedIso": times[0].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "endUsedIso": times[-1].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


async def _compute_roi_load_kwh_value_uah_window(
    session: AsyncSession,
    device_sn: str,
    win_start_utc: datetime,
    win_end_utc: datetime,
    *,
    end_exclusive: bool,
) -> dict[str, Any]:
    """
    Integrate load (consumption) kWh; UAH = kWh × DAM at each Kyiv hour of consumption.
    Optional daily sums (Kyiv calendar day) for 1-day-step reporting.
    """
    sn = (device_sn or "").strip()
    empty = _empty_roi_payload()
    if not sn:
        return {**empty, "detail": "invalid_start"}

    extras = await deye_soc_balance_input_columns_ready(session)
    if not extras:
        return {**empty, "detail": "pv_columns_unavailable"}

    end_cond = DeyeSocSample.bucket_start < win_end_utc if end_exclusive else DeyeSocSample.bucket_start <= win_end_utc
    result = await session.execute(
        select(DeyeSocSample.bucket_start, DeyeSocSample.load_power_w).where(
            DeyeSocSample.device_sn == sn,
            DeyeSocSample.bucket_start >= win_start_utc,
            end_cond,
            DeyeSocSample.load_power_w.isnot(None),
        ).order_by(DeyeSocSample.bucket_start)
    )
    rows = [(r[0], r[1]) for r in result.all()]

    times: list[datetime] = []
    powers: list[float] = []
    for bucket_start, load_w in rows:
        try:
            lw = max(0.0, float(load_w))
        except (TypeError, ValueError):
            continue
        times.append(bucket_start if bucket_start.tzinfo else bucket_start.replace(tzinfo=timezone.utc))
        powers.append(lw)

    if len(times) < 2:
        return {
            **empty,
            "sampleCount": len(times),
            "detail": "insufficient_load_samples",
        }

    d0 = times[0].astimezone(KYIV).date()
    d1 = times[-1].astimezone(KYIV).date()
    dam_by_day = await _preload_dam_uah_kwh(session, d0, d1)

    daily_kwh: dict[date, float] = {}
    daily_uah: dict[date, float] = {}

    total_cons_kwh = 0.0
    total_value_uah = 0.0
    missing_dam_slices = 0
    segments = 0

    for i in range(len(times) - 1):
        t0 = times[i]
        t1 = times[i + 1]
        p0 = powers[i]
        p1 = powers[i + 1]
        if t1 <= t0:
            continue
        kwh, uah, miss = _accumulate_segment_value_uah(
            t0, p0, t1, p1, dam_by_day, daily_kwh, daily_uah
        )
        total_cons_kwh += kwh
        total_value_uah += uah
        missing_dam_slices += miss
        segments += 1

    daily_rows: list[dict[str, Any]] = []
    for d in sorted(daily_kwh.keys()):
        daily_rows.append(
            {
                "dayIso": d.isoformat(),
                "kwh": round(daily_kwh[d], 4),
                "valueUah": round(daily_uah.get(d, 0.0), 4),
            }
        )

    return {
        "totalPvKwh": 0.0,
        "totalConsumptionKwh": total_cons_kwh,
        "totalValueUah": total_value_uah,
        "sampleCount": len(times),
        "segmentCount": segments,
        "missingDamSlices": missing_dam_slices,
        "detail": None,
        "startUsedIso": times[0].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "endUsedIso": times[-1].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dailyConsumptionKwh": daily_rows,
    }


def _merge_load_and_pv_roi(load_data: dict[str, Any], pv_data: dict[str, Any]) -> dict[str, Any]:
    """Monetary ROI from load × DAM; PV kWh kept for reference. Load errors take precedence."""
    ld = load_data.get("detail")
    detail = ld if ld is not None else None

    tc = float(load_data.get("totalConsumptionKwh") or 0.0)
    tv = float(load_data.get("totalValueUah") or 0.0)
    eff_rate = (tv / tc) if tc > 1e-12 and tv >= 0 else None

    return {
        "totalPvKwh": float(pv_data.get("totalPvKwh") or 0.0),
        "totalConsumptionKwh": tc,
        "totalValueUah": tv,
        "effectiveRateUahPerKwh": eff_rate,
        "sampleCount": int(load_data.get("sampleCount") or 0),
        "segmentCount": int(load_data.get("segmentCount") or 0),
        "missingDamSlices": int(load_data.get("missingDamSlices") or 0),
        "detail": detail,
        "startUsedIso": load_data.get("startUsedIso") or pv_data.get("startUsedIso"),
        "endUsedIso": load_data.get("endUsedIso") or pv_data.get("endUsedIso"),
        "dailyConsumptionKwh": load_data.get("dailyConsumptionKwh") or [],
    }


async def compute_roi_pv_kwh_and_value_uah(
    session: AsyncSession,
    device_sn: str,
    start_iso: str,
) -> dict[str, Any]:
    """
    Consumption kWh (load_power_w) and UAH = kWh × DAM at consumption hour (Kyiv).
    PV generation kWh is returned separately (solar production reference).

    Time range: ROI start .. now (same window for both series).
    """
    sn = (device_sn or "").strip()
    start_utc = _parse_start_utc(start_iso)
    now_utc = datetime.now(timezone.utc)
    empty = _empty_roi_payload()
    if not sn or start_utc is None:
        return {**empty, "detail": "invalid_start"}
    if start_utc >= now_utc:
        return {**empty, "detail": "start_in_future"}

    load_data = await _compute_roi_load_kwh_value_uah_window(
        session, sn, start_utc, now_utc, end_exclusive=False
    )
    pv_data = await _compute_roi_pv_kwh_value_uah_window(
        session, sn, start_utc, now_utc, end_exclusive=False
    )
    return _merge_load_and_pv_roi(load_data, pv_data)


async def compute_roi_pv_kwh_and_value_uah_previous_kyiv_month(
    session: AsyncSession,
    device_sn: str,
    start_iso: str,
) -> dict[str, Any]:
    """
    Same integration as full ROI, but only for the previous calendar month (Europe/Kyiv),
    intersected with [roi_start, now). Used for month-scaled payback hint.
    """
    sn = (device_sn or "").strip()
    roi_start = _parse_start_utc(start_iso)
    now_utc = datetime.now(timezone.utc)
    empty = _empty_roi_payload()
    out: dict[str, Any] = {
        **empty,
        "year": None,
        "month": None,
        "daysInMonth": None,
    }
    if not sn or roi_start is None:
        return {**out, "detail": "invalid_start"}

    ms, me, y, m = _kyiv_previous_month_bounds_utc(now_utc)
    eff_start = max(roi_start, ms)
    eff_end = min(now_utc, me)
    if eff_start >= eff_end:
        return {
            **out,
            "detail": "no_overlap",
            "year": y,
            "month": m,
            "daysInMonth": calendar.monthrange(y, m)[1],
        }

    extras = await deye_soc_balance_input_columns_ready(session)
    if not extras:
        return {
            **out,
            "detail": "pv_columns_unavailable",
            "year": y,
            "month": m,
            "daysInMonth": calendar.monthrange(y, m)[1],
        }

    days_in_month = calendar.monthrange(y, m)[1]

    load_data = await _compute_roi_load_kwh_value_uah_window(
        session, sn, eff_start, eff_end, end_exclusive=True
    )
    pv_data = await _compute_roi_pv_kwh_value_uah_window(
        session, sn, eff_start, eff_end, end_exclusive=True
    )
    data = _merge_load_and_pv_roi(load_data, pv_data)
    data["year"] = y
    data["month"] = m
    data["daysInMonth"] = days_in_month
    return data
