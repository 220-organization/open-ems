#!/usr/bin/env python3
"""One-off: import E-port.energy.xlsx charging stations into static CSVs + photos.

Usage:
  python3 scripts/import_eport_xlsx.py [/path/to/E-port.energy.xlsx]
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XLSX = Path.home() / "Downloads" / "E-port.energy.xlsx"
HOME_CSV = ROOT / "app" / "data" / "eport_home_chargers.csv"
COMMERCIAL_CSV = ROOT / "app" / "data" / "eport_commercial_chargers.csv"
IMG_DIR = ROOT / "ui" / "public" / "static" / "chargers" / "eport"

# Section headers that start a product group (Ukrainian sheet titles).
_AC_SECTION_RE = re.compile(
    r"^Зарядн[іiїеe]+\s+станц[іiїяєїеe]+\s+(.+)$",
    re.I,
)
_DC_SECTION_RE = re.compile(r"TARY\s*\+\s*EPG\s*DC|EPG\s*DC", re.I)
_SKIP_SECTION_RE = re.compile(
    r"^(Аксесуари|Перехідники|Зарядні кабелі|Контролери|мережеві|"
    r"гібридн|навісн[іi]\s+гібридн|напольн|систем|акумулятор|"
    r"Commercial|Monitoring|комплект)",
    re.I,
)
_PRICE_RE = re.compile(r"([\d\s]+(?:[.,]\d+)?)")
_KW_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*(?:квт|кВт|kw)?", re.I)


def _slug(sku: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", (sku or "").strip(), flags=re.U)
    return re.sub(r"-+", "-", s).strip("-")[:80] or "item"


def _parse_price(raw) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).replace("\xa0", " ").replace("₴", "").strip()
    m = _PRICE_RE.search(s)
    if not m:
        return None
    num = m.group(1).replace(" ", "").replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def _parse_kw(raw) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    m = _KW_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _normalize_connector(raw: str) -> str:
    t = (raw or "").strip().lower().replace(" ", "")
    if not t:
        return ""
    if "ccs2" in t or t == "ccs":
        return "CCS2"
    if "gbt" in t or "gb/t" in t:
        return "GB/T"
    if "tesla" in t or "nacs" in t:
        return "NACS"
    if "type1" in t or t == "тип1":
        return "Type 1"
    if "type2" in t or "sockettype2" in t or "розеткаtype2" in t or "розеткатип2" in t:
        return "Type 2"
    if "socket" in t and "2" in t:
        return "Type 2"
    return (raw or "").strip()


def _brand_from_section(section: str) -> str:
    s = (section or "").strip()
    # Drop leading "Зарядні станції "
    m = _AC_SECTION_RE.match(s)
    name = m.group(1).strip() if m else s
    low = name.lower()
    if "wallbox" in low:
        return "Wallbox"
    if "besen" in low:
        return "Besen"
    if "wissenergy" in low:
        return "Wissenergy"
    if "rtfiy" in low:
        return "RTFIY"
    if "tary" in low or "epg" in low:
        # Prefer the product-line brand from SKU later; default TARY for section.
        return "TARY"
    return name.split()[0] if name else "E-port"


def _brand_from_sku(sku: str, section_brand: str) -> str:
    u = (sku or "").upper()
    if u.startswith("EVE") or "EPG" in u:
        return "EPG"
    if u.startswith(("PLP", "PPR", "PSP")):
        return "Wallbox"
    if u.startswith("BS") or u.startswith("BN") or u.startswith("SQ"):
        return "Besen"
    if u.startswith(("WB", "CC", "P60")):
        return "Wissenergy"
    if u.startswith("ST-"):
        return "RTFIY"
    if u.startswith("TA-") or u.startswith("TA ") or "TARY" in u:
        return "TARY"
    return section_brand


def _phases_for_ac(kw: float | None) -> int:
    if kw is not None and kw >= 11.0:
        return 3
    return 1


def _image_map(ws) -> dict[int, object]:
    """Map 0-based row index → first Image anchored on that row."""
    out: dict[int, object] = {}
    for img in getattr(ws, "_images", []) or []:
        try:
            anchor = img.anchor
            frm = getattr(anchor, "_from", None) or getattr(anchor, "from", None)
            if frm is None:
                continue
            row = int(frm.row)  # 0-based in openpyxl
            out.setdefault(row, img)
        except Exception:
            continue
    return out


def _save_image(img, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = img._data()
    ext = (getattr(img, "format", None) or "png").lower()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
        ext = "png"
    if ext == "jpeg":
        ext = "jpg"
    path = dest.with_suffix(f".{ext}")
    path.write_bytes(data)
    return f"/static/chargers/eport/{path.name}"


def _is_section_row(cols: list) -> str | None:
    """Return section title if this row is a section header, else None."""
    # Section rows typically have text in col B/C area and empty sku/price.
    texts = [str(c).strip() if c is not None else "" for c in cols]
    joined = " ".join(t for t in texts if t)
    if not joined:
        return None
    # Prefer first non-empty cell as title.
    title = next((t for t in texts if t), "")
    if _SKIP_SECTION_RE.search(title):
        return "__SKIP__"
    if _DC_SECTION_RE.search(title) or _DC_SECTION_RE.search(joined):
        return title
    if _AC_SECTION_RE.search(title):
        return title
    # Some headers omit "Зарядні станції" prefix variants already covered.
    return None


def _iter_product_rows(ws):
    """Yield (0based_row, cols) for all rows with any content."""
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        cols = list(row)
        if any(c not in (None, "") for c in cols):
            yield i, cols


def _extract_sku_title_type_power_price(cols: list) -> tuple | None:
    """Wallbox / portable sheets share layout:
    A=stock, B=photo, C=sku, D=title, E=length, F=type, G=power, H=RRP, I=cost
    """
    if len(cols) < 8:
        return None
    sku = str(cols[2]).strip() if cols[2] is not None else ""
    title = str(cols[3]).strip() if cols[3] is not None else ""
    if not sku or not title:
        return None
    # Skip section-like titles mistaken for products
    if _AC_SECTION_RE.search(sku) or _AC_SECTION_RE.search(title):
        return None
    if _SKIP_SECTION_RE.search(sku):
        return None
    cable = str(cols[4]).strip() if cols[4] is not None else ""
    type_raw = str(cols[5]).strip() if cols[5] is not None else ""
    power = _parse_kw(cols[6])
    price = _parse_price(cols[7])
    if price is None:
        return None
    return sku, title, cable, type_raw, power, price


def import_workbook(xlsx: Path) -> tuple[list[dict], list[dict]]:
    wb = load_workbook(xlsx, data_only=True)
    home: list[dict] = []
    commercial: list[dict] = []
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    sheet_specs = [
        # (sheet name substring, default kind)
        ("Wallbox", "ac"),
        ("Переносні", "ac"),
        ("навесні", "ac"),
    ]

    for ws in wb.worksheets:
        name = ws.title or ""
        if not any(s.lower() in name.lower() for s in ("wallbox", "переносн", "навесн", "besen")):
            continue
        if "growatt" in name.lower() or "перехідник" in name.lower() or "кабел" in name.lower():
            continue

        images = _image_map(ws)
        section = ""
        section_kind = "ac"
        seen_skus: set[str] = set()

        for row_idx, cols in _iter_product_rows(ws):
            sec = _is_section_row(cols)
            if sec == "__SKIP__":
                section = ""
                continue
            if sec:
                section = sec
                section_kind = "dc" if _DC_SECTION_RE.search(sec) else "ac"
                continue
            if not section:
                continue
            if _SKIP_SECTION_RE.search(section):
                continue

            parsed = _extract_sku_title_type_power_price(cols)
            if not parsed:
                continue
            sku, title, cable, type_raw, power, price = parsed
            # Deduplicate identical SKU within a sheet (e.g. WB20-7.2KW-APP twice for T2/GBT)
            # Keep both by suffixing connector when duplicate.
            connector = _normalize_connector(type_raw)
            sku_key = sku
            if sku_key in seen_skus:
                suffix = connector.replace(" ", "").replace("/", "") or "x"
                sku_key = f"{sku}-{suffix}"
            seen_skus.add(sku_key)

            brand = _brand_from_sku(sku, _brand_from_section(section))
            img_url = ""
            if row_idx in images:
                img_url = _save_image(images[row_idx], IMG_DIR / _slug(sku_key))

            is_dc = section_kind == "dc" or connector in ("CCS2",) or (
                power is not None and "DC" in title.upper() and power >= 20
            )
            # TARY/EPG section is DC even for GBT (DC GBT).
            if section_kind == "dc":
                is_dc = True

            row = {
                "sku": sku_key,
                "title": title,
                "brand": brand,
                "kind": "dc" if is_dc else "ac",
                "connector": connector,
                "power_kw": power if power is not None else "",
                "phases": "" if is_dc else _phases_for_ac(power),
                "cable": cable,
                "price_uah": price,
                "image": img_url,
            }
            if is_dc:
                commercial.append(row)
            else:
                home.append(row)

    return home, commercial


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "sku",
        "title",
        "brand",
        "kind",
        "connector",
        "power_kw",
        "phases",
        "cable",
        "price_uah",
        "image",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main(argv: list[str]) -> int:
    xlsx = Path(argv[1]) if len(argv) > 1 else DEFAULT_XLSX
    if not xlsx.is_file():
        print(f"missing workbook: {xlsx}", file=sys.stderr)
        return 1
    home, commercial = import_workbook(xlsx)
    _write_csv(HOME_CSV, home)
    _write_csv(COMMERCIAL_CSV, commercial)
    print(f"home={len(home)} -> {HOME_CSV}")
    print(f"commercial={len(commercial)} -> {COMMERCIAL_CSV}")
    print(f"images in {IMG_DIR}: {len(list(IMG_DIR.glob('*')))}")
    for r in commercial:
        print(" DC", r["sku"], r["power_kw"], r["price_uah"], r["connector"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
