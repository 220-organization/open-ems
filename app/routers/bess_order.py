"""Order BESS — BIOM price lists from Google Sheets + discount-request leads."""

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


def _to_csv_export_url(url: str) -> str:
    """Accept edit or export Google Sheets URL; return CSV export URL."""
    raw = (url or "").strip()
    if not raw:
        return raw
    if "export?format=csv" in raw or "/export?" in raw:
        return raw
    m = _SHEET_ID_RE.search(raw)
    if not m:
        return raw
    sheet_id = m.group(1)
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    gid = (qs.get("gid") or ["0"])[0]
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?"
        + urlencode({"format": "csv", "gid": gid})
    )


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


def _parse_sheet_csv(text: str, *, kind: str) -> tuple[float, dict[str, dict[str, Any]]]:
    """
    Parse BIOM price CSV.
    kind: 'promo' → promoUsd / promoVatUsd / availability
          'install' → installerUsd / availabilityInstaller
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
            # Installer sheet — prefer «Інсталятор» without VAT
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
            if availability:
                entry["availabilityInstaller"] = availability

        items[key] = entry

        # Also index by normalized article for BOM lookup
        art_key = article.upper().replace(" ", "")
        items[art_key] = entry

    return fx, items


async def _fetch_csv(url: str) -> str:
    export = _to_csv_export_url(url)
    async with httpx.AsyncClient(follow_redirects=True, timeout=45.0) as client:
        resp = await client.get(export)
        resp.raise_for_status()
        # Google may return UTF-8 with BOM
        return resp.content.decode("utf-8-sig", errors="replace")


async def _load_price_list(*, force: bool = False) -> dict[str, Any]:
    now = time.time()
    ttl = float(settings.BESS_PRICE_CACHE_TTL_SEC)
    if not force and _CACHE["payload"] is not None and (now - float(_CACHE["ts"])) < ttl:
        return _CACHE["payload"]

    promo_url = settings.BESS_PROMO_SHEET_URL
    install_url = settings.BESS_INSTALL_SHEET_URL
    if not promo_url or not install_url:
        raise HTTPException(status_code=503, detail="BESS sheet URLs not configured")

    try:
        promo_text, install_text = await _fetch_csv(promo_url), await _fetch_csv(install_url)
    except Exception as exc:
        logger.exception("Failed to fetch BESS price sheets")
        if _CACHE["payload"] is not None:
            return _CACHE["payload"]
        raise HTTPException(status_code=502, detail=f"Failed to fetch price sheets: {exc}") from exc

    fx_promo, promo_items = _parse_sheet_csv(promo_text, kind="promo")
    fx_inst, install_items = _parse_sheet_csv(install_text, kind="install")
    fx = fx_promo or fx_inst or 45.3

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
            if row.get("installerUsd") is not None:
                existing["installerUsd"] = row["installerUsd"]
            if row.get("availabilityInstaller"):
                existing["availabilityInstaller"] = row["availabilityInstaller"]
            if not existing.get("brand") or existing.get("brand") == "other":
                existing["brand"] = row.get("brand") or existing.get("brand")

    # Deduplicate to unique articles for API response
    by_article: dict[str, dict[str, Any]] = {}
    for row in merged.values():
        art = (row.get("article") or "").strip()
        if not art:
            continue
        art_key = art.upper().replace(" ", "")
        if art_key in by_article:
            # Merge missing fields
            cur = by_article[art_key]
            for f in ("promoUsd", "promoVatUsd", "installerUsd", "availability", "availabilityInstaller"):
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
            "availability": row.get("availability") or "",
            "availabilityInstaller": row.get("availabilityInstaller") or "",
        }

    payload = {
        "fxRate": fx,
        "items": list(by_article.values()),
        "cachedAt": int(now),
        "ttlSec": int(ttl),
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
