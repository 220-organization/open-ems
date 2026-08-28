"""Order BESS — BIOM + Energotrendy Ukrainy price lists from Google Sheets + leads."""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.db import get_db
from app.models import BessDiscountRequest
from app.telegram_notify import format_bess_lead_message, send_telegram_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bess-order", tags=["bess-order"])

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_MEMORY_LEADS: list[dict[str, Any]] = []

ALLOWED_UNITS_MIN = 2
ALLOWED_UNITS_MAX = 220
ALLOWED_BUSINESS = frozenset({"fop", "vat", "cash"})

_FX_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*грн", re.IGNORECASE)
_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_UA_VAT = 1.20
_ETU_AVAIL = "5–10 днів з Нідерландів (Енерготренди)"
# Lookalike Cyrillic → Latin so SE-F16-С matches SE-F16-C.
_CYR_TO_LAT = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "Х": "X",
        "І": "I",
        "а": "A",
        "е": "E",
        "о": "O",
        "с": "C",
        "і": "I",
    }
)
# BOM / custom-builder articles used on /order-bess (must stay in sync with ui presets).
_CANONICAL_ARTICLES = (
    "SUN-5K-SG05LP1-EU-AM2-P",
    "SUN-6K-SG05LP1-EU",
    "SUN-6K-SG05LP1-EU-AM2-P",
    "SUN-8K-SG05LP1-EU",
    "SUN-10K-SG02LP1-EU-AM3",
    "SUN-12K-SG02LP1-EU",
    "SUN-12K-SG05LP3-EU",
    "SUN-15K-SG05LP3-EU",
    "SUN-16K-SG02LP1-EU-AM3",
    "SUN-20K-SG05LP3-EU",
    "SUN-20K-SG01HP3-EU-AM2",
    "SUN-25K-SG01HP3-EU-AM2",
    "SUN-30K-SG02HP3-EU-AM3",
    "SUN-50K-SG01HP3-EU-BM4",
    "SUN-80K-SG02HP3-EU-EM6",
    "SUN-125K-SG02HP3-EU-EM10",
    "SE-G5.1-PRO-B",
    "SE-F5-PRO-C",
    "SE-F12-C",
    "SE-F12-MAX",
    "SE-F16-C",
    "SE-F16-MAX",
    "BOS-G-Pack5.1",
    "BOS-G-PDU-2",
    "3U-HRACK (BOS G PRO)",
    "HV BOS-B-Pack16-A3-Pro",
    "BOS-B-PDU-2-A-Pro",
    "BALFP-512100-V1",
    "BALFP-512200-V1",
    "BALFP-512314-V2",
    "BAHV-100512-LFP",
    "BAHV-314512-LFP",
    "CB-HV-100",
    "CB-HV-160",
    "MB-HV-1",
    "MB-HV-3",
    "PC-HV-3-3.2m",
)
# sku_key → canonical article (ETU / BIOM spelling variants).
_ARTICLE_ALIASES = {
    "SUN8KSG05LP1EUAM2P": "SUN-8K-SG05LP1-EU",
    "SUN12KSG02LP1EUAM3": "SUN-12K-SG02LP1-EU",
    "SUN15KSG05LP3EUSM2": "SUN-15K-SG05LP3-EU",
    "SUN20KSG05LP3EUSM2": "SUN-20K-SG05LP3-EU",
    "SUN80KSG02HP3EUEM6BM4": "SUN-80K-SG02HP3-EU-EM6",
    "SUN125KSG02HP3EUEM10BM4": "SUN-125K-SG02HP3-EU-EM10",
    "SEG51PROB": "SE-G5.1-PRO-B",
    "SEG5.1PROB": "SE-G5.1-PRO-B",
    "SEF5PROC": "SE-F5-PRO-C",
    "SEF16C": "SE-F16-C",
    "SEF16MAX": "SE-F16-MAX",
    "SEF12C": "SE-F12-C",
    "SEF12MAX": "SE-F12-MAX",
    "BOSGPACK51PRO": "BOS-G-Pack5.1",
    "BOSGPACK5.1PRO": "BOS-G-Pack5.1",
    "BOSGPROPACK51": "BOS-G-Pack5.1",
    "BOSGPROPACK5.1": "BOS-G-Pack5.1",
    "BOSGPROPDU2": "BOS-G-PDU-2",
    "BOSGPDU2": "BOS-G-PDU-2",
    "3UHRACKBOSGPRO": "3U-HRACK (BOS G PRO)",
    "HVBOSBPACK16A3PRO": "HV BOS-B-Pack16-A3-Pro",
    "BOSBPACK16A3PRO": "HV BOS-B-Pack16-A3-Pro",
}


