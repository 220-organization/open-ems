"""Order BESS — BIOM + Energotrendy Ukrainy price lists from Google Sheets + leads."""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.admin_auth import require_admin_token
from app.db import get_db
from app.models import BessDiscountRequest
from app.sales_buy_request_store import (
    KIND_BESS,
    KIND_BESS_DISCOUNT,
    save_sales_buy_request,
)
from app.telegram_notify import format_bess_lead_message, send_telegram_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bess-order", tags=["bess-order"])

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_IMAGE_CACHE: dict[str, tuple[float, str]] = {}
_IMAGE_TTL_SEC = 6 * 60 * 60
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
    "SUN-6K-SG06LP1-EU-BM2",
    "SUN-8K-SG05LP1-EU",
    "SUN-8K-SG06LP1-EU-BM3",
    "SUN-10K-SG02LP1-EU-AM3",
    "SUN-10K-SG06LP1-EU-BM3",
    "SUN-12K-SG02LP1-EU",
    "SUN-12K-SG06LP1-EU-BM3",
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
    "SigenStor EC 3.0 SP",
    "SigenStor EC 6.0 SP",
    "SigenStor EC 10.0 TP",
    "SigenStor EC 30.0 TP",
    "SigenStor BAT 6.0",
    "SigenStor BAT 10.0",
    "Sigen Gateway Home SP 12K",
    "Sigen Gateway Home TP 30K",
    "SigenStor Installation Kit for Ground",
    "SigenStor BC",
    "SigenStor Neo Installation Kit Ground",
    "Sigen PV 50M1-HYB",
    "Sigen PV 80M1-HYB",
    "Sigen PV 125M1-HYB",
    "SigenStack BAT 12.06",
    "SigenStack BC M2-0.5C-BST",
    "SigenStack BC M2-1C-BST",
    "SigenStack Base MAIN-0.5C",
    "SigenStack Base MAIN-1C",
    "SigenStack Base SUB-0.5C",
    "SigenStack Base SUB-1C",
    "SigenStack Cover",
    "SigenStack BC Cables 4m",
    "Sigen Communication Module",
)
# Sigenergy price list Sigen1.xlsx (USD): purchase / sale / with VAT.
# Cash (Vyrii installers) = purchase. FOP = sale. VAT payers = with VAT.
# Lead time for every Sigenergy line: 10 days.
_SIGENERGY_AVAIL = "10 днів"
# article, name, purchase, sale, vat
_SIGENERGY_ROWS: tuple[tuple[str, str, int, int, int], ...] = (
    ("SigenStor EC 3.0 SP", "SigenStor EC 3.0 SP, 3 кВт, 1 фаза", 1146, 1418, 1702),
    ("SigenStor EC 4.0 SP", "SigenStor EC 4.0 SP, 4 кВт, 1 фаза", 1196, 1481, 1777),
    ("SigenStor EC 5.0 SP", "SigenStor EC 5.0 SP, 5 кВт, 1 фаза", 1259, 1559, 1870),
    ("SigenStor EC 6.0 SP", "SigenStor EC 6.0 SP, 6 кВт, 1 фаза", 1309, 1621, 1945),
    ("SigenStor EC 8.0 SP", "SigenStor EC 8.0 SP, 8 кВт, 1 фаза", 1850, 2291, 2749),
    ("SigenStor EC 10.0 SP", "SigenStor EC 10.0 SP, 10 кВт, 1 фаза", 2014, 2493, 2992),
    ("SigenStor EC 12.0 SP", "SigenStor EC 12.0 SP, 12 кВт, 1 фаза", 2178, 2696, 3235),
    ("SigenStor EC 5.0 TP", "SigenStor EC 5.0 TP, 5 кВт, 3 фази", 1800, 2228, 2674),
    ("SigenStor EC 6.0 TP", "SigenStor EC 6.0 TP, 6 кВт, 3 фази", 1976, 2447, 2936),
    ("SigenStor EC 8.0 TP", "SigenStor EC 8.0 TP, 8 кВт, 3 фази", 2039, 2525, 3030),
    ("SigenStor EC 10.0 TP", "SigenStor EC 10.0 TP, 10 кВт, 3 фази", 2127, 2634, 3161),
    ("SigenStor EC 12.0 TP", "SigenStor EC 12.0 TP, 12 кВт, 3 фази", 2518, 3117, 3741),
    ("SigenStor EC 15.0 TP", "SigenStor EC 15.0 TP, 15 кВт, 3 фази", 2819, 3491, 4189),
    ("SigenStor EC 17.0 TP", "SigenStor EC 17.0 TP, 17 кВт, 3 фази", 2983, 3693, 4432),
    ("SigenStor EC 20.0 TP", "SigenStor EC 20.0 TP, 20 кВт, 3 фази", 3147, 3896, 4675),
    ("SigenStor EC 25.0 TP", "SigenStor EC 25.0 TP, 25 кВт, 3 фази", 3663, 4536, 5443),
    ("SigenStor EC 30.0 TP", "SigenStor EC 30.0 TP, 30 кВт, 3 фази", 3977, 4924, 5909),
    ("SigenStor BAT 6.0", "SigenStor BAT 6.0, 6 кВт·год", 1561, 1933, 2320),
    ("SigenStor BAT 10.0", "SigenStor BAT 10.0, 10 кВт·год", 2090, 2587, 3104),
    ("Sigen Gateway Home SP 12K", "Sigen Gateway Home SP 12K", 428, 530, 636),
    ("Sigen Gateway HomePro SP", "Sigen Gateway HomePro SP", 604, 748, 897),
    ("Sigen Gateway Home TP 30K", "Sigen Gateway Home TP 30K", 491, 608, 730),
    ("Sigen Gateway HomePro TP", "Sigen Gateway HomePro TP", 894, 1106, 1328),
    ("SigenStor Installation Kit for Ground", "SigenStor Installation Kit for Ground", 101, 125, 150),
    ("SigenStor Installation Kit for Wall", "SigenStor Installation Kit for Wall", 125, 155, 186),
    ("Sigen Hybrid 5.0 SP2", "Sigen Hybrid 5.0 SP2, 5 кВт, 1 фаза", 528, 654, 785),
    ("Sigen Hybrid 6.0 SP2", "Sigen Hybrid 6.0 SP2, 6 кВт, 1 фаза", 541, 670, 803),
    ("Sigen Hybrid 8.0 TP2", "Sigen Hybrid 8.0 TP2, 8 кВт, 3 фази", 780, 966, 1159),
    ("Sigen Hybrid 10.0 TP2", "Sigen Hybrid 10.0 TP2, 10 кВт, 3 фази", 793, 982, 1178),
    ("Sigen Hybrid 12.0 TP2", "Sigen Hybrid 12.0 TP2, 12 кВт, 3 фази", 805, 997, 1197),
    ("SigenStor BC", "SigenStor BC, контролер батареї", 302, 374, 449),
    ("SigenStor Neo EC 3.0 SP", "SigenStor Neo EC 3.0 SP, 3 кВт, 1 фаза", 843, 1044, 1253),
    ("SigenStor Neo EC 5.0 SP", "SigenStor Neo EC 5.0 SP, 5 кВт, 1 фаза", 950, 1177, 1412),
    ("SigenStor Neo EC 6.0 SP", "SigenStor Neo EC 6.0 SP, 6 кВт, 1 фаза", 1013, 1255, 1505),
    ("SigenStor Neo EC 8.0 SP", "SigenStor Neo EC 8.0 SP, 8 кВт, 1 фаза", 1152, 1426, 1711),
    ("SigenStor Neo EC 10.0 SP", "SigenStor Neo EC 10.0 SP, 10 кВт, 1 фаза", 1284, 1590, 1908),
    ("SigenStor Neo EC 12.0 SP", "SigenStor Neo EC 12.0 SP, 12 кВт, 1 фаза", 1416, 1754, 2104),
    ("SigenStor Neo EC 6.0 TP", "SigenStor Neo EC 6.0 TP, 6 кВт, 3 фази", 1215, 1504, 1805),
    ("SigenStor Neo EC 8.0 TP", "SigenStor Neo EC 8.0 TP, 8 кВт, 3 фази", 1284, 1590, 1908),
    ("SigenStor Neo EC 10.0 TP", "SigenStor Neo EC 10.0 TP, 10 кВт, 3 фази", 1347, 1668, 2001),
    ("SigenStor Neo EC 12.0 TP", "SigenStor Neo EC 12.0 TP, 12 кВт, 3 фази", 1416, 1754, 2104),
    ("SigenStor Neo EC 15.0 TP", "SigenStor Neo EC 15.0 TP, 15 кВт, 3 фази", 1479, 1832, 2198),
    ("SigenStor Neo BAT 6.0", "SigenStor Neo BAT 6.0, 6,02 кВт·год", 1127, 1395, 1674),
    ("SigenStor Neo BAT 8.0", "SigenStor Neo BAT 8.0, 7,52 кВт·год", 1328, 1645, 1973),
    ("SigenStor Neo Installation Kit Ground", "SigenStor Neo Installation Kit Ground", 69, 86, 103),
    ("SigenStor Neo Installation Kit Wall", "SigenStor Neo Installation Kit Wall", 82, 101, 122),
    ("Sigen PV 50M1-HYB", "Sigen PV 50M1-HYB, 50 кВт, гібрид бекап", 3742, 4633, 5560),
    ("Sigen PV 60M1-HYB", "Sigen PV 60M1-HYB, 60 кВт, гібрид бекап", 3866, 4787, 5744),
    ("Sigen PV 80M1-HYB", "Sigen PV 80M1-HYB, 80 кВт, гібрид бекап", 4241, 5251, 6301),
    ("Sigen PV 100M1-HYB", "Sigen PV 100M1-HYB, 100 кВт, гібрид бекап", 4366, 5405, 6486),
    ("Sigen PV 110M1-HYB", "Sigen PV 110M1-HYB, 110 кВт, гібрид бекап", 4241, 5251, 6301),
    ("Sigen PV 125M1-HYB", "Sigen PV 125M1-HYB, 125 кВт, гібрид бекап", 4241, 5251, 6301),
    ("SigenStack BAT 12.06", "SigenStack BAT 12.06, 12 кВт·год", 1496, 1853, 2223),
    ("SigenStack BC M2-0.5C-BST", "SigenStack BC M2-0.5C-BST", 3119, 3861, 4633),
    ("SigenStack BC M2-1C-BST", "SigenStack BC M2-1C-BST", 5238, 6486, 7783),
    ("SigenStack Base MAIN-0.5C", "SigenStack Base MAIN-0.5C", 624, 772, 927),
    ("SigenStack Base MAIN-1C", "SigenStack Base MAIN-1C", 748, 926, 1111),
    ("SigenStack Base SUB-0.5C", "SigenStack Base SUB-0.5C", 624, 772, 927),
    ("SigenStack Base SUB-1C", "SigenStack Base SUB-1C", 748, 926, 1111),
    ("SigenStack Cover", "SigenStack Cover", 206, 255, 306),
    ("SigenStack BC Cables 4m", "SigenStack BC Cables 4m", 206, 255, 306),
    ("Sigen Communication Module", "Sigen Communication Module", 101, 125, 150),
)


