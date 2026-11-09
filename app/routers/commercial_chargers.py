"""Commercial DC EV chargers catalog — EDS Chargers retail price sheet."""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException

from app import settings
from app.nbu_fx_service import fetch_usd_uah_rate_for_date

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/commercial-chargers", tags=["commercial-chargers"])

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_SKU_RE = re.compile(r"^EDS-", re.I)
_FAMILY_RE = re.compile(r"^EDS-(QS|SPLIT|S|Q)(\d+)", re.I)
_FALLBACK_CSV = Path(__file__).resolve().parents[1] / "data" / "eds_commercial_chargers.csv"
_UGV_CSV = Path(__file__).resolve().parents[1] / "data" / "ugv_commercial_chargers.csv"
_EPORT_CSV = Path(__file__).resolve().parents[1] / "data" / "eport_commercial_chargers.csv"
_CATALOG_URL = "https://eds-chargers.com/en/products/"
_UGV_CATALOG_URL = "https://ugv.ua"
_UGV_IMAGE = "/static/commercial-chargers/ugv-front.png"
_EPORT_CATALOG_URL = "https://e-port.energy"

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
    "1dc": 0,
    "2dc": 1,
    "2dc_ac": 2,
    "2dc_2ac": 3,
    "3dc": 4,
    "4dc": 5,
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

# UGV Chargers SLA (datasheet: 24-month warranty; other terms match EDS catalog UX).
_UGV_SERVICE = {
    "warranty_years": 2,
    "warranty_downtime": "48h",
    "dedicated_manager": True,
    "lead_time": "2to3m",
}

