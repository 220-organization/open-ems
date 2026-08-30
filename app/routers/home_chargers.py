"""Home EV chargers catalog — Sparks Chargers Google Merchant feed proxy."""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException

from app import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/home-chargers", tags=["home-chargers"])

_G = "{http://base.google.com/ns/1.0}"
_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}

_PRICE_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*([A-Za-z]{3})?", re.I)
_KW_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*(?:квт|кВт|kw)\b", re.I)
_AMP_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*[aа]\b", re.I)
_CHARGER_TYPE_RE = re.compile(r"електромобільн|ev\s*charg|charging\s*station", re.I)
_EXCLUDE_TYPE_RE = re.compile(
    r"комар|mosquito|dynatrap|сейф|safe|діагностич|диагност|москіт|москит",
    re.I,
)
_ACCESSORY_RE = re.compile(
    r"\b(перехідник|переходник|адаптер|adapter|сумка|bag|розетка|socket|nema\s*14|"
    r"атрактант|attraktant)\b",
    re.I,
)
_CHARGER_TITLE_RE = re.compile(
    r"зарядн|charg|wallbox|станці|станци",
    re.I,
)


def _gtext(item: ET.Element, name: str) -> str:
    el = item.find(f"{_G}{name}")
    return (el.text or "").strip() if el is not None else ""


