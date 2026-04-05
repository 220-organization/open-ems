"""ENTSO-E Transparency REST API — day-ahead prices (DocumentType A44, ProcessType A01) into entsoe_dam_price."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.models import EntsoeDamPrice
from app.nbu_fx_service import fetch_eur_uah_rate_for_date

logger = logging.getLogger(__name__)

BRUSSELS = ZoneInfo("Europe/Brussels")

# Ukraine bidding zone — ENTSO-E often publishes day-ahead price.amount in UAH/MWh (not EUR/MWh).
UKRAINE_ZONE_EIC = "10Y1001C--000182"


def entsoe_dam_configured() -> bool:
    return bool(settings.ENTSOE_SECURITY_TOKEN and settings.ENTSOE_SECURITY_TOKEN.strip())


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def delivery_tomorrow_brussels() -> date:
    """Next calendar day in Europe/Brussels (typical CET/CEST DAM delivery for EU coupling)."""
    return (datetime.now(BRUSSELS).date() + timedelta(days=1))


def period_start_end_utc(delivery_day: date, tz_name: str) -> tuple[str, str]:
    """
    ENTSO-E expects periodStart/periodEnd as YYYYMMDDHHmm in UTC.
    Bounds: local midnight of delivery_day → local midnight of next day (delivery window).
    """
    z = ZoneInfo(tz_name)
    start_local = datetime.combine(delivery_day, time.min, tzinfo=z)
    end_local = datetime.combine(delivery_day + timedelta(days=1), time.min, tzinfo=z)
    utc = ZoneInfo("UTC")
    su = start_local.astimezone(utc)
    eu = end_local.astimezone(utc)
    return su.strftime("%Y%m%d%H%M"), eu.strftime("%Y%m%d%H%M")


def _first_currency_name_from_root(root: ET.Element) -> str:
    """Read currency name from first TimeSeries (e.g. EUR / UAH)."""
    for el in root.iter():
        if _local_tag(el.tag) != "TimeSeries":
            continue
        for ch in el:
            if _local_tag(ch.tag) == "currency":
                for cc in ch:
                    if _local_tag(cc.tag) == "name" and cc.text:
                        return cc.text.strip().upper()
        for k, v in el.attrib.items():
            if _local_tag(k) == "currency" and v:
                return str(v).strip().upper()
    return ""


def parse_entsoe_price_points_xml(content: bytes) -> tuple[Optional[str], dict[int, float], str]:
    """
    Parse Publication_MarketDocument / Price_MarketDocument XML; collect position -> price (per MWh in document currency).
    Returns (acknowledgement_error_or_None, position_to_price, currency_name_upper_or_empty).
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        return f"XML parse error: {exc}", {}, ""

    if _local_tag(root.tag) == "Acknowledgement_MarketDocument":
        ack_reasons: list[str] = []
        for el in root.iter():
            if _local_tag(el.tag) == "Reason":
                code = el.attrib.get("code", "") or ""
                txt = (el.text or "").strip()
                ack_reasons.append(f"{code}:{txt}".strip(":") if code else txt)
        return "; ".join(ack_reasons) or "Acknowledgement", {}, ""

    currency = _first_currency_name_from_root(root)

    by_pos: dict[int, float] = {}
    for el in root.iter():
        if _local_tag(el.tag) != "Point":
            continue
        pos: Optional[int] = None
        price: Optional[float] = None
        for ch in el:
            lt = _local_tag(ch.tag)
            if lt == "position" and ch.text is not None:
                try:
                    pos = int(str(ch.text).strip())
                except ValueError:
                    pos = None
            elif lt == "price.amount" and ch.text is not None:
                try:
                    price = float(str(ch.text).strip().replace(",", "."))
                except ValueError:
                    price = None
        if pos is not None and price is not None:
            by_pos[pos] = price

    if not by_pos:
        return "No price points in document", {}, currency

    max_pos = max(by_pos)
    if max_pos <= 24:
        return None, {p: by_pos[p] for p in sorted(by_pos) if 1 <= p <= 24}, currency
    # 15-minute resolution: collapse 96 intervals to 24 hourly averages
    hourly: dict[int, float] = {}
    for h in range(1, 25):
        chunk = [by_pos[p] for p in range((h - 1) * 4 + 1, h * 4 + 1) if p in by_pos]
        if chunk:
            hourly[h] = sum(chunk) / len(chunk)
    return None, hourly, currency


async def fetch_entsoe_day_ahead_points(
    domain_eic: str,
    delivery_day: date,
    delivery_tz: str,
) -> tuple[dict[int, float], Optional[str], str]:
    """
    GET ENTSO-E web API (A44/A01). Uses document parameters only — current Transparency REST API
    rejects ``curveType`` (HTTP 400: Input parameter does not exist: curveType).
    Hourly vs 15-minute resolution is inferred from Point positions in the XML.
    Returns (position -> price per MWh in document currency, error_message, currency_code_upper).
    """
    if not entsoe_dam_configured():
        return {}, "ENTSOE_SECURITY_TOKEN not set", ""
    ps, pe = period_start_end_utc(delivery_day, delivery_tz)
    base: dict[str, str] = {
        "securityToken": settings.ENTSOE_SECURITY_TOKEN.strip(),
        "documentType": "A44",
        "processType": "A01",
        "in_Domain": domain_eic,
        "out_Domain": domain_eic,
        "periodStart": ps,
        "periodEnd": pe,
    }
    url = settings.ENTSOE_API_BASE_URL
    headers = {
        "Accept": "application/xml",
        "User-Agent": settings.ENTSOE_HTTP_USER_AGENT or "OpenEMS/1.0",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url, headers=headers, params=base)
        if r.status_code >= 400:
            return {}, f"HTTP {r.status_code}: {(r.text or '')[:800]}", ""
        err, points, currency = parse_entsoe_price_points_xml(r.content)
        if err:
            return {}, err, currency or ""
        if points:
            return points, None, currency or ""
        return {}, "No <Point> price.amount in response", currency or ""