def _sigenergy_image(article: str) -> str:
    """Product photo cropped from the Sigenergy datasheets, served by the UI."""
    a = article.lower()
    if a.startswith("sigenstor ec "):
        # SP and TP share a chassis, but the datasheet photo labeled
        # "Трифазний" must not be used for a single-phase controller.
        if a.endswith(" sp"):
            return "/static/bess/sigen-stor-ec-sp.jpg"
        return "/static/bess/sigen-stor-ec.jpg"
    if a.startswith("sigen hybrid"):
        return "/static/bess/sigen-hybrid.jpg"
    if a.startswith("sigenstor bat") or a == "sigenstor bc":
        return "/static/bess/sigen-stor-bat.jpg"
    if a.startswith("sigen pv"):
        return "/static/bess/sigen-ci-hyb.jpg"
    if a.startswith("sigen gateway"):
        return "/static/bess/sigen-gateway.jpg"
    return ""


_SIGENERGY_CATALOG: tuple[dict[str, Any], ...] = tuple(
    {
        "article": article,
        "name": name,
        "purchase": purchase,
        "sale": sale,
        "vat": vat,
        "imageUrl": _sigenergy_image(article),
    }
    for article, name, purchase, sale, vat in _SIGENERGY_ROWS
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
    "SIGENSTORINSTALLATIONKITFORGROUNDMOUNTED": "SigenStor Installation Kit for Ground",
    "SIGENSTACKBAT12.0": "SigenStack BAT 12.06",
    "SIGENSTACKBAT12.06": "SigenStack BAT 12.06",
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


_ARRIVAL_WINDOW_RE = re.compile(
    r"(\d{1,2}\s*[-–—]\s*\d{1,2}\s*"
    r"(?:січня|лютого|березня|квітня|травня|червня|липня|серпня|"
    r"вересня|жовтня|листопада|грудня))",
    re.IGNORECASE,
)


def _clean_arrival_window(raw: str) -> str:
    match = _ARRIVAL_WINDOW_RE.search(re.sub(r"\s+", " ", raw or ""))
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _is_specific_arrival(availability: str) -> bool:
    return bool(_clean_arrival_window(availability))


def _etu_price_columns(norms: list[str]) -> tuple[Optional[int], Optional[int]]:
    """First UAH price column is prepaid, the next is TOV.

    The description header mentions «передплата» and «ТОВ» but is not a price.
    Current sheets label both money columns «Ціна під замовлення, грн».
    """
    price_cols: list[int] = []
    for i, header in enumerate(norms):
        if header.startswith("опис"):
            continue
        if "ціна" in header and ("грн" in header or "замовлення" in header):
            price_cols.append(i)
    if price_cols:
        prepaid_i = price_cols[0]
        tov_i = price_cols[1] if len(price_cols) > 1 else None
        return prepaid_i, tov_i

    prepaid_i = None
    tov_i = None
    for i, header in enumerate(norms):
        if header.startswith("опис"):
            continue
        if prepaid_i is None and "передплата" in header:
            prepaid_i = i
        if tov_i is None and re.search(r"(^|[\s,])тов([\s,]|$)", header):
            tov_i = i
    return prepaid_i, tov_i


def _row_arrival_window(row: list[Any], after_index: Optional[int]) -> str:
    start = 0 if after_index is None else after_index + 1
    for cell in row[start:]:
        text = re.sub(r"\s+", " ", str(cell or "")).strip()
        if not text or len(text) > 40:
            continue
        window = _clean_arrival_window(text)
        if window:
            return window
    return ""


def _unique_etu_rows(items: dict[str, dict[str, Any]]):
    seen: set[int] = set()
    for row in items.values():
        ident = id(row)
        if ident in seen:
            continue
        seen.add(ident)
        yield row


def _banner_token_matches(article: str, token: str, kind: str) -> bool:
    key = _sku_key(article)
    tok = token.lower().replace("к", "k")
    tok = re.sub(r"\([^)]*\)", "", tok)
    tok = re.sub(r"[^a-z0-9]", "", tok)
    if not tok or not key:
        return False
    if kind == "inverter":
        match = re.fullmatch(r"(\d+)k(?:lp(\d))?", tok)
        if not match or "HP" in key:
            return False
        kw, lp = match.group(1), match.group(2)
        if not re.search(rf"SUN{kw}K", key):
            return False
        if lp and f"LP{lp}" not in key:
            return False
        return True
    if tok == "proc":
        return "F5PROC" in key
    if tok in ("f12max", "f16max"):
        return tok.upper() in key
    if tok == "f16":
        return "F16" in key and "MAX" not in key
    if tok == "f12":
        return "F12" in key and "MAX" not in key
    return False


def _apply_etu_banner_availability(items: dict[str, dict[str, Any]], banner: str) -> None:
    """Fill generic NL availability from the sheet intro (Kyiv stock and 6K window)."""
    text = re.sub(r"\s+", " ", banner or "")
    if not text:
        return
    for match in re.finditer(
        r"(\d+)\s*k\s+інвертор.{0,160}?" + _ARRIVAL_WINDOW_RE.pattern,
        text,
        re.IGNORECASE,
    ):
        kw = match.group(1)
        date = _clean_arrival_window(match.group(2))
        if not date:
            continue
        for row in _unique_etu_rows(items):
            art = str(row.get("article") or "")
            if row.get("availability") != _ETU_AVAIL:
                continue
            if re.search(rf"SUN-{kw}K", art, re.IGNORECASE):
                row["availability"] = date

    kyiv = re.search(r"київ\s+" + _ARRIVAL_WINDOW_RE.pattern, text, re.IGNORECASE)
    if not kyiv:
        return
    date = _clean_arrival_window(kyiv.group(1))
    if not date:
        return
    tail = text[kyiv.end() :]
    cut = re.search(r"\d+\s*k\s+інвертор", tail, re.IGNORECASE)
    if cut:
        tail = tail[: cut.start()]
    inv_match = re.search(r"інвертор\w*\s*:", tail, re.IGNORECASE)
    bat_match = re.search(r"акумулятор\w*\s*:", tail, re.IGNORECASE)
    inv_part = ""
    bat_part = ""
    if inv_match and bat_match and inv_match.start() < bat_match.start():
        inv_part = tail[inv_match.end() : bat_match.start()]
        bat_part = tail[bat_match.end() :]
    elif inv_match and bat_match:
        bat_part = tail[bat_match.end() : inv_match.start()]
        inv_part = tail[inv_match.end() :]
    elif inv_match:
        inv_part = tail[inv_match.end() :]
    elif bat_match:
        bat_part = tail[bat_match.end() :]

    def tokens(part: str) -> list[str]:
        part = re.sub(r"\([^)]*\)", "", part)
        return [piece.strip() for piece in part.split(",") if piece.strip()]

    inv_tokens = tokens(inv_part)
    bat_tokens = tokens(bat_part)
    for row in _unique_etu_rows(items):
        if row.get("availability") != _ETU_AVAIL:
            continue
        art = str(row.get("article") or "")
        if any(_banner_token_matches(art, tok, "inverter") for tok in inv_tokens):
            row["availability"] = date
        elif any(_banner_token_matches(art, tok, "battery") for tok in bat_tokens):
            row["availability"] = date


def _parse_etu_sheet_csv(text: str) -> dict[str, dict[str, Any]]:
    """Parse Energotrendy Ukrainy UAH price list (model + prepaid / TOV columns)."""
    items: dict[str, dict[str, Any]] = {}
    reader = csv.reader(io.StringIO(text or ""))
    headers: Optional[list[str]] = None
    banner_chunks: list[str] = []

    for row in reader:
        if not row or all(not str(c).strip() for c in row):
            continue
        norms_joined = " ".join(_norm_header(c) for c in row)
        if headers is None:
            banner_chunks.append(" ".join(str(c or "") for c in row))
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
        prepaid_i, tov_i = _etu_price_columns(norms)

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

        price_after = None
        for idx in (prepaid_i, tov_i):
            if idx is None:
                continue
            price_after = idx if price_after is None else max(price_after, idx)
        arrival = _row_arrival_window(row, price_after)

        key = _sku_key(article) or article.upper().replace(" ", "")
        items[key] = {
            "article": article,
            "articleRaw": _clean_article(article_raw),
            "name": name,
            "brand": brand,
            "prepaidUah": prepaid if prepaid and prepaid > 0 else None,
            "tovUah": tov if tov and tov > 0 else None,
            "availability": arrival or _ETU_AVAIL,
        }
        raw_key = _sku_key(article_raw)
        if raw_key and raw_key not in items:
            items[raw_key] = items[key]
    _apply_etu_banner_availability(items, " ".join(banner_chunks))
    return items


def _fill_missing_vat(by_article: dict[str, dict[str, Any]]) -> None:
    """VAT-payer price is always retail + 20%. The sheet «Роздріб (з ПДВ)» column is 13%."""
    for row in by_article.values():
        if row.get("retailUsd") is None:
            continue
        try:
            row["retailVatUsd"] = round(float(row["retailUsd"]) * _UA_VAT, 2)
        except (TypeError, ValueError):
            continue


_NO_ARRIVAL_RE = re.compile(
    r"дані\s*про\s*приход|приход[иі]\s+відсутн|нет\s+данных\s+о\s+приход|no\s+arrival\s+data",
    re.IGNORECASE,
)


def _has_no_arrival_dates(availability: str) -> bool:
    return bool(_NO_ARRIVAL_RE.search(availability or ""))


_BIOM_DATE_RE = re.compile(r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?")
_BIOM_INSTOCK_RE = re.compile(r"в\s*наявност|закінчил", re.IGNORECASE)


def _biom_arrival_label(text: str) -> str:
    """Date or in-stock text from a BIOM «Наявність» cell."""
    raw = re.sub(r"\s+", " ", (text or "")).strip(" .")
    if not raw or _has_no_arrival_dates(raw):
        return ""
    if _BIOM_INSTOCK_RE.search(raw) or _BIOM_DATE_RE.search(raw):
        return raw
    return ""


def _with_promo_arrival(availability: str, availability_installer: str) -> tuple[str, str]:
    """Public BIOM sheet date replaces the installer-sheet window."""
    promo = _biom_arrival_label(availability)
    if promo:
        return promo, promo
    return (availability or "").strip(), (availability_installer or "").strip()


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
        # Prepaid 100% column is the NL list price shown for every business type.
        etu_usd = cash_usd if cash_usd is not None else fop_usd
        etu_avail = (row.get("availability") or "").strip()
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
                "etuUsd": etu_usd,
                "availability": etu_avail,
                "availabilityInstaller": etu_avail,
                "priceSourceCash": "etu" if cash_usd is not None else None,
                "priceSourceRetail": "etu" if fop_usd is not None else None,
            }
            continue
        if etu_usd is not None:
            existing["etuUsd"] = etu_usd

        biom_cash = existing.get("installerCheapestUsd")
        if biom_cash is None:
            biom_cash = existing.get("installerUsd")
        if cash_usd is not None and (biom_cash is None or cash_usd < float(biom_cash)):
            existing["installerUsd"] = cash_usd
            existing["installerCheapestUsd"] = cash_usd
            existing["priceSourceCash"] = "etu"
        biom_retail = existing.get("retailUsd")
        if fop_usd is not None and (biom_retail is None or fop_usd < float(biom_retail)):
            existing["retailUsd"] = fop_usd
            if vat_usd is not None:
                existing["retailVatUsd"] = vat_usd
            existing["priceSourceRetail"] = "etu"
        elif existing.get("retailVatUsd") is None and vat_usd is not None:
            existing["retailVatUsd"] = vat_usd

        # ETU can supply this SKU even when the BIOM cash price wins — unlock the UI
        # when BIOM only says «дані про приходи відсутні». A real BIOM date
        # (for example «10.12» or «в наявності») stays with that BIOM price.
        # ETU's own window is used when the cash price comes from ETU, or BIOM
        # has no arrival of its own.
        if etu_avail and (cash_usd is not None or fop_usd is not None):
            biom_avail = (
                f"{existing.get('availabilityInstaller') or ''} "
                f"{existing.get('availability') or ''}"
            )
            biom_dated = bool(
                _biom_arrival_label(str(existing.get("availability") or ""))
                or _biom_arrival_label(str(existing.get("availabilityInstaller") or ""))
            )
            cash_from_etu = existing.get("priceSourceCash") == "etu"
            shown = (
                existing.get("availabilityInstaller") or existing.get("availability") or ""
            ).strip()
            if biom_dated and not cash_from_etu:
                pass
            elif (
                cash_from_etu
                or _has_no_arrival_dates(biom_avail)
                or not shown
                or _is_specific_arrival(etu_avail)
            ):
                existing["availabilityInstaller"] = etu_avail
                existing["availability"] = etu_avail


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
        # All-in-one cabinets use «Потужність» + «Ємність», not battery chemistry columns.
        if art_u.startswith("UBT"):
            pw = (
                str(row[power_i] or "").strip()
                if power_i is not None and power_i < len(row)
                else ""
            )
            cap_i_exact = _find_col_exact(headers, "Ємність")
            cap = (
                str(row[cap_i_exact] or "").strip()
                if cap_i_exact is not None and cap_i_exact < len(row)
                else ""
            )
            spec = " / ".join(part for part in (pw, cap) if part)
            name = f"Шафа Ubetter {article}" + (f", {spec}" if spec else "")
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
        if not availability:
            for cell in row:
                text = str(cell or "").strip()
                if not text or _parse_number(text) is not None:
                    continue
                if re.search(r"наявност|приход", text, re.I):
                    availability = text
                    break

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
            ignore_price_indexes: set[int] = set()
            if retail_vat_i is not None:
                rvi = retail_vat_i + shift
                if rvi < len(row):
                    vat_val = _parse_number(row[rvi])
                    retail_val = entry.get("retailUsd")
                    # A «with VAT» cell below the net price is a broken sheet formula, not a discount.
                    if (
                        vat_val is not None
                        and retail_val is not None
                        and float(vat_val) < float(retail_val)
                    ):
                        vat_val = None
                        ignore_price_indexes.add(rvi)
                    entry["retailVatUsd"] = vat_val

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
                    if i in ignore_price_indexes:
                        continue
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


def _merge_sigenergy_catalog(by_article: dict[str, dict[str, Any]]) -> None:
    """Overlay the Sigenergy 50 kW / 60 kWh kit. PDF prices win over sheet rows."""
    for row in _SIGENERGY_CATALOG:
        art = row["article"]
        art_key = art.upper().replace(" ", "")
        by_article[art_key] = {
            "code": "",
            "article": art,
            "name": row["name"],
            "brand": "sigenergy",
            "promoUsd": None,
            "promoVatUsd": None,
            "installerUsd": row["purchase"],
            "installerCheapestUsd": row["purchase"],
            "retailUsd": row["sale"],
            "retailVatUsd": row["vat"],
            "availability": _SIGENERGY_AVAIL,
            "availabilityInstaller": _SIGENERGY_AVAIL,
            "priceSourceCash": "sigenergy",
            "priceSourceRetail": "sigenergy",
            "imageUrl": row.get("imageUrl") or "",
        }


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
            avail, avail_inst = _with_promo_arrival(
                str(cur.get("availability") or row.get("availability") or ""),
                str(cur.get("availabilityInstaller") or row.get("availabilityInstaller") or ""),
            )
            cur["availability"] = avail
            cur["availabilityInstaller"] = avail_inst
            continue
        avail, avail_inst = _with_promo_arrival(
            str(row.get("availability") or ""),
            str(row.get("availabilityInstaller") or ""),
        )
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
            "availability": avail,
            "availabilityInstaller": avail_inst,
            "priceSourceCash": "install",
            "priceSourceRetail": "install",
        }

    _fill_missing_vat(by_article)
    if etu_items:
        _merge_etu_items(by_article, etu_items, fx)
    _merge_sigenergy_catalog(by_article)

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