def _product_details(item: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for pd in item.findall(f"{_G}product_detail"):
        name = ""
        value = ""
        for ch in pd:
            tag = ch.tag.replace(_G, "")
            if tag == "attribute_name":
                name = (ch.text or "").strip()
            elif tag == "attribute_value":
                value = (ch.text or "").strip()
        if name and value:
            out[name] = value
    return out


def _parse_price(raw: str) -> tuple[Optional[float], str]:
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None, "UAH"
    amount = float(m.group(1).replace(",", "."))
    currency = (m.group(2) or "UAH").upper()
    return amount, currency


def _parse_kw(raw: str, blob: str) -> Optional[float]:
    for src in (raw, blob):
        if not src:
            continue
        m = _KW_RE.search(src)
        if m:
            return float(m.group(1).replace(",", "."))
    return None


def _parse_amps(raw: str, blob: str) -> Optional[float]:
    for src in (raw, blob):
        if not src:
            continue
        m = _AMP_RE.search(src)
        if m:
            return float(m.group(1).replace(",", "."))
    return None


def _parse_phases(raw: str, blob: str) -> Optional[int]:
    if raw:
        digits = re.sub(r"\D", "", raw)
        if digits in ("1", "3"):
            return int(digits)
    if re.search(r"3[\s\-]?ф|трифаз|3[\s\-]?ph|three[\s\-]?phase|400\s*в", blob, re.I):
        return 3
    if re.search(r"1[\s\-]?ф|однофаз|1[\s\-]?ph|single[\s\-]?phase|230\s*в", blob, re.I):
        return 1
    return None


def _parse_connectors(raw: str, blob: str) -> list[str]:
    text = f"{raw} {blob}".lower()
    found: list[str] = []
    if re.search(r"type\s*2|тип\s*2", text):
        found.append("Type 2")
    if re.search(r"type\s*1|тип\s*1|j1772", text):
        found.append("Type 1")
    if re.search(r"gb/?t|гб/?т", text):
        found.append("GB/T")
    if re.search(r"\bccs\b", text):
        found.append("CCS")
    # Deduplicate preserving order
    return list(dict.fromkeys(found))


def _is_ev_charger(product_type: str, title: str, description: str, details: dict[str, str]) -> bool:
    blob = f"{product_type} {title} {description}"
    if _EXCLUDE_TYPE_RE.search(blob):
        return False
    if not _CHARGER_TYPE_RE.search(product_type):
        return False
    # Home-charger page is for buying a charger, not adapters / bags / outlets.
    if _ACCESSORY_RE.search(title) and not re.search(r"набір|kit|зарядн(ий|а)\s+пристр", title, re.I):
        return False
    if details.get("Потужність") or _KW_RE.search(title):
        return True
    return bool(_CHARGER_TITLE_RE.search(title) and details.get("Сила струму"))


def _power_bucket(kw: Optional[float]) -> Optional[str]:
    if kw is None:
        return None
    if kw <= 4.0:
        return "upto4"
    if kw <= 8.5:
        return "7to8"
    if kw <= 12.0:
        return "11"
    return "22plus"


def parse_merchant_rss(xml_text: str) -> dict[str, Any]:
    """Parse Google Merchant RSS into EV home-charger products + filter facets."""
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("merchant feed missing channel")

    products: list[dict[str, Any]] = []
    for item in channel.findall("item"):
        title = _gtext(item, "title")
        description = _gtext(item, "description")
        product_type = _gtext(item, "product_type")
        details = _product_details(item)
        if not _is_ev_charger(product_type, title, description, details):
            continue

        # Prefer structured attributes for power — avoid false hits in long descriptions.
        power_kw = _parse_kw(details.get("Потужність", ""), title)
        current_a = _parse_amps(details.get("Сила струму", ""), title)
        phases = _parse_phases(details.get("Кількість фаз", ""), f"{title} {details.get('Вхідна напруга', '')}")
        connectors = _parse_connectors(details.get("Тип роз'ємів", ""), title)
        brand = _gtext(item, "brand") or None
        price_amount, currency = _parse_price(_gtext(item, "price"))

        products.append(
            {
                "id": _gtext(item, "id"),
                "title": title,
                "description": description[:400],
                "link": _gtext(item, "link") or _gtext(item, "ads_redirect"),
                "image": _gtext(item, "image_link"),
                "availability": _gtext(item, "availability") or "unknown",
                "brand": brand,
                "price": price_amount,
                "currency": currency,
                "power_kw": power_kw,
                "power_bucket": _power_bucket(power_kw),
                "current_a": current_a,
                "phases": phases,
                "connectors": connectors,
                "country": details.get("Країна виробник"),
                "cable_cm": details.get("Довжина кабелю"),
                "product_type": product_type,
            }
        )

    products.sort(key=lambda p: (p["price"] is None, p["price"] or 0.0, p["title"]))

    brands = sorted({p["brand"] for p in products if p.get("brand")})
    connectors = sorted({c for p in products for c in (p.get("connectors") or [])})
    phases = sorted({p["phases"] for p in products if p.get("phases") in (1, 3)})
    power_buckets = sorted(
        {p["power_bucket"] for p in products if p.get("power_bucket")},
        key=lambda b: {"upto4": 0, "7to8": 1, "11": 2, "22plus": 3}.get(b, 9),
    )
    prices = [p["price"] for p in products if p.get("price") is not None]

    return {
        "source": "sparkschargers.com.ua",
        "count": len(products),
        "products": products,
        "facets": {
            "brands": brands,
            "connectors": connectors,
            "phases": phases,
            "power_buckets": power_buckets,
            "price_min": min(prices) if prices else None,
            "price_max": max(prices) if prices else None,
        },
    }


async def _fetch_feed() -> str:
    url = (settings.HOME_CHARGERS_FEED_URL or "").strip()
    if not url:
        raise HTTPException(status_code=503, detail="Home chargers feed is not configured")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text
    except httpx.HTTPError as exc:
        logger.warning("home chargers feed fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to fetch charger catalog") from exc


@router.get("")
async def list_home_chargers(refresh: bool = False) -> dict[str, Any]:
    """Return EV home chargers from the Sparks merchant feed (cached)."""
    ttl = max(60, int(settings.HOME_CHARGERS_CACHE_TTL_SEC))
    now = time.time()
    if (
        not refresh
        and _CACHE["payload"] is not None
        and (now - float(_CACHE["ts"])) < ttl
    ):
        return _CACHE["payload"]

    xml_text = await _fetch_feed()
    try:
        payload = parse_merchant_rss(xml_text)
    except (ET.ParseError, ValueError) as exc:
        logger.warning("home chargers feed parse failed: %s", exc)
        raise HTTPException(status_code=502, detail="Invalid charger catalog feed") from exc

    payload["cached"] = False
    payload["cache_ttl_sec"] = ttl
    _CACHE["payload"] = {**payload, "cached": True}
    _CACHE["ts"] = now
    return payload