async def sync_entsoe_zone_to_db(
    session: AsyncSession,
    zone_eic: str,
    delivery_day: date,
) -> int:
    """Fetch ENTSO-E DAM for one zone/day and upsert rows. Returns rows written."""
    tz_name = settings.ENTSOE_DOMAIN_TIMEZONE.get(zone_eic, "Europe/Madrid")
    points, errmsg, currency_raw = await fetch_entsoe_day_ahead_points(zone_eic, delivery_day, tz_name)
    if errmsg:
        logger.warning("ENTSO-E %s %s: %s", zone_eic, delivery_day, errmsg)
        return 0
    if not points:
        return 0

    cur = (currency_raw or "").strip().upper()
    if not cur and zone_eic == UKRAINE_ZONE_EIC:
        cur = "UAH"
    if not cur:
        cur = "EUR"
    if cur == "UAH":
        rate = await fetch_eur_uah_rate_for_date(delivery_day)
        if rate is None or rate <= 0:
            logger.warning(
                "ENTSO-E %s %s: prices in UAH/MWh but NBU EUR/UAH unavailable — skip upsert",
                zone_eic,
                delivery_day,
            )
            return 0
        # Store EUR/MWh in entsoe_dam_price.price_eur_mwh (same as ES/PL).
        points = {p: float(v) / rate for p, v in points.items()}
    elif cur != "EUR":
        logger.warning(
            "ENTSO-E %s %s: unsupported currency %r — treating amounts as EUR/MWh",
            zone_eic,
            delivery_day,
            cur,
        )

    upsert_sql = text(
        """
        INSERT INTO entsoe_dam_price (trade_day, zone_eic, period, price_eur_mwh, created_on, updated_on)
        VALUES (:trade_day, :zone_eic, :period, :price_eur_mwh, NOW(), NOW())
        ON CONFLICT (trade_day, zone_eic, period) DO UPDATE SET
          price_eur_mwh = EXCLUDED.price_eur_mwh,
          updated_on = NOW()
        """
    )
    n = 0
    for pos, eur in sorted(points.items()):
        if not (1 <= pos <= 24):
            continue
        await session.execute(
            upsert_sql,
            {
                "trade_day": delivery_day,
                "zone_eic": zone_eic,
                "period": pos,
                "price_eur_mwh": float(eur),
            },
        )
        n += 1
    return n


async def sync_entsoe_all_configured_zones(session: AsyncSession, delivery_day: date) -> int:
    """Fetch and upsert all ENTSOE_DAM_ZONE_EICS zones for delivery_day. Returns total rows written."""
    total = 0
    for z in settings.ENTSOE_DAM_ZONE_EICS:
        ze = z.strip()
        if not ze:
            continue
        try:
            total += await sync_entsoe_zone_to_db(session, ze, delivery_day)
        except Exception:
            logger.exception("ENTSO-E sync failed for zone %s", ze)
    await session.commit()
    return total


async def entsoe_trade_day_complete_in_db(
    session: AsyncSession,
    trade_day: date,
    zone_eic: str,
) -> bool:
    hourly = await get_hourly_entsoe_eur_mwh(session, trade_day, zone_eic)
    return len(hourly) == 24 and all(x is not None for x in hourly)


async def get_hourly_entsoe_eur_mwh(
    session: AsyncSession,
    trade_day: date,
    zone_eic: str,
) -> list[Optional[float]]:
    result = await session.execute(
        select(EntsoeDamPrice.period, EntsoeDamPrice.price_eur_mwh).where(
            EntsoeDamPrice.trade_day == trade_day,
            EntsoeDamPrice.zone_eic == zone_eic,
        )
    )
    by_period: dict[int, float] = {}
    for p, price in result.all():
        if 1 <= int(p) <= 24:
            by_period[int(p)] = float(price)
    return [by_period.get(p) for p in range(1, 25)]


def resolve_zone_eic(zone: str) -> Optional[str]:
    """Map alias (ES, …) or pass through full EIC."""
    z = zone.strip().upper()
    if z in settings.ENTSOE_ZONE_ALIASES:
        return settings.ENTSOE_ZONE_ALIASES[z]
    s = zone.strip()
    if len(s) >= 10 and "-" in s:
        return s
    return None


def list_zone_catalog() -> list[dict[str, Any]]:
    """UI/API: known zones with EIC + timezone."""
    out: list[dict[str, Any]] = []
    for alias, eic in sorted(settings.ENTSOE_ZONE_ALIASES.items(), key=lambda x: x[0]):
        out.append(
            {
                "alias": alias,
                "zoneEic": eic,
                "timeZone": settings.ENTSOE_DOMAIN_TIMEZONE.get(eic, "Europe/Madrid"),
            }
        )
    return out