async def _first_search_thumbnail(query: str) -> str:
    """First image-search thumbnail for a product name. Cached so the table does not refetch."""
    now = time.time()
    cached = _IMAGE_CACHE.get(query)
    if cached and now - cached[0] < _IMAGE_TTL_SEC:
        return cached[1]
    headers = {"User-Agent": "Mozilla/5.0"}
    url = ""
    async with httpx.AsyncClient(follow_redirects=True, timeout=12.0, headers=headers) as client:
        home = await client.get("https://duckduckgo.com/", params={"q": query})
        match = re.search(r'vqd="([^"]+)"', home.text) or re.search(r"vqd=([\d-]+)", home.text)
        if match:
            images = await client.get(
                "https://duckduckgo.com/i.js",
                params={"l": "ua-uk", "o": "json", "q": query, "vqd": match.group(1), "f": ",,,", "p": "1"},
                headers={"Referer": "https://duckduckgo.com/"},
            )
            for row in images.json().get("results") or []:
                url = str(row.get("thumbnail") or row.get("image") or "")
                if url.startswith("https://"):
                    break
                url = ""
    _IMAGE_CACHE[query] = (now, url)
    return url


@router.get("/image-preview")
async def image_preview(q: str = "") -> dict[str, Any]:
    query = " ".join((q or "").split())[:180]
    if len(query) < 2:
        return {"images": []}
    try:
        url = await _first_search_thumbnail(query)
    except Exception:
        logger.exception("BESS image preview failed for %s", query)
        return {"images": []}
    return {"images": [url] if url else []}


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


