"""Home EV chargers catalog — Sparks Chargers PROM Google Sheet proxy."""

from __future__ import annotations

import csv
import html
import io
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException

from app import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/home-chargers", tags=["home-chargers"])

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_FALLBACK_CSV = Path(__file__).resolve().parents[1] / "data" / "sparks_home_chargers.csv"
_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")

_PRICE_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*([A-Za-z]{3})?", re.I)
_KW_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*(?:квт|кВт|kw)\b", re.I)
_AMP_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*[aа]\b", re.I)
_TAG_RE = re.compile(r"<[^>]+>", re.S)
_EXCLUDE_TYPE_RE = re.compile(
    r"комар|mosquito|dynatrap|сейф|safe|діагностич|диагност|москіт|москит",
    re.I,
)
_ADAPTER_RE = re.compile(r"\b(перехідник|переходник|адаптер|adapter)\b", re.I)
_CABLE_RE = re.compile(r"\b(кабель|cable)\b", re.I)
_CHARGER_TITLE_RE = re.compile(
    r"зарядн(ий|а|ое)\s+(пристр|станц)|wallbox|charging\s*station|зарядка для",
    re.I,
)
_KIND_ORDER = {"charger": 0, "adapter": 1, "cable": 2}
_POWER_BUCKET_ORDER = {"upto4": 0, "7to8": 1, "11": 2, "22plus": 3}


def _to_csv_export_url(url: str) -> str:
    """Accept edit or export Google Sheets URL; return gviz CSV export URL."""
    raw = (url or "").strip()
    if not raw:
        return raw
    if "export?format=csv" in raw or "/export?" in raw or "tqx=out:csv" in raw:
        return raw
    m = _SHEET_ID_RE.search(raw)
    if not m:
        return raw
    sheet_id = m.group(1)
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    frag = parse_qs((parsed.fragment or "").replace("?", "&"))
    gid = (qs.get("gid") or frag.get("gid") or [None])[0]
    params: dict[str, str] = {"tqx": "out:csv"}
    if gid is not None and str(gid).strip() != "":
        params["gid"] = str(gid).strip()
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
        + urlencode(params)
    )


def _csv_export_fallback_urls(url: str) -> list[str]:
    primary = _to_csv_export_url(url)
    out = [primary] if primary else []
    m = _SHEET_ID_RE.search(url or "")
    if not m:
        return out
    sheet_id = m.group(1)
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    frag = parse_qs((parsed.fragment or "").replace("?", "&"))
    gid = (qs.get("gid") or frag.get("gid") or [None])[0]
    candidates = [
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv",
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv",
    ]
    if gid is not None and str(gid).strip() != "":
        g = str(gid).strip()
        candidates.extend(
            [
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
                + urlencode({"tqx": "out:csv", "gid": g}),
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?"
                + urlencode({"format": "csv", "gid": g}),
            ]
        )
    for c in candidates:
        if c not in out:
            out.append(c)
    return out


async def _fetch_csv(url: str) -> str:
    last_exc: Optional[Exception] = None
    headers = {
        "User-Agent": "OpenEMS-HomeChargers/1.0 (+https://220-km.com; catalog fetch)",
        "Accept": "text/csv,text/plain,*/*",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=45.0, headers=headers) as client:
        for export in _csv_export_fallback_urls(url):
            try:
                resp = await client.get(export)
                if resp.status_code >= 400:
                    last_exc = httpx.HTTPStatusError(
                        f"{resp.status_code} for {export}",
                        request=resp.request,
                        response=resp,
                    )
                    logger.warning("home chargers sheet HTTP %s for %s", resp.status_code, export)
                    continue
                text = resp.content.decode("utf-8-sig", errors="replace")
                if "<html" in text[:200].lower():
                    last_exc = RuntimeError(f"HTML response for {export}")
                    logger.warning("home chargers sheet got HTML for %s", export)
                    continue
                return text
            except Exception as exc:
                last_exc = exc
                logger.warning("home chargers sheet fetch failed for %s: %s", export, exc)
    assert last_exc is not None
    raise last_exc


