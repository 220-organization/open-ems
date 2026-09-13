"""Commercial DC EV chargers catalog — EDS Chargers retail price sheet."""

from __future__ import annotations

import csv
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

router = APIRouter(prefix="/api/commercial-chargers", tags=["commercial-chargers"])

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_SKU_RE = re.compile(r"^EDS-", re.I)
_FAMILY_RE = re.compile(r"^EDS-(QS|SPLIT|S|Q)(\d+)", re.I)
_FALLBACK_CSV = Path(__file__).resolve().parents[1] / "data" / "eds_commercial_chargers.csv"
_CATALOG_URL = "https://eds-chargers.com/en/products/"

# Official product photos from eds-chargers.com catalog (family → image).
_IMAGES: dict[str, str] = {
    "S80": "https://eds-chargers.com/wp-content/uploads/2025/10/s_80kw_04.png",
    "S120": "https://eds-chargers.com/wp-content/uploads/2025/10/s_120kw_01.png",
    "S160": "https://eds-chargers.com/wp-content/uploads/2025/10/s_160kw_01.png",
    "QS200": "https://eds-chargers.com/wp-content/uploads/2025/10/QS_200kW_05.png",
    "QS240": "https://eds-chargers.com/wp-content/uploads/2025/10/QS_240kW_03.png",
    "QS320": "https://eds-chargers.com/wp-content/uploads/2025/10/QS_320kW_04.png",
    "QS360": "https://eds-chargers.com/wp-content/uploads/2025/10/QS_360kW_04.png",
    "QS400": "https://eds-chargers.com/wp-content/uploads/2025/10/QS_400kW_05.png",
    "QS440": "https://eds-chargers.com/wp-content/uploads/2025/10/QS_440kW_03.png",
    "QS480": "https://eds-chargers.com/wp-content/uploads/2025/10/QS_480kW_05.png",
    "Q240": "https://eds-chargers.com/wp-content/uploads/2025/07/240kw_02-2.png",
    "Q320": "https://eds-chargers.com/wp-content/uploads/2025/10/320kw_11.png",
    "Q360": "https://eds-chargers.com/wp-content/uploads/2025/10/360kw_02.png",
    "Q400": "https://eds-chargers.com/wp-content/uploads/2025/10/400kw_11.png",
    "Q440": "https://eds-chargers.com/wp-content/uploads/2025/10/440kw_01.png",
    "Q480": "https://eds-chargers.com/wp-content/uploads/2025/10/480_kw_q-2.png",
    "SPLIT": "/static/commercial-chargers/split-hub.jpg",
    "DISPENSER": "/static/commercial-chargers/split-hub.jpg",
}

_LINKS: dict[str, str] = {
    "S80": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-s-80-kw/",
    "S120": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-s-120-kw/",
    "S160": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-s-160/",
    "QS200": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qsa-200-%d0%ba%d0%b2%d1%82/",
    "QS240": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qs-240-kw/",
    "QS320": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qsa-320-%d0%ba%d0%b2%d1%82/",
    "QS360": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qs-360-%d0%ba%d0%b2%d1%82/",
    "QS400": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qsa-400-kw/",
    "QS440": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qsa-440-%d0%ba%d0%b2%d1%82/",
    "QS480": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qs-480-%d0%ba%d0%b2%d1%82/",
    "Q240": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-q-240-kw/",
    "Q320": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qa-320-kw/",
    "Q360": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-q-360-kw/",
    "Q400": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qa-400-kw/",
    "Q440": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-qa-440-kw/",
    "Q480": "https://eds-chargers.com/en/products/fast-charging-station-eds-chargers-q-480-kw/",
}

_SERIES_FORM = {
    "S": "single",
    "QS": "single",
    "Q": "dual",
    "SPLIT": "split",
    "DISPENSER": "dispenser",
}

_POWER_BUCKET_ORDER = {
    "upto160": 0,
    "200to320": 1,
    "360to480": 2,
    "720plus": 3,
}

_PORT_ORDER = {
    "2dc": 0,
    "2dc_ac": 1,
    "2dc_2ac": 2,
    "3dc": 3,
    "4dc": 4,
}

# Comparison-shopping facets (not all values exist in the EDS sheet today).
_WARRANTY_YEARS = [1, 2, 3]
_WARRANTY_DOWNTIME = ["48h", "5d", "10d"]

