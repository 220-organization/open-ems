"""Reference battery amortised UAH/kWh (same formula as GET /api/power-flow/reference-lcoe)."""

from __future__ import annotations

import math
from datetime import date
from typing import Optional

from app import settings
from app.nbu_fx_service import fetch_usd_uah_rate_for_date


async def compute_reference_battery_uah_per_kwh(valuation_date: Optional[date] = None) -> Optional[float]:
    """
    Illustrative LiFePO4 LCOE in UAH/kWh from POWER_FLOW_* env and NBU USD→UAH for ``valuation_date`` (default: today UTC).
    """
    d = valuation_date or date.today()
    uah_per_usd = await fetch_usd_uah_rate_for_date(d)
    if uah_per_usd is None or not math.isfinite(uah_per_usd) or uah_per_usd <= 0:
        return None
    dod = float(settings.POWER_FLOW_BATTERY_USABLE_DOD)
    cyc = max(1, int(settings.POWER_FLOW_BATTERY_EQUIV_CYCLES))
    denom_bat = max(1e-12, dod * float(cyc))
    pack = float(settings.POWER_FLOW_REF_LIFEPO4_USD_PER_KWH)
    bop = float(settings.POWER_FLOW_BATTERY_BOP_MULT)
    return pack * bop * uah_per_usd / denom_bat