def _header_index(header: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, name in enumerate(header):
        key = (name or "").strip()
        if key and key not in out:
            out[key] = i
    return out


def _cell(row: list[str], idx: dict[str, int], name: str) -> str:
    i = idx.get(name)
    if i is None or i >= len(row):
        return ""
    return (row[i] or "").strip()


def _product_details(row: list[str], header: list[str]) -> dict[str, str]:
    start = next((i for i, h in enumerate(header) if h == "Назва_Характеристики"), None)
    if start is None:
        return {}
    out: dict[str, str] = {}
    i = start
    while i + 2 < len(row):
        name = (row[i] or "").strip()
        unit = (row[i + 1] or "").strip()
        value = (row[i + 2] or "").strip()
        if name and value:
            out[name] = f"{value} {unit}".strip() if unit else value
        i += 3
    return out


def _strip_html(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _first_image(raw: str) -> str:
    for part in (raw or "").split(","):
        url = part.strip()
        if url.startswith("http"):
            return url
    return ""


def _parse_number(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace("\xa0", " ").replace(" ", "")
    if not s or s in ("—", "-", "–"):
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_price(raw: str) -> tuple[Optional[float], str]:
    amount = _parse_number(raw)
    if amount is not None:
        return amount, "UAH"
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None, "UAH"
    return float(m.group(1).replace(",", ".")), (m.group(2) or "UAH").upper()


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


def _parse_connectors(raw: str) -> list[str]:
    """Parse connector types from the PROM characteristic only (not the marketing title)."""
    text = (raw or "").lower()
    if not text:
        return []
    found: list[str] = []
    if re.search(r"type\s*2|тип\s*2", text):
        found.append("Type 2")
    if re.search(r"type\s*1|тип\s*1|j1772", text):
        found.append("Type 1")
    if re.search(r"gb/?t|гб/?т", text):
        found.append("GB/T")
    if re.search(r"ccs\s*2|ccs2", text):
        found.append("CCS2")
    if re.search(r"ccs\s*1|ccs1", text):
        found.append("CCS1")
    if re.search(r"\bccs\b", text) and "CCS2" not in found and "CCS1" not in found:
        found.append("CCS")
    if re.search(r"nacs|tesla\s*usa|\btesla\b", text):
        found.append("NACS")
    return list(dict.fromkeys(found))


def _product_kind(title: str) -> Optional[str]:
    """Classify catalog rows: charger, adapter, cable — or skip unrelated goods."""
    text = title or ""
    if _EXCLUDE_TYPE_RE.search(text):
        return None
    is_charger = bool(_CHARGER_TITLE_RE.search(text))
    is_cable = bool(_CABLE_RE.search(text))
    is_adapter = bool(_ADAPTER_RE.search(text))
    if is_cable and not is_charger:
        return "cable"
    if is_adapter and not is_charger:
        return "adapter"
    if is_charger:
        return "charger"
    if is_cable:
        return "cable"
    if is_adapter:
        return "adapter"
    return None


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


def _availability(raw: str) -> str:
    s = (raw or "").strip()
    if s == "+":
        return "in stock"
    if s == "!":
        return "on request"
    if s in ("-", "−", "–"):
        return "out of stock"
    return s or "unknown"


def parse_prom_csv(csv_text: str) -> dict[str, Any]:
    """Parse Sparks PROM export CSV into EV home-charger products + filter facets."""
    reader = csv.reader(io.StringIO(csv_text or ""))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("prom catalog csv is empty") from None
    idx = _header_index(header)

    products: list[dict[str, Any]] = []
    for row in reader:
        if not any((c or "").strip() for c in row):
            continue
        title = _cell(row, idx, "Назва_позиції_укр") or _cell(row, idx, "Назва_позиції")
        details = _product_details(row, header)
        kind = _product_kind(title)
        if not kind:
            continue

        power_kw = _parse_kw(details.get("Потужність", ""), title)
        current_a = _parse_amps(details.get("Сила струму", ""), title)
        phases = _parse_phases(
            details.get("Кількість фаз", ""),
            f"{title} {details.get('Вхідна напруга', '')}",
        )
        connectors = _parse_connectors(details.get("Тип роз'ємів", ""))
        brand = _cell(row, idx, "Виробник") or None
        price_amount, _fallback_currency = _parse_price(_cell(row, idx, "Ціна"))
        currency = (_cell(row, idx, "Валюта") or _fallback_currency or "UAH").upper()
        description = _strip_html(_cell(row, idx, "Опис_укр") or _cell(row, idx, "Опис"))
        product_id = (
            _cell(row, idx, "Унікальний_ідентифікатор")
            or _cell(row, idx, "Ідентифікатор_товару")
            or _cell(row, idx, "Код_товару")
            or title
        )

        products.append(
            {
                "id": product_id,
                "title": title,
                "description": description[:400],
                "link": _cell(row, idx, "Продукт_на_сайті"),
                "image": _first_image(_cell(row, idx, "Посилання_зображення")),
                "availability": _availability(_cell(row, idx, "Наявність")),
                "brand": brand,
                "price": price_amount,
                "currency": currency,
                "kind": kind,
                "power_kw": power_kw,
                "power_bucket": _power_bucket(power_kw) if kind == "charger" else None,
                "current_a": current_a,
                "phases": phases,
                "connectors": connectors,
                "country": details.get("Країна виробник") or _cell(row, idx, "Країна_виробник") or None,
                "cable_cm": details.get("Довжина кабелю"),
                "product_type": _cell(row, idx, "Назва_групи") or "home-charger",
            }
        )

    products.sort(key=lambda p: (p["price"] is None, p["price"] or 0.0, p["title"]))

    brands = sorted({p["brand"] for p in products if p.get("brand")})
    connectors = sorted({c for p in products for c in (p.get("connectors") or [])})
    phases = sorted({p["phases"] for p in products if p.get("phases") in (1, 3)})
    kinds = sorted(
        {p["kind"] for p in products if p.get("kind")},
        key=lambda k: _KIND_ORDER.get(k, 9),
    )
    power_buckets = sorted(
        {
            p["power_bucket"]
            for p in products
            if p.get("kind") == "charger" and p.get("power_bucket")
        },
        key=lambda b: _POWER_BUCKET_ORDER.get(b, 9),
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
            "kinds": kinds,
            "power_buckets": power_buckets,
            "price_min": min(prices) if prices else None,
            "price_max": max(prices) if prices else None,
        },
    }


def _load_fallback_csv() -> str:
    if not _FALLBACK_CSV.is_file():
        raise FileNotFoundError(str(_FALLBACK_CSV))
    return _FALLBACK_CSV.read_text(encoding="utf-8-sig")


@router.get("")
async def list_home_chargers(refresh: bool = False) -> dict[str, Any]:
    """Return EV home chargers from the Sparks PROM Google Sheet (cached)."""
    ttl = max(60, int(settings.HOME_CHARGERS_CACHE_TTL_SEC))
    now = time.time()
    if (
        not refresh
        and _CACHE["payload"] is not None
        and (now - float(_CACHE["ts"])) < ttl
    ):
        return _CACHE["payload"]

    sheet_url = (settings.HOME_CHARGERS_FEED_URL or "").strip()
    csv_text = ""
    source_kind = "fallback"
    if sheet_url:
        try:
            csv_text = await _fetch_csv(sheet_url)
            source_kind = "sheet"
        except Exception as exc:
            logger.warning("home chargers live sheet failed, using snapshot: %s", exc)

    if not csv_text:
        try:
            csv_text = _load_fallback_csv()
            source_kind = "fallback"
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Home chargers feed is not configured") from exc

    try:
        payload = parse_prom_csv(csv_text)
    except (csv.Error, ValueError) as exc:
        logger.warning("home chargers catalog parse failed: %s", exc)
        raise HTTPException(status_code=502, detail="Invalid charger catalog feed") from exc

    if payload["count"] == 0 and source_kind == "sheet":
        try:
            payload = parse_prom_csv(_load_fallback_csv())
            source_kind = "fallback"
        except OSError:
            pass

    payload["cached"] = False
    payload["cache_ttl_sec"] = ttl
    payload["source_kind"] = source_kind
    _CACHE["payload"] = {**payload, "cached": True}
    _CACHE["ts"] = now
    return payload