# EDS Chargers SLA for the commercial catalog.
_EDS_SERVICE = {
    "warranty_years": 3,
    "warranty_downtime": "48h",
    "dedicated_manager": True,
    # Built to order: no local stock, shipment 2-3 months after the order.
    "lead_time": "2to3m",
}


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
        "User-Agent": "OpenEMS-CommercialChargers/1.0 (+https://220-km.com; price-list fetch)",
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
                    logger.warning(
                        "commercial chargers sheet HTTP %s for %s",
                        resp.status_code,
                        export,
                    )
                    continue
                text = resp.content.decode("utf-8-sig", errors="replace")
                if "<html" in text[:200].lower():
                    last_exc = RuntimeError(f"HTML response for {export}")
                    logger.warning("commercial chargers sheet got HTML for %s", export)
                    continue
                return text
            except Exception as exc:
                last_exc = exc
                logger.warning("commercial chargers sheet fetch failed for %s: %s", export, exc)
    assert last_exc is not None
    raise last_exc


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


def _normalize_series(raw: str) -> str:
    s = (raw or "").strip().upper()
    if s in _SERIES_FORM:
        return s
    return s


def _family_from_sku(sku: str, series: str) -> str:
    if series == "DISPENSER" or "DISPENSER" in (sku or "").upper():
        return "DISPENSER"
    m = _FAMILY_RE.match(sku or "")
    if m:
        return f"{m.group(1).upper()}{m.group(2)}"
    if series == "SPLIT":
        return "SPLIT"
    return series or "S"


def _connectors(title: str, config: str) -> list[str]:
    blob = f"{title} {config}".upper().replace("GB/T", "GBT")
    found: list[str] = []
    if "CCS" in blob:
        found.append("CCS2")
    if "GBT" in blob:
        found.append("GB/T")
    if "TYPE2" in blob or "TYPE 2" in blob or re.search(r"\+2?AC\b", blob):
        found.append("Type 2")
    if not found and "2 DC" in blob:
        found.extend(["CCS2", "GB/T"])
    return list(dict.fromkeys(found))


def _ports(config: str, title: str) -> Optional[str]:
    """Port layout for filters: 2 DC, 2 DC+AC, 2 DC+2 AC, 3 DC, 4 DC."""
    blob = f"{config} {title}".upper().replace(" ", "")
    if "2DC+2AC" in blob or "2DC+AC+AC" in blob:
        return "2dc_2ac"
    if "2DC+AC" in blob:
        return "2dc_ac"
    if "4DC" in blob:
        return "4dc"
    if "3DC" in blob:
        return "3dc"
    if "2DC" in blob or "2DC" in (config or "").upper().replace(" ", ""):
        return "2dc"
    if re.search(r"2\s*DC", f"{config} {title}", re.I):
        return "2dc"
    return None


def _cooling(series: str, config: str, title: str) -> Optional[str]:
    blob = f"{config} {title}".lower()
    if "рідин" in blob or "жидк" in blob or "liquid" in blob:
        return "liquid"
    if "повітр" in blob or "воздуш" in blob or "air" in blob:
        return "air"
    if series != "SPLIT" and "DISPENSER" not in series:
        return None
    if "700" in blob or "600" in blob:
        return "liquid"
    if "500" in blob:
        return "air"
    return None


def _power_bucket(kw: Optional[float], series: str) -> str:
    # Dispensers are sold with split HPC. 720 kW+ is always a split system.
    if series == "DISPENSER" or kw is None:
        return "720plus"
    if kw <= 160:
        return "upto160"
    if kw <= 320:
        return "200to320"
    if kw <= 480:
        return "360to480"
    return "720plus"


def _image_for(family: str, series: str) -> str:
    if family in _IMAGES:
        return _IMAGES[family]
    if series in _IMAGES:
        return _IMAGES[series]
    return _IMAGES.get("QS240", "")


def _link_for(family: str) -> str:
    return _LINKS.get(family, _CATALOG_URL)


def _find_sku(cols: list[str]) -> Optional[str]:
    for cell in cols:
        s = (cell or "").strip()
        if _SKU_RE.match(s):
            return s
    return None


