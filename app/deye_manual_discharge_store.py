"""Persist manual (UI/API) discharge export metrics for landing totals."""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.deye_discharge_export_parse import parse_discharge_export_session_times
from app.deye_sample_metrics import sum_grid_export_kwh_between
from app.models import DeyeManualDischargeSession

logger = logging.getLogger(__name__)


async def persist_manual_discharge_session_from_api_result(
    session: AsyncSession,
    payload: dict[str, Any],
) -> None:
    """
    Insert one row after a completed ``discharge_soc_delta_then_zero_export_ct`` run
    (sync or background). Skips if ``exportSession.endedAt`` is missing.
    """
    sn = str(payload.get("deviceSn") or "").strip()
    if not sn:
        return
    t0, t1, hit = parse_discharge_export_session_times(payload)
    if t1 is None:
        logger.debug("Manual discharge session: skip persist (no end time) sn=%s", sn)
        return
    export_kwh: Optional[float] = None
    if t0 is not None:
        try:
            export_kwh = await sum_grid_export_kwh_between(session, sn, t0, t1)
        except Exception:
            logger.exception("Manual discharge session: export kWh sum failed sn=%s", sn)
    session.add(
        DeyeManualDischargeSession(
            device_sn=sn,
            export_session_start_at=t0,
            export_session_end_at=t1,
            export_session_kwh=export_kwh,
            discharge_hit_target=hit,
        )
    )