class BuyRequestBody(BaseModel):
    preset_id: Optional[str] = Field(None, max_length=64)
    business_type: Optional[str] = None
    total_usd: Optional[float] = None
    name: Optional[str] = Field(None, max_length=120)
    phone: str = Field(..., max_length=40)
    kit: Optional[dict[str, Any]] = None
    page_url: Optional[str] = Field(None, max_length=2000)


class BuyRequestResponse(BaseModel):
    ok: bool = True
    notified: bool = False


@router.post("/buy-request", response_model=BuyRequestResponse)
async def create_buy_request(
    payload: BuyRequestBody,
    db: AsyncSession = Depends(get_db),
) -> BuyRequestResponse:
    """Notify support chat about a buy request. The user stays on the page."""
    phone = (payload.phone or "").strip()
    if len(phone) < 5:
        raise HTTPException(status_code=400, detail="phone is required")
    if payload.business_type and payload.business_type not in ALLOWED_BUSINESS:
        raise HTTPException(status_code=400, detail=f"business_type must be one of {sorted(ALLOWED_BUSINESS)}")

    name = (payload.name or "").strip() or None
    msg = format_bess_lead_message(
        kind="buy",
        preset_id=payload.preset_id,
        business_type=payload.business_type,
        total_usd=payload.total_usd,
        contact=None,
        name=name,
        phone=phone,
        kit=payload.kit,
        page_url=payload.page_url,
    )
    notified = await send_telegram_message(msg)
    if not notified:
        raise HTTPException(status_code=502, detail="Unable to notify support")

    amount_label = None
    if payload.total_usd is not None:
        amount_label = f"${payload.total_usd:,.2f}"
    kit_label = None
    if isinstance(payload.kit, dict):
        kit_label = payload.kit.get("label") or payload.kit.get("title")
    await save_sales_buy_request(
        db,
        kind=KIND_BESS,
        name=name,
        phone=phone,
        title=kit_label or (payload.preset_id or "Order BESS"),
        amount_label=amount_label,
        status="requested",
        page_url=(payload.page_url or "").strip() or None,
        payload={
            "preset_id": payload.preset_id,
            "business_type": payload.business_type,
            "total_usd": payload.total_usd,
            "kit": payload.kit,
        },
    )

    logger.info("BESS buy request preset=%s notified=%s", payload.preset_id, notified)
    return BuyRequestResponse(ok=True, notified=True)


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
    amount_label = None
    if payload.total_usd is not None:
        amount_label = f"${payload.total_usd:,.2f}"
    await save_sales_buy_request(
        db,
        kind=KIND_BESS_DISCOUNT,
        name=name,
        phone=phone,
        title=payload.preset_id.strip()[:64],
        amount_label=amount_label,
        status="requested",
        page_url=(payload.page_url or "").strip() or None,
        payload={
            "preset_id": payload.preset_id,
            "business_type": payload.business_type,
            "units": payload.units,
            "total_usd": payload.total_usd,
            "contact": contact,
            "kit": payload.kit,
            "legacy_discount_id": lead_id,
        },
    )
    return DiscountRequestResponse(id=lead_id, ok=True, notified=notified)


