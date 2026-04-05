"""Official NBU EUR→UAH for DAM chart ENTSO-E overlay (EUR/kWh scaled to UAH/kWh)."""

from __future__ import annotations

import logging
from datetime import date as date_cls, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Query

from app.nbu_fx_service import fetch_nbu_eur_row

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fx", tags=["fx"])


@router.get("/eur-uah")
async def eur_uah(
    date: str = Query(
        ...,
        description="Calendar day YYYY-MM-DD; if NBU has no publication, earlier days are tried",
    ),
) -> dict[str, Any]:
    """
    Return UAH per 1 EUR for the given day (NBU official rate).

    Used to plot ENTSO-E ES/PL lines on the same UAH/kWh scale as the Ukraine OREE series.
    """
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        return {"ok": False, "detail": "invalid date"}
    try:
        d0 = date_cls.fromisoformat(date)
    except ValueError:
        return {"ok": False, "detail": "invalid date"}

    for i in range(10):
        d = d0 - timedelta(days=i)
        compact = d.strftime("%Y%m%d")
        try:
            row = await fetch_nbu_eur_row(compact)
        except httpx.HTTPError as e:
            logger.warning("NBU EUR fetch failed for %s: %s", compact, e)
            return {"ok": False, "detail": "nbu_unavailable"}
        if row is not None:
            rate = row.get("rate")
            if rate is not None and isinstance(rate, (int, float)):
                return {
                    "ok": True,
                    "rate": float(rate),
                    "exchangedate": row.get("exchangedate"),
                    "requested": date,
                    "nbu_query_date": compact,
                    "source": "NBU",
                }
    return {"ok": False, "detail": "no_nbu_rate"}