def _to_csv_export_url(url: str) -> str:
    """Accept edit or export Google Sheets URL; return CSV export URL.

    Prefer the gviz CSV endpoint — ``/export?format=csv&gid=0`` often 400s when
    the first tab is not gid=0. Only pass ``gid`` when the source URL has one.
    """
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
    # Also support hash fragments like #gid=123
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
    """Build ordered list of CSV URLs to try for a sheet link."""
    primary = _to_csv_export_url(url)
    out = [primary]
    m = _SHEET_ID_RE.search(url or "")
    if not m:
        return out
    sheet_id = m.group(1)
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    frag = parse_qs((parsed.fragment or "").replace("?", "&"))
    gid = (qs.get("gid") or frag.get("gid") or [None])[0]
    candidates = [
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv",
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv",
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
        "User-Agent": "OpenEMS-BESS/1.0 (+https://220-km.com; price-list fetch)",
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
                    logger.warning("BESS sheet fetch HTTP %s for %s", resp.status_code, export)
                    continue
                text = resp.content.decode("utf-8-sig", errors="replace")
                # Google may return an HTML login / error page with 200
                if "<html" in text[:200].lower():
                    last_exc = RuntimeError(f"HTML response for {export}")
                    logger.warning("BESS sheet fetch got HTML for %s", export)
                    continue
                return text
            except Exception as exc:
                last_exc = exc
                logger.warning("BESS sheet fetch failed for %s: %s", export, exc)
    assert last_exc is not None
    raise last_exc


def _parse_number(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace("\xa0", " ").replace(" ", "")
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").replace("\n", " ").strip().lower())


def _find_col(headers: list[str], *needles: str, allow_contains: bool = True) -> Optional[int]:
    norms = [_norm_header(h) for h in headers]
    for needle in needles:
        n = _norm_header(needle)
        for i, h in enumerate(norms):
            if n == h:
                return i
    if not allow_contains:
        return None
    for needle in needles:
        n = _norm_header(needle)
        for i, h in enumerate(norms):
            # Avoid «Тип» matching «Тип акумуляторів»
            if h.startswith(n + " ") or h.startswith(n + "("):
                return i
            if n in h and n != "тип":
                return i
    return None


def _find_col_exact(headers: list[str], *needles: str) -> Optional[int]:
    return _find_col(headers, *needles, allow_contains=False)


def _infer_brand(article: str, section_brand: Optional[str]) -> str:
    if section_brand in ("deye", "biom"):
        return section_brand
    a = (article or "").upper().replace(" ", "")
    if a.startswith(("SUN-", "SE-", "BOS-", "3U-", "HV BOS", "HVBOS")):
        return "deye"
    if a.startswith(("BALFP", "BAHV", "CB-HV", "MB-HV", "PC-HV", "CS-", "MPP-")):
        return "biom"
    if "DEYE" in a:
        return "deye"
    if "BIOM" in a or "BAHV" in a:
        return "biom"
    return "other"


def _update_section_brand(cell: str, current: Optional[str]) -> Optional[str]:
    s = (cell or "").upper()
    if "ПРОДУКЦІЯ DEYE" in s or "PRODUCTS DEYE" in s or s.strip() == "DEYE":
        return "deye"
    if "BIOM PROFESSIONAL" in s or "АКУМУЛЯТОРНІ БАТАРЕЇ BIOM" in s:
        return "biom"
    if "ПРОДУКЦІЯ JIKONG" in s:
        return "other"
    return current


def _clean_article(raw: str) -> str:
    """Normalize a model cell from ETU / BIOM into a comparable article string."""
    s = str(raw or "").translate(_CYR_TO_LAT).replace("\xa0", " ")
    s = re.sub(r"[\r\n]+", "-", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(DEYE|DYNESS|MARSTEK)\s+", "", s, flags=re.I)
    return s.strip(" -")


def _sku_key(article: str) -> str:
    return re.sub(r"[^A-Z0-9.]", "", _clean_article(article).upper())


def _canonical_article(raw: str) -> str:
    """Map ETU / BIOM spelling to the BOM article used by the order-bess UI."""
    cleaned = _clean_article(raw)
    if not cleaned:
        return ""
    key = _sku_key(cleaned)
    if key in _ARTICLE_ALIASES:
        return _ARTICLE_ALIASES[key]
    best = ""
    best_len = 0
    for canon in _CANONICAL_ARTICLES:
        ck = _sku_key(canon)
        if not ck:
            continue
        if key == ck:
            return canon
        if (key.startswith(ck) or ck.startswith(key)) and min(len(key), len(ck)) >= 8:
            n = min(len(key), len(ck))
            if n > best_len:
                best = canon
                best_len = n
    return best or cleaned


def _uah_to_usd(uah: Optional[float], fx: float) -> Optional[float]:
    if uah is None or uah <= 0:
        return None
    rate = fx if fx and fx > 0 else 45.3
    return round(uah / rate, 2)


def _looks_like_sku(article: str) -> bool:
    a = _clean_article(article).upper()
    if not a or len(a) < 4:
        return False
    return bool(
        re.search(
            r"(SUN-|SE-|BOS-|STACK|DYNESS|MARSTEK|VENUS|GE-F|3U-HRACK|DH200)",
            a,
        )
    )


def _parse_etu_sheet_csv(text: str) -> dict[str, dict[str, Any]]:
    """Parse Energotrendy Ukrainy UAH price list (model + prepaid / TOV columns)."""
    items: dict[str, dict[str, Any]] = {}
    reader = csv.reader(io.StringIO(text or ""))
    headers: Optional[list[str]] = None

    for row in reader:
        if not row or all(not str(c).strip() for c in row):
            continue
        norms_joined = " ".join(_norm_header(c) for c in row)
        if headers is None and "модель" in norms_joined and "ціна" in norms_joined:
            headers = [str(c or "") for c in row]
            continue
        if headers is None:
            continue

        model_i = _find_col(headers, "Модель")
        desc_i = _find_col(headers, "Опис")
        cap_i = _find_col(headers, "Потужність/ємність", "Потужність")
        brand_i = 1 if len(headers) > 1 else None
        norms = [_norm_header(h) for h in headers]
        prepaid_i = None
        tov_i = None
        for i, h in enumerate(norms):
            if prepaid_i is None and "передплата" in h:
                prepaid_i = i
            # «тов» also appears inside «гарантована» — require a token, not a substring.
            if tov_i is None and re.search(r"(^|[\s,])тов([\s,]|$)", h):
                tov_i = i
        if prepaid_i is None:
            for i, h in enumerate(norms):
                if "ціна" in h and "грн" in h and "тов" not in h.split() and "пдв" not in h:
                    prepaid_i = i
                    break

        if model_i is None or model_i >= len(row):
            continue
        article_raw = str(row[model_i] or "").strip()
        if not _looks_like_sku(article_raw):
            continue
        article = _canonical_article(article_raw)
        if not article:
            continue

        prepaid = (
            _parse_number(row[prepaid_i]) if prepaid_i is not None and prepaid_i < len(row) else None
        )
        tov = _parse_number(row[tov_i]) if tov_i is not None and tov_i < len(row) else None
        if (prepaid is None or prepaid <= 0) and (tov is None or tov <= 0):
            continue

        desc = str(row[desc_i] or "").strip() if desc_i is not None and desc_i < len(row) else ""
        cap = str(row[cap_i] or "").strip() if cap_i is not None and cap_i < len(row) else ""
        brand_cell = (
            str(row[brand_i] or "").strip() if brand_i is not None and brand_i < len(row) else ""
        )
        brand_l = brand_cell.lower()
        if "deye" in brand_l:
            brand = "deye"
        elif "dyness" in brand_l:
            brand = "dyness"
        elif "marstek" in brand_l:
            brand = "other"
        else:
            brand = _infer_brand(article, None)

        name = desc or article
        if cap and not desc:
            name = f"{article}, {cap}"

        key = _sku_key(article) or article.upper().replace(" ", "")
        items[key] = {
            "article": article,
            "articleRaw": _clean_article(article_raw),
            "name": name,
            "brand": brand,
            "prepaidUah": prepaid if prepaid and prepaid > 0 else None,
            "tovUah": tov if tov and tov > 0 else None,
            "availability": _ETU_AVAIL,
        }
        raw_key = _sku_key(article_raw)
        if raw_key and raw_key not in items:
            items[raw_key] = items[key]
    return items


def _fill_missing_vat(by_article: dict[str, dict[str, Any]]) -> None:
    for row in by_article.values():
        if row.get("retailVatUsd") is None and row.get("retailUsd") is not None:
            try:
                row["retailVatUsd"] = round(float(row["retailUsd"]) * _UA_VAT, 2)
            except (TypeError, ValueError):
                continue


def _merge_etu_items(
    by_article: dict[str, dict[str, Any]],
    etu_items: dict[str, dict[str, Any]],
    fx: float,
) -> None:
    """Overlay ETU UAH prices (converted to USD). Fill gaps; prefer ETU when cheaper."""
    seen: set[int] = set()
    for row in etu_items.values():
        ident = id(row)
        if ident in seen:
            continue
        seen.add(ident)
        article = _canonical_article(row.get("article") or "")
        if not article:
            continue
        list_key = article.upper().replace(" ", "")
        cash_usd = _uah_to_usd(row.get("prepaidUah"), fx)
        fop_usd = _uah_to_usd(row.get("tovUah"), fx)
        vat_usd = round(fop_usd * _UA_VAT, 2) if fop_usd is not None else None
        existing = by_article.get(list_key)
        if existing is None:
            by_article[list_key] = {
                "code": "",
                "article": article,
                "name": row.get("name") or article,
                "brand": row.get("brand") or "other",
                "promoUsd": None,
                "promoVatUsd": None,
                "installerUsd": cash_usd,
                "installerCheapestUsd": cash_usd,
                "retailUsd": fop_usd,
                "retailVatUsd": vat_usd,
                "availability": row.get("availability") or "",
                "availabilityInstaller": row.get("availability") or "",
                "priceSourceCash": "etu" if cash_usd is not None else None,
                "priceSourceRetail": "etu" if fop_usd is not None else None,
            }
            continue

        biom_cash = existing.get("installerCheapestUsd")
        if biom_cash is None:
            biom_cash = existing.get("installerUsd")
        if cash_usd is not None and (biom_cash is None or cash_usd < float(biom_cash)):
            existing["installerUsd"] = cash_usd
            existing["installerCheapestUsd"] = cash_usd
            existing["availabilityInstaller"] = row.get("availability") or existing.get(
                "availabilityInstaller"
            )
            existing["priceSourceCash"] = "etu"
        biom_retail = existing.get("retailUsd")
        if fop_usd is not None and (biom_retail is None or fop_usd < float(biom_retail)):
            existing["retailUsd"] = fop_usd
            if vat_usd is not None:
                existing["retailVatUsd"] = vat_usd
            existing["priceSourceRetail"] = "etu"
        elif existing.get("retailVatUsd") is None and vat_usd is not None:
            existing["retailVatUsd"] = vat_usd


def _parse_sheet_csv(text: str, *, kind: str) -> tuple[float, dict[str, dict[str, Any]]]:
    """
    Parse BIOM price CSV.
    kind: 'promo' → promoUsd / promoVatUsd / availability
          'install' → installerUsd / installerCheapestUsd / retailUsd / retailVatUsd /
                      availabilityInstaller
    Returns (fx_rate, items_by_code_or_article).
    """
    fx = 45.3
    items: dict[str, dict[str, Any]] = {}
    reader = csv.reader(io.StringIO(text))
    headers: Optional[list[str]] = None
    section_brand: Optional[str] = None

    for row in reader:
        if not row or all(not str(c).strip() for c in row):
            continue
        first = str(row[0] or "")
        joined = " ".join(str(c or "") for c in row[:3])

        fx_m = _FX_RE.search(joined)
        if "курс" in joined.lower() and fx_m:
            fx = float(fx_m.group(1).replace(",", "."))

        section_brand = _update_section_brand(first, section_brand) or _update_section_brand(
            joined, section_brand
        )

        # Header row detection — sheets have multiple section headers (batteries vs inverters)
        norms_joined = " ".join(_norm_header(c) for c in row)
        if "артикул" in norms_joined and (
            "код" in norms_joined or "промокод" in norms_joined or "інсталятор" in norms_joined
        ):
            # Treat as header only if «Артикул» cell itself is the label (not a product row)
            art_probe = next(
                (i for i, c in enumerate(row) if _norm_header(str(c or "")) == "артикул"),
                None,
            )
            if art_probe is not None and _norm_header(str(row[art_probe] or "")) == "артикул":
                headers = [str(c or "") for c in row]
                continue

        if headers is None:
            continue

        # Skip section title rows (no numeric code)
        code_i = _find_col(headers, "Код")
        art_i = _find_col(headers, "Артикул")
        if art_i is None:
            continue

        code_raw = str(row[code_i] if code_i is not None and code_i < len(row) else "").strip()
        article = str(row[art_i] if art_i < len(row) else "").strip()
        if not article:
            continue
        # Product rows have numeric code
        code_num = _parse_number(code_raw)
        if code_num is None and not code_raw.isdigit():
            # May still be a product if article looks like SKU
            if not re.search(r"[A-Za-z]", article):
                continue

        type_i = _find_col_exact(headers, "Тип")
        power_i = _find_col(headers, "Потужність")
        cap_i = _find_col(headers, "Номінальна ємність")
        name = ""
        if type_i is not None and type_i < len(row):
            cand = str(row[type_i] or "").strip()
            # Skip numeric phase counts / short codes — prefer real descriptions
            if cand and not cand.replace(".", "", 1).isdigit() and len(cand) >= 5:
                name = cand
        art_u = article.upper()
        if not name and power_i is not None and power_i < len(row):
            pw = str(row[power_i] or "").strip()
            if pw and art_u.startswith(("SUN-", "SE-")):
                name = f"Інвертор Deye {article}, {pw}"
        # Batteries: prefer «Акумулятор …, capacity» over bare chemistry label
        if art_u.startswith(("BALFP", "BAHV")) and cap_i is not None and cap_i < len(row):
            cap = str(row[cap_i] or "").strip()
            if cap:
                name = f"Акумулятор Biom {article}, {cap}"
        if (
            art_u.startswith(("SE-", "BOS-G-PACK", "BOS-A-PACK", "HV BOS", "HVBOS"))
            or "BOS-B-PACK" in art_u.replace(" ", "")
        ) and cap_i is not None and cap_i < len(row):
            cap = str(row[cap_i] or "").strip()
            if cap:
                name = f"Акумулятор Deye {article}, {cap}"
        if not name:
            name = article

        avail_i = _find_col(headers, "Наявність")
        availability = ""
        if avail_i is not None and avail_i < len(row):
            availability = str(row[avail_i] or "").strip()

        brand = _infer_brand(article, section_brand)
        key = str(int(code_num)) if code_num is not None else article.upper().replace(" ", "")

        entry = items.get(key) or {
            "code": str(int(code_num)) if code_num is not None else code_raw,
            "article": article,
            "name": name or article,
            "brand": brand,
        }
        entry["article"] = article
        if name:
            entry["name"] = name
        entry["brand"] = brand

        if kind == "promo":
            promo_i = _find_col(headers, "Промокод")
            # Prefer exact «Промокод» over «Промокод (з ПДВ)» — find column whose norm equals промокод
            norms = [_norm_header(h) for h in headers]
            promo_i = None
            promo_vat_i = None
            for i, h in enumerate(norms):
                if h == "промокод":
                    promo_i = i
                elif "промокод" in h and "пдв" in h:
                    promo_vat_i = i
            if promo_i is None:
                for i, h in enumerate(norms):
                    if "промокод" in h and "пдв" not in h:
                        promo_i = i
                        break
            if promo_vat_i is None:
                for i, h in enumerate(norms):
                    if "промокод" in h and "пдв" in h:
                        promo_vat_i = i
                        break
            if promo_i is not None and promo_i < len(row):
                entry["promoUsd"] = _parse_number(row[promo_i])
            if promo_vat_i is not None and promo_vat_i < len(row):
                entry["promoVatUsd"] = _parse_number(row[promo_vat_i])
            if availability:
                entry["availability"] = availability
        else:
            # Installer sheet — «Інсталятор» without VAT + cheapest among price columns
            norms = [_norm_header(h) for h in headers]
            inst_i = None
            for i, h in enumerate(norms):
                if h == "інсталятор":
                    inst_i = i
                    break
            if inst_i is None:
                for i, h in enumerate(norms):
                    if "інсталятор" in h and "пдв" not in h:
                        inst_i = i
                        break
            if inst_i is not None and inst_i < len(row):
                entry["installerUsd"] = _parse_number(row[inst_i])

            # Retail columns — FOP = «Роздріб», VAT = «Роздріб(з ПДВ)»
            retail_i = None
            retail_vat_i = None
            for i, h in enumerate(norms):
                if h == "роздріб" or (h.startswith("роздріб") and "пдв" not in h and len(h) < 40):
                    retail_i = i
                    break
            for i, h in enumerate(norms):
                if "роздріб" in h and "пдв" in h and len(h) < 40:
                    retail_vat_i = i
                    break
            # Deye «АКЦІЯ» rows sometimes insert an extra price without an «АКЦІЇ» header.
            has_action_header = any(h == "акції" or h.startswith("акці") for h in norms if len(h) < 40)
            row_has_action = any("акці" in _norm_header(str(c or "")) for c in row)
            shift = 1 if row_has_action and not has_action_header else 0

            if retail_i is not None:
                ri = retail_i + shift
                if ri < len(row):
                    entry["retailUsd"] = _parse_number(row[ri])
            if retail_vat_i is not None:
                rvi = retail_vat_i + shift
                if rvi < len(row):
                    entry["retailVatUsd"] = _parse_number(row[rvi])

            # Cheapest among price columns only (start at «Інсталятор», not policy text that
            # mentions «інсталятор» in a merged header cell from Google gviz export).
            price_start = inst_i
            price_end = avail_i if avail_i is not None else len(row)
            if price_start is None:
                price_start = 0
            if shift and avail_i is not None:
                price_end = min(len(row), avail_i + shift)
            candidates: list[float] = []
            if price_start is not None:
                for i in range(price_start, min(price_end, len(row))):
                    val = _parse_number(row[i])
                    if val is not None and val > 0:
                        candidates.append(val)
            if candidates:
                entry["installerCheapestUsd"] = min(candidates)
            elif entry.get("installerUsd") is not None:
                entry["installerCheapestUsd"] = entry["installerUsd"]

            if availability:
                entry["availabilityInstaller"] = availability
            # When АКЦІЯ shifts columns, true availability is usually one cell after header index.
            if shift and avail_i is not None:
                ai = avail_i + shift
                if ai < len(row):
                    avail_shifted = str(row[ai] or "").strip()
                    if avail_shifted and _parse_number(avail_shifted) is None:
                        entry["availabilityInstaller"] = avail_shifted

        items[key] = entry

        # Also index by normalized article for BOM lookup
        art_key = article.upper().replace(" ", "")
        items[art_key] = entry

    return fx, items




async def _load_price_list(*, force: bool = False) -> dict[str, Any]:
    now = time.time()
    ttl = float(settings.BESS_PRICE_CACHE_TTL_SEC)
    if not force and _CACHE["payload"] is not None and (now - float(_CACHE["ts"])) < ttl:
        return _CACHE["payload"]

    promo_url = settings.BESS_PROMO_SHEET_URL
    install_url = settings.BESS_INSTALL_SHEET_URL
    etu_url = settings.BESS_ETU_SHEET_URL
    if not install_url and not promo_url and not etu_url:
        raise HTTPException(status_code=503, detail="BESS sheet URLs not configured")

    promo_text = ""
    install_text = ""
    etu_text = ""
    fetch_exc: Optional[Exception] = None
    try:
        promo_text = await _fetch_csv(promo_url) if promo_url else ""
        install_text = await _fetch_csv(install_url) if install_url else ""
    except Exception as exc:
        fetch_exc = exc
        logger.exception("Failed to fetch BIOM BESS price sheets")
    try:
        etu_text = await _fetch_csv(etu_url) if etu_url else ""
    except Exception as exc:
        logger.exception("Failed to fetch ETU BESS price sheet")
        if fetch_exc is None:
            fetch_exc = exc

    if not promo_text and not install_text and not etu_text:
        if _CACHE["payload"] is not None:
            return _CACHE["payload"]
        detail = f"Failed to fetch price sheets: {fetch_exc or 'empty response'}"
        if fetch_exc is not None:
            raise HTTPException(status_code=502, detail=detail) from fetch_exc
        raise HTTPException(status_code=502, detail=detail)

    fx_promo, promo_items = _parse_sheet_csv(promo_text, kind="promo") if promo_text else (None, {})
    fx_inst, install_items = (
        _parse_sheet_csv(install_text, kind="install") if install_text else (None, {})
    )
    fx = fx_promo or fx_inst or 45.3
    etu_items = _parse_etu_sheet_csv(etu_text) if etu_text else {}

    # Merge: start from promo, overlay installer fields
    merged: dict[str, dict[str, Any]] = {}
    for key, row in promo_items.items():
        art = (row.get("article") or "").upper().replace(" ", "")
        code = str(row.get("code") or "")
        # Prefer article as stable list key
        list_key = art or code or key
        if list_key in merged and merged[list_key].get("article"):
            continue
        merged[list_key] = dict(row)

    for key, row in install_items.items():
        art = (row.get("article") or "").upper().replace(" ", "")
        code = str(row.get("code") or "")
        list_key = art or code or key
        existing = merged.get(list_key)
        if existing is None:
            # Try match by code across existing
            for ek, ev in merged.items():
                if code and str(ev.get("code") or "") == code:
                    existing = ev
                    list_key = ek
                    break
        if existing is None:
            merged[list_key] = dict(row)
        else:
            for f in (
                "installerUsd",
                "installerCheapestUsd",
                "retailUsd",
                "retailVatUsd",
                "availabilityInstaller",
            ):
                if row.get(f) is not None:
                    existing[f] = row[f]
            if not existing.get("brand") or existing.get("brand") == "other":
                existing["brand"] = row.get("brand") or existing.get("brand")

    # Deduplicate to unique articles for API response (canonical SKU keys for BOM lookup)
    by_article: dict[str, dict[str, Any]] = {}
    for row in merged.values():
        art = _canonical_article((row.get("article") or "").strip())
        if not art:
            continue
        art_key = art.upper().replace(" ", "")
        if art_key in by_article:
            cur = by_article[art_key]
            for f in (
                "promoUsd",
                "promoVatUsd",
                "installerUsd",
                "installerCheapestUsd",
                "retailUsd",
                "retailVatUsd",
                "availability",
                "availabilityInstaller",
            ):
                if cur.get(f) is None and row.get(f) is not None:
                    cur[f] = row[f]
            continue
        by_article[art_key] = {
            "code": row.get("code") or "",
            "article": art,
            "name": row.get("name") or art,
            "brand": row.get("brand") or "other",
            "promoUsd": row.get("promoUsd"),
            "promoVatUsd": row.get("promoVatUsd"),
            "installerUsd": row.get("installerUsd"),
            "installerCheapestUsd": row.get("installerCheapestUsd"),
            "retailUsd": row.get("retailUsd"),
            "retailVatUsd": row.get("retailVatUsd"),
            "availability": row.get("availability") or "",
            "availabilityInstaller": row.get("availabilityInstaller") or "",
            "priceSourceCash": "install",
            "priceSourceRetail": "install",
        }

    _fill_missing_vat(by_article)
    if etu_items:
        _merge_etu_items(by_article, etu_items, fx)

    payload = {
        "fxRate": fx,
        "items": list(by_article.values()),
        "cachedAt": int(now),
        "ttlSec": int(ttl),
        "sources": {
            "biom": bool(promo_text or install_text),
            "etu": bool(etu_items),
        },
    }
    _CACHE["ts"] = now
    _CACHE["payload"] = payload
    return payload


@router.get("/price-list")
async def get_price_list(refresh: bool = False) -> dict[str, Any]:
    return await _load_price_list(force=refresh)


class DiscountRequestBody(BaseModel):
    preset_id: str = Field(..., min_length=1, max_length=64)
    business_type: str = Field(..., description="fop | vat | cash")
    units: int = Field(..., description="Number of kits, 2…220")
    total_usd: Optional[float] = None
    name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=40)
    contact: Optional[str] = Field(None, max_length=200)
    kit: Optional[dict[str, Any]] = None
    page_url: Optional[str] = Field(None, max_length=2000)


class DiscountRequestResponse(BaseModel):
    id: int
    ok: bool = True
    notified: bool = False


class ContactRequestBody(BaseModel):
    channel: str = Field(..., description="telegram | whatsapp")
    intent: str = Field("offer", description="offer | discount")
    preset_id: Optional[str] = Field(None, max_length=64)
    business_type: Optional[str] = None
    units: Optional[int] = None
    total_usd: Optional[float] = None
    name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=40)
    contact: Optional[str] = Field(None, max_length=200)
    kit: Optional[dict[str, Any]] = None
    page_url: Optional[str] = Field(None, max_length=2000)


class ContactRequestResponse(BaseModel):
    ok: bool = True
    notified: bool = False


@router.post("/contact", response_model=ContactRequestResponse)
async def create_contact_request(payload: ContactRequestBody) -> ContactRequestResponse:
    channel = (payload.channel or "").strip().lower()
    if channel not in ("telegram", "whatsapp"):
        raise HTTPException(status_code=400, detail="channel must be telegram or whatsapp")
    intent = (payload.intent or "offer").strip().lower()
    if intent not in ("offer", "discount"):
        raise HTTPException(status_code=400, detail="intent must be offer or discount")
    if payload.business_type and payload.business_type not in ALLOWED_BUSINESS:
        raise HTTPException(status_code=400, detail=f"business_type must be one of {sorted(ALLOWED_BUSINESS)}")

    name = (payload.name or "").strip() or None
    phone = (payload.phone or "").strip() or None
    contact = (payload.contact or "").strip() or None
    if name and phone:
        contact = f"{name} / {phone}"
    units = payload.units if intent == "discount" else None
    if units is not None and not (ALLOWED_UNITS_MIN <= units <= ALLOWED_UNITS_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"units must be between {ALLOWED_UNITS_MIN} and {ALLOWED_UNITS_MAX}",
        )

    msg = format_bess_lead_message(
        kind=intent,
        channel=channel,
        preset_id=payload.preset_id,
        business_type=payload.business_type,
        units=units,
        total_usd=payload.total_usd,
        contact=contact,
        name=name,
        phone=phone,
        kit=payload.kit,
        page_url=payload.page_url,
    )
    notified = await send_telegram_message(msg)
    logger.info(
        "BESS contact request intent=%s channel=%s preset=%s notified=%s",
        intent,
        channel,
        payload.preset_id,
        notified,
    )
    return ContactRequestResponse(ok=True, notified=notified)


@router.post("/discount-request", response_model=DiscountRequestResponse)
async def create_discount_request(
    payload: DiscountRequestBody,
    db: AsyncSession = Depends(get_db),
) -> DiscountRequestResponse:
    if payload.business_type not in ALLOWED_BUSINESS:
        raise HTTPException(status_code=400, detail=f"business_type must be one of {sorted(ALLOWED_BUSINESS)}")
    if not (ALLOWED_UNITS_MIN <= payload.units <= ALLOWED_UNITS_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"units must be between {ALLOWED_UNITS_MIN} and {ALLOWED_UNITS_MAX}",
        )

    name = (payload.name or "").strip() or None
    phone = (payload.phone or "").strip() or None
    contact = (payload.contact or "").strip() or None
    if name and phone:
        contact = f"{name} / {phone}"
    row = BessDiscountRequest(
        preset_id=payload.preset_id.strip()[:64],
        business_type=payload.business_type,
        units=payload.units,
        total_usd=payload.total_usd,
        contact=contact,
        kit_json=payload.kit,
    )
    lead_id = 0
    try:
        db.add(row)
        await db.commit()
        await db.refresh(row)
        lead_id = int(row.id)
        logger.info(
            "BESS discount request saved id=%s preset=%s type=%s units=%s",
            row.id,
            row.preset_id,
            row.business_type,
            row.units,
        )
    except Exception:
        logger.exception("Failed to persist BESS discount request — falling back to memory")
        await db.rollback()
        mem_id = len(_MEMORY_LEADS) + 1
        _MEMORY_LEADS.append(
            {
                "id": mem_id,
                "preset_id": payload.preset_id,
                "business_type": payload.business_type,
                "units": payload.units,
                "total_usd": payload.total_usd,
                "contact": contact,
                "name": name,
                "phone": phone,
                "kit": payload.kit,
            }
        )
        lead_id = mem_id

    msg = format_bess_lead_message(
        kind="discount",
        preset_id=payload.preset_id,
        business_type=payload.business_type,
        units=payload.units,
        total_usd=payload.total_usd,
        contact=contact,
        name=name,
        phone=phone,
        kit=payload.kit,
        page_url=payload.page_url,
    )
    notified = await send_telegram_message(msg)
    return DiscountRequestResponse(id=lead_id, ok=True, notified=notified)