class BessLeadAdmin(BaseModel):
    id: int
    preset_id: str
    business_type: str
    units: int
    total_usd: Optional[float] = None
    contact: Optional[str] = None
    created_on: datetime


class BessLeadAdminList(BaseModel):
    items: list[BessLeadAdmin]


class BessLeadWrite(BaseModel):
    preset_id: str = Field(..., min_length=1, max_length=64)
    business_type: str = Field(..., min_length=1, max_length=32)
    units: int = Field(..., ge=1, le=500)
    total_usd: Optional[float] = Field(None, ge=0)
    contact: Optional[str] = Field(None, max_length=200)


def _bess_lead_admin(row: BessDiscountRequest) -> BessLeadAdmin:
    return BessLeadAdmin(
        id=int(row.id),
        preset_id=row.preset_id,
        business_type=row.business_type,
        units=int(row.units),
        total_usd=row.total_usd,
        contact=row.contact,
        created_on=row.created_on,
    )


@router.get("/discount-requests/admin", response_model=BessLeadAdminList)
async def list_bess_leads_admin(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
) -> BessLeadAdminList:
    result = await db.execute(
        select(BessDiscountRequest).order_by(BessDiscountRequest.created_on.desc()).limit(200)
    )
    return BessLeadAdminList(items=[_bess_lead_admin(row) for row in result.scalars().all()])