def parse_eds_price_csv(csv_text: str) -> dict[str, Any]:
    """Parse EDS retail CSV into catalog products + filter facets."""
    reader = csv.reader(io.StringIO(csv_text or ""))
    products: list[dict[str, Any]] = []
    notes: list[str] = []

    for raw in reader:
        cols = [(c or "").strip() for c in raw]
        if not any(cols):
            continue
        joined = " ".join(cols)
        if joined.startswith("*"):
            notes.append(joined)
            continue
        sku = _find_sku(cols)
        if not sku:
            continue
        # Positional: №, title, series, kW, config, sku, price
        title = cols[1] if len(cols) > 1 else sku
        series = _normalize_series(cols[2] if len(cols) > 2 else "")
        if not series:
            if "DISPENSER" in sku.upper():
                series = "DISPENSER"
            elif "SPLIT" in sku.upper():
                series = "SPLIT"
            elif sku.upper().startswith("EDS-QS"):
                series = "QS"
            elif sku.upper().startswith("EDS-Q"):
                series = "Q"
            else:
                series = "S"
        power_kw = _parse_number(cols[3] if len(cols) > 3 else "")
        config = cols[4] if len(cols) > 4 else ""
        price = _parse_number(cols[6] if len(cols) > 6 else "")
        if price is None:
            continue
        family = _family_from_sku(sku, series)
        products.append(
            {
                "id": sku,
                "sku": sku,
                "title": title,
                "brand": "EDS Chargers",
                "series": series,
                "family": family,
                "form": _SERIES_FORM.get(series, "single"),
                "config": config,
                "power_kw": power_kw,
                "power_bucket": _power_bucket(power_kw, series),
                "connectors": _connectors(title, config),
                "ports": _ports(config, title),
                "cooling": _cooling(series, config, title),
                "warranty_years": _EDS_SERVICE["warranty_years"],
                "warranty_downtime": _EDS_SERVICE["warranty_downtime"],
                "dedicated_manager": _EDS_SERVICE["dedicated_manager"],
                "lead_time": _EDS_SERVICE["lead_time"],
                "price": price,
                "currency": "EUR",
                "image": _image_for(family, series),
                "link": _link_for(family),
            }
        )

    products.sort(key=lambda p: (p["price"] is None, p["price"] or 0.0, p["title"]))

    series = sorted(
        {p["series"] for p in products if p.get("series")},
        key=lambda s: {"S": 0, "QS": 1, "Q": 2, "SPLIT": 3, "DISPENSER": 4}.get(s, 9),
    )
    connectors = sorted({c for p in products for c in (p.get("connectors") or [])})
    ports = sorted(
        {p["ports"] for p in products if p.get("ports")},
        key=lambda x: _PORT_ORDER.get(x, 9),
    )
    cooling = sorted({p["cooling"] for p in products if p.get("cooling")})
    power_buckets = sorted(
        {p["power_bucket"] for p in products if p.get("power_bucket")},
        key=lambda b: _POWER_BUCKET_ORDER.get(b, 9),
    )
    prices = [p["price"] for p in products if p.get("price") is not None]

    return {
        "source": "eds-chargers.com",
        "count": len(products),
        "products": products,
        "notes": notes,
        "facets": {
            "series": series,
            "connectors": connectors,
            "ports": ports,
            "cooling": cooling,
            "power_buckets": power_buckets,
            "warranty_years": list(_WARRANTY_YEARS),
            "warranty_downtime": list(_WARRANTY_DOWNTIME),
            "dedicated_manager": [True, False],
            "price_min": min(prices) if prices else None,
            "price_max": max(prices) if prices else None,
        },
    }


def _load_fallback_csv() -> str:
    if not _FALLBACK_CSV.is_file():
        raise FileNotFoundError(str(_FALLBACK_CSV))
    return _FALLBACK_CSV.read_text(encoding="utf-8-sig")


@router.get("")
async def list_commercial_chargers(refresh: bool = False) -> dict[str, Any]:
    """Return EDS commercial DC chargers from the retail Google Sheet (cached)."""
    ttl = max(60, int(settings.COMMERCIAL_CHARGERS_CACHE_TTL_SEC))
    now = time.time()
    if (
        not refresh
        and _CACHE["payload"] is not None
        and (now - float(_CACHE["ts"])) < ttl
    ):
        return _CACHE["payload"]

    sheet_url = (settings.COMMERCIAL_CHARGERS_SHEET_URL or "").strip()
    csv_text = ""
    source_kind = "fallback"
    if sheet_url:
        try:
            csv_text = await _fetch_csv(sheet_url)
            source_kind = "sheet"
        except Exception as exc:
            logger.warning("commercial chargers live sheet failed, using snapshot: %s", exc)

    if not csv_text:
        try:
            csv_text = _load_fallback_csv()
            source_kind = "fallback"
        except OSError as exc:
            raise HTTPException(
                status_code=503, detail="Commercial charger catalog is not configured"
            ) from exc

    try:
        payload = parse_eds_price_csv(csv_text)
    except (csv.Error, ValueError) as exc:
        logger.warning("commercial chargers parse failed: %s", exc)
        raise HTTPException(status_code=502, detail="Invalid commercial charger catalog") from exc

    if payload["count"] == 0 and source_kind == "sheet":
        try:
            payload = parse_eds_price_csv(_load_fallback_csv())
            source_kind = "fallback"
        except OSError:
            pass

    payload["cached"] = False
    payload["cache_ttl_sec"] = ttl
    payload["source_kind"] = source_kind
    _CACHE["payload"] = {**payload, "cached": True}
    _CACHE["ts"] = now
    return payload
