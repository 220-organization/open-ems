"""Inject page-specific SEO meta into the CRA index.html for social crawlers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SITE = "https://220-km.com:9220"
_OG_IMAGE = f"{_SITE}/static/commercial-chargers-og.png"

COMMERCIAL_CHARGER_META: dict[str, dict[str, str]] = {
    "uk": {
        "title": "Комерційні зарядні станції — купити DC 40–960 кВт | OCPP | 220-km.com",
        "description": (
            "Купити комерційні зарядні станції DC 40–960 кВт: EDS, UGV, E-port, "
            "Infi Power, Eltis. OCPP 1.6J, тарифи РДН, монтаж і сервіс по Україні. "
            "Заявка — sales@220-km.com."
        ),
        "keywords": (
            "комерційні зарядні станції, купити DC зарядку, OCPP зарядна станція, "
            "EDS Chargers, UGV Chargers, E-port, Infi Power, Eltis, швидка зарядка EV, "
            "зарядка для бізнесу, 220-km.com"
        ),
        "og_title": "Комерційні зарядні станції DC — купити від 220-km.com | OCPP",
        "og_locale": "uk_UA",
        "canonical": f"{_SITE}/buy-commercial-charger",
        "og_image": _OG_IMAGE,
    },
    "en": {
        "title": "Commercial EV chargers — buy DC 40–960 kW | OCPP | 220-km.com",
        "description": (
            "Buy commercial DC chargers 40–960 kW: EDS, UGV, E-port, Infi Power, Eltis. "
            "OCPP 1.6J, DAM-linked tariffs, installation and service in Ukraine. "
            "Request — sales@220-km.com."
        ),
        "keywords": (
            "commercial EV chargers, buy DC charger, OCPP charging station, "
            "EDS Chargers, UGV Chargers, E-port, Infi Power, Eltis, fast EV charging, "
            "business charging, 220-km.com"
        ),
        "og_title": "Commercial DC EV chargers — buy from 220-km.com | OCPP",
        "og_locale": "en_US",
        "canonical": f"{_SITE}/buy-commercial-charger?lang=en",
        "og_image": _OG_IMAGE,
    },
    "es": {
        "title": "Cargadores comerciales EV — comprar DC 40–960 kW | OCPP | 220-km.com",
        "description": (
            "Compre cargadores DC comerciales 40–960 kW: EDS, UGV, E-port, Infi Power, Eltis. "
            "OCPP 1.6J, tarifas DAM, instalación y servicio en Ucrania. "
            "Solicitud — sales@220-km.com."
        ),
        "keywords": (
            "cargadores comerciales EV, comprar cargador DC, estación OCPP, "
            "EDS Chargers, UGV Chargers, E-port, Infi Power, Eltis, carga rápida EV, "
            "carga para empresas, 220-km.com"
        ),
        "og_title": "Cargadores DC comerciales EV — comprar en 220-km.com | OCPP",
        "og_locale": "es_ES",
        "canonical": f"{_SITE}/buy-commercial-charger?lang=es",
        "og_image": _OG_IMAGE,
    },
}


def commercial_charger_meta_for_lang(lang: str | None) -> dict[str, str]:
    key = (lang or "uk").lower()
    if key not in COMMERCIAL_CHARGER_META:
        key = "uk"
    return COMMERCIAL_CHARGER_META[key]


def _replace_title(html: str, title: str) -> str:
    return re.sub(
        r"<title>[^<]*</title>",
        f"<title>{title}</title>",
        html,
        count=1,
        flags=re.IGNORECASE,
    )


def _replace_named_meta(html: str, name: str, content: str) -> str:
    pattern = rf'(<meta\s+name="{re.escape(name)}"\s+content=")[^"]*(")'
    if re.search(pattern, html, flags=re.IGNORECASE):
        return re.sub(pattern, rf"\g<1>{content}\g<2>", html, count=1, flags=re.IGNORECASE)
    # Insert after <title> if missing
    return re.sub(
        r"(</title>)",
        rf'\1\n    <meta name="{name}" content="{content}" />',
        html,
        count=1,
        flags=re.IGNORECASE,
    )


def _replace_property_meta(html: str, prop: str, content: str) -> str:
    pattern = rf'(<meta\s+property="{re.escape(prop)}"\s+content=")[^"]*(")'
    if re.search(pattern, html, flags=re.IGNORECASE):
        return re.sub(pattern, rf"\g<1>{content}\g<2>", html, count=1, flags=re.IGNORECASE)
    return re.sub(
        r'(<meta\s+property="og:type"[^>]*>)',
        rf'\1\n    <meta property="{prop}" content="{content}" />',
        html,
        count=1,
        flags=re.IGNORECASE,
    )


def _replace_canonical(html: str, href: str) -> str:
    pattern = r'(<link\s+rel="canonical"\s+href=")[^"]*(")'
    if re.search(pattern, html, flags=re.IGNORECASE):
        return re.sub(pattern, rf"\g<1>{href}\g<2>", html, count=1, flags=re.IGNORECASE)
    return re.sub(
        r"(</title>)",
        rf'\1\n    <link rel="canonical" href="{href}" />',
        html,
        count=1,
        flags=re.IGNORECASE,
    )


def inject_spa_meta(html: str, meta: dict[str, Any]) -> str:
    """Replace title / description / OG / Twitter / canonical in CRA index HTML."""
    out = html
    title = meta["title"]
    description = meta["description"]
    og_title = meta.get("og_title") or title
    og_image = meta["og_image"]
    canonical = meta["canonical"]
    keywords = meta.get("keywords") or ""
    og_locale = meta.get("og_locale") or "uk_UA"

    out = _replace_title(out, title)
    out = _replace_named_meta(out, "description", description)
    if keywords:
        out = _replace_named_meta(out, "keywords", keywords)
    out = _replace_canonical(out, canonical)

    out = _replace_property_meta(out, "og:title", og_title)
    out = _replace_property_meta(out, "og:description", description)
    out = _replace_property_meta(out, "og:url", canonical)
    out = _replace_property_meta(out, "og:image", og_image)
    out = _replace_property_meta(out, "og:locale", og_locale)
    out = _replace_property_meta(out, "og:site_name", "220-km.com")

    out = _replace_named_meta(out, "twitter:title", og_title)
    out = _replace_named_meta(out, "twitter:description", description)
    out = _replace_named_meta(out, "twitter:image", og_image)
    out = _replace_named_meta(out, "twitter:card", "summary_large_image")
    return out


_index_cache: dict[str, Any] = {"mtime": None, "html": None}


def read_spa_index_html(index_path: Path) -> str:
    """Read CRA index.html, cached by mtime."""
    if not index_path.is_file():
        raise FileNotFoundError(str(index_path))
    mtime = index_path.stat().st_mtime
    if _index_cache["html"] is not None and _index_cache["mtime"] == mtime:
        return _index_cache["html"]
    html = index_path.read_text(encoding="utf-8")
    _index_cache["mtime"] = mtime
    _index_cache["html"] = html
    return html