@router.post("/discount-requests/admin", response_model=BessLeadAdmin, status_code=201)
async def create_bess_lead_admin(
    payload: BessLeadWrite,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
) -> BessLeadAdmin:
    row = BessDiscountRequest(
        preset_id=payload.preset_id.strip()[:64],
        business_type=payload.business_type.strip()[:32],
        units=payload.units,
        total_usd=payload.total_usd,
        contact=(payload.contact or "").strip() or None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _bess_lead_admin(row)


@router.put("/discount-requests/admin/{lead_id}", response_model=BessLeadAdmin)
async def update_bess_lead_admin(
    lead_id: int,
    payload: BessLeadWrite,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
) -> BessLeadAdmin:
    row = await db.get(BessDiscountRequest, lead_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    row.preset_id = payload.preset_id.strip()[:64]
    row.business_type = payload.business_type.strip()[:32]
    row.units = payload.units
    row.total_usd = payload.total_usd
    row.contact = (payload.contact or "").strip() or None
    await db.commit()
    await db.refresh(row)
    return _bess_lead_admin(row)


@router.delete("/discount-requests/admin/{lead_id}", status_code=204)
async def delete_bess_lead_admin(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_admin_token),
) -> None:
    row = await db.get(BessDiscountRequest, lead_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    await db.delete(row)
    await db.commit()
