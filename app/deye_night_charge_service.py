"""Backend: auto charge during Kyiv night window 23:00–06:59 (inclusive), once per (night_window_start, device)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app import settings
from app.deye_api import (
    assert_inverter_owned,
    apply_self_consumption_zero_export_ct,
    charge_soc_delta_then_zero_export_ct,
    deye_configured,
)
from app.deye_low_dam_charge_service import (
    CHARGE_SOC_DELTA_PCT_ALLOWED,
    get_low_dam_charge_pref,
    normalize_charge_soc_delta_pct,
    upsert_low_dam_charge_pref,
)
from app.deye_peak_auto_service import get_peak_auto_pref, upsert_peak_auto_pref
from app.deye_self_consumption_auto_dam_service import (
    get_self_consumption_auto_dam_pref,
    upsert_self_consumption_auto_dam_pref,
)
from app.deye_self_consumption_service import get_self_consumption_pref, upsert_self_consumption_pref
from app.models import DeyeNightChargeFired, DeyeNightChargePref
from app.oree_dam_service import KYIV

logger = logging.getLogger(__name__)


def kyiv_night_window_anchor_date(now: datetime) -> Optional[date]:
    """
    Anchor calendar date for the current Kyiv night period (23:00–06:59).
    Same anchor for 23:00–23:59 and the following 00:00–06:59.
    """
    loc = now.astimezone(KYIV)
    d, h = loc.date(), loc.hour
    if h == 23:
        return d
    if 0 <= h < 7:
        return d - timedelta(days=1)
    return None


async def get_night_charge_pref(session: AsyncSession, device_sn: str) -> tuple[bool, int]:
    """(enabled, charge_soc_delta_pct) — defaults when row missing: False, 10."""
    sn = (device_sn or "").strip()
    if not sn:
        return False, 10
    row = await session.get(DeyeNightChargePref, sn)
    if not row:
        return False, 10
    pct = int(row.charge_soc_delta_pct)
    return bool(row.enabled), normalize_charge_soc_delta_pct(pct)


async def upsert_night_charge_pref(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
    charge_soc_delta_pct: int,
) -> None:
    if charge_soc_delta_pct not in CHARGE_SOC_DELTA_PCT_ALLOWED:
        allowed = ", ".join(str(x) for x in CHARGE_SOC_DELTA_PCT_ALLOWED)
        raise ValueError(f"charge_soc_delta_pct must be one of: {allowed}")
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    stmt = (
        pg_insert(DeyeNightChargePref)
        .values(
            device_sn=sn,
            enabled=enabled,
            charge_soc_delta_pct=charge_soc_delta_pct,
        )
        .on_conflict_do_update(
            index_elements=["device_sn"],
            set_={
                "enabled": enabled,
                "charge_soc_delta_pct": charge_soc_delta_pct,
                "updated_on": func.now(),
            },
        )
    )
    await session.execute(stmt)


async def toolbar_snapshot_after_night_change(session: AsyncSession, sn: str) -> dict[str, Any]:
    n_en, n_pct = await get_night_charge_pref(session, sn)
    p_en, p_pct = await get_peak_auto_pref(session, sn)
    l_en, l_pct = await get_low_dam_charge_pref(session, sn)
    sc = await get_self_consumption_pref(session, sn)
    auto_dam = await get_self_consumption_auto_dam_pref(session, sn)
    return {
        "nightChargeEnabled": n_en,
        "chargeSocDeltaPct": int(n_pct if n_en else l_pct),
        "peakDamDischargeEnabled": bool(p_en),
        "dischargeSocDeltaPct": int(p_pct),
        "lowDamChargeEnabled": bool(l_en),
        "selfConsumptionEnabled": bool(sc),
        "selfConsumptionAutoDamEnabled": bool(auto_dam),
    }


async def set_night_charge_from_ui(
    session: AsyncSession,
    device_sn: str,
    enabled: bool,
    charge_soc_delta_pct: int,
) -> dict[str, Any]:
    """
    When enabling: assert ownership, store night pref, disable peak + low DAM prefs, enable self-consumption
    and apply ZERO_EXPORT_TO_CT (same semantics as self-consumption UI).
    When disabling: only turn off night pref.
    """
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    pct = normalize_charge_soc_delta_pct(int(charge_soc_delta_pct))
    if enabled:
        await assert_inverter_owned(sn)
        if not deye_configured():
            raise RuntimeError("Deye API credentials not configured")
        en_p, dp = await get_peak_auto_pref(session, sn)
        _, cp = await get_low_dam_charge_pref(session, sn)
        await upsert_night_charge_pref(session, sn, True, pct)
        await upsert_peak_auto_pref(session, sn, False, dp)
        await upsert_low_dam_charge_pref(session, sn, False, cp)
        await upsert_self_consumption_auto_dam_pref(session, sn, False)
        await upsert_self_consumption_pref(session, sn, True)
        await apply_self_consumption_zero_export_ct(sn)
        if en_p:
            logger.info("Night charge enabled: peak DAM auto disabled device_sn=%s", sn)
    else:
        await upsert_night_charge_pref(session, sn, False, pct)
    return await toolbar_snapshot_after_night_change(session, sn)


async def run_night_charge_tick() -> None:
    if not settings.DEYE_NIGHT_CHARGE_SCHEDULER_ENABLED:
        return
    if not deye_configured():
        return

    from app.db import async_session_factory

    now = datetime.now(KYIV)
    anchor = kyiv_night_window_anchor_date(now)
    if anchor is None:
        return

    async with async_session_factory() as session:
        res = await session.execute(
            select(
                DeyeNightChargePref.device_sn,
                DeyeNightChargePref.charge_soc_delta_pct,
            ).where(DeyeNightChargePref.enabled.is_(True))
        )
        devices = [
            (str(r[0]), normalize_charge_soc_delta_pct(int(r[1])))
            for r in res.all()
            if r[0]
        ]
    if not devices:
        return

    for sn, delta_pct in devices:
        async with async_session_factory() as session:
            q = await session.execute(
                select(DeyeNightChargeFired).where(
                    DeyeNightChargeFired.night_window_start == anchor,
                    DeyeNightChargeFired.device_sn == sn,
                )
            )
            if q.scalar_one_or_none() is not None:
                continue

        logger.info(
            "Night charge auto: starting device_sn=%s night_window_start=%s delta_pct=%s",
            sn,
            anchor.isoformat(),
            delta_pct,
        )
        try:
            await charge_soc_delta_then_zero_export_ct(sn, float(delta_pct))
        except Exception:
            logger.exception("Night charge auto: charge failed device_sn=%s", sn)
            continue

        async with async_session_factory() as session:
            session.add(
                DeyeNightChargeFired(
                    night_window_start=anchor,
                    device_sn=sn,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.warning("Night charge auto: duplicate success row device_sn=%s", sn)
            else:
                logger.info("Night charge auto: success recorded device_sn=%s", sn)