_BRAND_ORDER = {
    "EDS Chargers": 0,
    "UGV Chargers": 1,
    "E-port": 2,
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


def _ports_from_dc_count(count: Optional[float]) -> Optional[str]:
    if count is None:
        return None
    n = int(count)
    if n == 2:
        return "2dc"
    if n == 3:
        return "3dc"
    if n == 4:
        return "4dc"
    return None


def _connectors_from_csv(raw: str) -> list[str]:
    """Split a connectors cell like ``CCS2+GB/T+Type2`` into unique labels."""
    out: list[str] = []
    for part in re.split(r"[+|]", raw or ""):
        s = part.strip()
        if not s:
            continue
        key = s.upper().replace(" ", "")
        if key in ("CCS", "CCS2"):
            label = "CCS2"
        elif key in ("GBT", "GB/T", "GB\\T"):
            label = "GB/T"
        elif key in ("CHADEMO",):
            label = "CHAdeMO"
        elif key in ("NACS",):
            label = "NACS"
        elif key in ("TYPE2", "TYPE 2", "T22"):
            label = "Type 2"
        else:
            label = s
        if label not in out:
            out.append(label)
    return out


def _connectors_from_ugv_sku(sku: str) -> list[str]:
    """Infer connectors from UGV SKU letters: H=CHAdeMO, C=CCS2, G=GB/T, N=NACS, T22=Type2."""
    # Drop brand/power prefix and trailing options so we only scan port codes.
    body = re.sub(r"^UGV-A\d+[A-Z]*-?", "", (sku or ""), flags=re.I)
    body = re.sub(r"-D-RMH.*$", "", body, flags=re.I)
    # Normalize Cyrillic С (U+0421) used in some SKUs to Latin C.
    body = body.replace("С", "C").replace("с", "C")
    found: list[str] = []
    if re.search(r"H\d+", body, re.I):
        found.append("CHAdeMO")
    # Count CCS codes: C320, C240, … but not the CG/DG cabinet letters already stripped.
    ccs_hits = len(re.findall(r"C\d+", body, re.I))
    for _ in range(max(ccs_hits, 1 if re.search(r"C\d+", body, re.I) else 0)):
        if "CCS2" not in found:
            found.append("CCS2")
            break
    if re.search(r"G\d+", body, re.I):
        found.append("GB/T")
    if re.search(r"N\d+", body, re.I):
        found.append("NACS")
    if re.search(r"T22", body, re.I):
        found.append("Type 2")
    return found


def _build_facets(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Build filter facets over a merged commercial-charger product list."""
    series = sorted(
        {p["series"] for p in products if p.get("series")},
        key=lambda s: {"S": 0, "QS": 1, "Q": 2, "SPLIT": 3, "DISPENSER": 4, "UGV": 5}.get(
            s, 9
        ),
    )
    brands = sorted(
        {p["brand"] for p in products if p.get("brand")},
        key=lambda b: _BRAND_ORDER.get(b, 9),
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
        "brands": brands,
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
    }


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
    return {
        "source": "eds-chargers.com",
        "count": len(products),
        "products": products,
        "notes": notes,
        "facets": _build_facets(products),
    }


def parse_ugv_csv(csv_text: str) -> dict[str, Any]:
    """Parse the static UGV DC price snapshot into catalog products."""
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    products: list[dict[str, Any]] = []
    for row in reader:
        sku = (row.get("sku") or "").strip()
        if not sku:
            continue
        power_kw = _parse_number(row.get("power_kw"))
        price = _parse_number(row.get("price_eur_vat"))
        if price is None:
            continue
        dc_ports = _parse_number(row.get("dc_ports"))
        connectors = _connectors_from_csv(row.get("connectors") or "")
        if not connectors:
            connectors = _connectors_from_ugv_sku(sku)
        title = (row.get("title") or "").strip() or sku
        family = f"UGV{int(power_kw)}" if power_kw is not None else "UGV"
        products.append(
            {
                "id": sku,
                "sku": sku,
                "title": title,
                "brand": "UGV Chargers",
                "series": "UGV",
                "family": family,
                "form": "single",
                "config": f"{int(dc_ports)}DC" if dc_ports is not None else "",
                "power_kw": power_kw,
                "power_bucket": _power_bucket(power_kw, "UGV"),
                "connectors": connectors,
                "ports": _ports_from_dc_count(dc_ports),
                "cooling": None,
                "warranty_years": _UGV_SERVICE["warranty_years"],
                "warranty_downtime": _UGV_SERVICE["warranty_downtime"],
                "dedicated_manager": _UGV_SERVICE["dedicated_manager"],
                "lead_time": _UGV_SERVICE["lead_time"],
                "price": price,
                "currency": "EUR",
                "image": _UGV_IMAGE,
                "link": _UGV_CATALOG_URL,
            }
        )
    products.sort(key=lambda p: (p["price"] is None, p["price"] or 0.0, p["title"]))
    return {
        "source": "ugv.ua",
        "count": len(products),
        "products": products,
        "notes": [],
        "facets": _build_facets(products),
    }


def eport_lead_time(kw: Optional[float]) -> str:
    """E-port SLA: in stock below 120 kW, 2 months at 120 kW+."""
    if kw is not None and kw >= 120:
        return "2m"
    return "now"


def _eport_connectors(raw: str) -> list[str]:
    """Parse connector cell like ``CCS2+GB/T`` or ``GB/T`` into unique labels."""
    out: list[str] = []
    for part in re.split(r"[+|]", raw or ""):
        s = part.strip()
        if not s:
            continue
        key = s.upper().replace(" ", "")
        if key in ("CCS", "CCS2"):
            label = "CCS2"
        elif key in ("CCS1",):
            label = "CCS1"
        elif key in ("GBT", "GB/T", "GB\\T"):
            label = "GB/T"
        elif key in ("CHADEMO",):
            label = "CHAdeMO"
        elif key in ("NACS", "TESLA"):
            label = "NACS"
        else:
            label = s
        if label not in out:
            out.append(label)
    return out


def parse_eport_dc_csv(csv_text: str) -> dict[str, Any]:
    """Parse the static E-port/EPG DC charger snapshot (UAH retail prices)."""
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    products: list[dict[str, Any]] = []
    for row in reader:
        sku = (row.get("sku") or "").strip()
        title = (row.get("title") or "").strip() or sku
        if not sku:
            continue
        power_kw = _parse_number(row.get("power_kw"))
        price = _parse_number(row.get("price_uah"))
        if price is None:
            continue
        connectors = _eport_connectors(row.get("connector") or "")
        line_brand = (row.get("brand") or "").strip()
        image = (row.get("image") or "").strip()
        form = (row.get("form") or "single").strip() or "single"
        ports_raw = (row.get("ports") or "").strip()
        if ports_raw in _PORT_ORDER:
            ports = ports_raw
        elif form == "split":
            ports = None
        elif len(connectors) >= 2:
            ports = "2dc"
        elif connectors:
            ports = "1dc"
        else:
            ports = None
        # Bucket by kW; use SPLIT/DISPENSER series only when form matches and kW unknown.
        bucket_series = "UGV"
        if form == "split":
            bucket_series = "SPLIT"
        elif form == "dispenser" and power_kw is None:
            bucket_series = "DISPENSER"
        family = f"EPORT{int(power_kw)}" if power_kw is not None else "EPORT"
        config = (
            f"{len(connectors)}DC"
            if connectors
            else ("SPLIT" if form == "split" else "")
        )
        products.append(
            {
                "id": sku,
                "sku": sku,
                "title": title,
                "brand": "E-port",
                "series": line_brand or "E-port",
                "family": family,
                "form": form,
                "config": config,
                "power_kw": power_kw,
                "power_bucket": _power_bucket(power_kw, bucket_series),
                "connectors": connectors,
                "ports": ports,
                "cooling": None,
                "warranty_years": None,
                "warranty_downtime": None,
                "dedicated_manager": None,
                "lead_time": eport_lead_time(power_kw),
                "price": price,
                "currency": "UAH",
                "image": image,
                "link": _EPORT_CATALOG_URL,
            }
        )
    products.sort(key=lambda p: (p["price"] is None, p["price"] or 0.0, p["title"]))
    return {
        "source": "e-port.energy",
        "count": len(products),
        "products": products,
        "notes": [],
        "facets": _build_facets(products),
    }


def _load_fallback_csv() -> str:
    if not _FALLBACK_CSV.is_file():
        raise FileNotFoundError(str(_FALLBACK_CSV))
    return _FALLBACK_CSV.read_text(encoding="utf-8-sig")


def _load_ugv_csv() -> str:
    if not _UGV_CSV.is_file():
        raise FileNotFoundError(str(_UGV_CSV))
    return _UGV_CSV.read_text(encoding="utf-8-sig")


def _load_eport_csv() -> str:
    if not _EPORT_CSV.is_file():
        raise FileNotFoundError(str(_EPORT_CSV))
    return _EPORT_CSV.read_text(encoding="utf-8-sig")


def _merge_catalog(*parts: dict[str, Any]) -> dict[str, Any]:
    products: list[dict[str, Any]] = []
    notes: list[str] = []
    sources: list[str] = []
    for part in parts:
        products.extend(part.get("products") or [])
        notes.extend(part.get("notes") or [])
        src = part.get("source")
        if src:
            sources.append(str(src))
    products.sort(key=lambda p: (p["price"] is None, p["price"] or 0.0, p["title"]))
    return {
        "source": "+".join(sources) if sources else "commercial-chargers",
        "count": len(products),
        "products": products,
        "notes": notes,
        "facets": _build_facets(products),
    }


def eport_prices_to_usd(
    payload: dict[str, Any], usd_uah: Optional[float]
) -> dict[str, Any]:
    """Convert E-port UAH retail prices to USD with today's NBU UAH/USD rate."""
    if not usd_uah or usd_uah <= 0:
        return payload
    products: list[dict[str, Any]] = []
    for p in payload.get("products") or []:
        q = dict(p)
        if (q.get("currency") or "").upper() == "UAH" and q.get("price") is not None:
            uah = float(q["price"])
            q["price_uah"] = uah
            q["price"] = round(uah / float(usd_uah), 2)
            q["currency"] = "USD"
            q["fx_usd_uah"] = float(usd_uah)
        products.append(q)
    out = dict(payload)
    out["products"] = products
    out["count"] = len(products)
    out["facets"] = _build_facets(products)
    out["fx_usd_uah"] = float(usd_uah)
    return out


@router.get("")
async def list_commercial_chargers(refresh: bool = False) -> dict[str, Any]:
    """Return EDS + UGV + E-port commercial DC chargers (cached)."""
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
        eds_payload = parse_eds_price_csv(csv_text)
    except (csv.Error, ValueError) as exc:
        logger.warning("commercial chargers parse failed: %s", exc)
        raise HTTPException(status_code=502, detail="Invalid commercial charger catalog") from exc

    if eds_payload["count"] == 0 and source_kind == "sheet":
        try:
            eds_payload = parse_eds_price_csv(_load_fallback_csv())
            source_kind = "fallback"
        except OSError:
            pass

    try:
        ugv_payload = parse_ugv_csv(_load_ugv_csv())
    except (OSError, csv.Error, ValueError) as exc:
        logger.warning("UGV commercial chargers snapshot missing/invalid: %s", exc)
        ugv_payload = {"source": "ugv.ua", "count": 0, "products": [], "notes": [], "facets": {}}

    try:
        eport_payload = parse_eport_dc_csv(_load_eport_csv())
    except (OSError, csv.Error, ValueError) as exc:
        logger.warning("E-port commercial chargers snapshot missing/invalid: %s", exc)
        eport_payload = {
            "source": "e-port.energy",
            "count": 0,
            "products": [],
            "notes": [],
            "facets": {},
        }

    usd_uah: Optional[float] = None
    try:
        usd_uah = await fetch_usd_uah_rate_for_date(date.today())
    except Exception as exc:
        logger.warning("NBU USD/UAH for E-port prices failed: %s", exc)
    if usd_uah:
        eport_payload = eport_prices_to_usd(eport_payload, usd_uah)
    else:
        logger.warning("E-port prices left in UAH — NBU USD rate unavailable")

    payload = _merge_catalog(eds_payload, ugv_payload, eport_payload)
    payload["cached"] = False
    payload["cache_ttl_sec"] = ttl
    payload["source_kind"] = source_kind
    if usd_uah:
        payload["fx_usd_uah"] = usd_uah
    _CACHE["payload"] = {**payload, "cached": True}
    _CACHE["ts"] = now
    return payload
