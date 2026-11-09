#!/usr/bin/env python3
"""Import EPG Commercial pricelist 2026 into home + commercial E-port CSVs.

Routing:
  - power < 40 kW and no OCPP → eport_home_chargers.csv (home page)
  - OCPP or power >= 40 kW → eport_commercial_chargers.csv (business page)

Usage:
  python3 scripts/import_epg_commercial_xlsx.py [path/to/Commercial\\ pricelist\\ 2026V6\\ EPG.xlsx]
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XLSX = (
    Path.home()
    / "Downloads"
    / "Telegram Desktop"
    / "Commercial pricelist 2026V6 EPG.xlsx"
)
COMMERCIAL_CSV = ROOT / "app" / "data" / "eport_commercial_chargers.csv"
HOME_CSV = ROOT / "app" / "data" / "eport_home_chargers.csv"
IMG_DIR = ROOT / "ui" / "public" / "static" / "chargers" / "eport"
OUT_CSV = COMMERCIAL_CSV  # backward-compatible alias

_KW_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*(?:квт|кВт|kw)?", re.I)
_SECTION_SKIP = re.compile(r"вулична\s+стійка|комплектуються", re.I)


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", (s or "").strip(), flags=re.U)
    return re.sub(r"-+", "-", s).strip("-")[:90] or "item"


def _parse_kw(raw) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    m = _KW_RE.search(str(raw))
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def _parse_price(raw) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).replace("\xa0", " ").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _norm_conn(raw: str) -> str:
    t = (raw or "").strip().upper().replace(" ", "")
    if not t:
        return ""
    if t in ("GBT", "GB/T", "GB\\T"):
        return "GB/T"
    if t in ("CCS2", "CCS"):
        return "CCS2"
    if t in ("CCS1",):
        return "CCS1"
    if t in ("NACS", "TESLA"):
        return "NACS"
    if t in ("CHADEMO", "CHAdeMO".upper()):
        return "CHAdeMO"
    if "CCS2" in t and "GBT" in t:
        return "CCS2+GB/T"
    return (raw or "").strip()


def _connectors_list(raw: str) -> list[str]:
    """Split CCS2-GBT / CCS2+GBT / single tokens."""
    s = (raw or "").strip()
    if not s:
        return []
    if "-" in s and "+" not in s and not s.upper().startswith("EPG"):
        # CCS2-GBT style
        parts = re.split(r"[-/]", s)
    else:
        parts = re.split(r"[+/|]", s)
    out: list[str] = []
    for p in parts:
        n = _norm_conn(p)
        if n and n not in out:
            # Flatten accidental CCS2+GB/T single token
            if n == "CCS2+GB/T":
                for x in ("CCS2", "GB/T"):
                    if x not in out:
                        out.append(x)
            else:
                out.append(n)
    return out


def _ports_for(connectors: list[str], form: str) -> str:
    n = len(connectors)
    if form == "split":
        return ""  # power cabinet — no vehicle ports
    if n >= 2:
        return "2dc"
    return "1dc"


def _parse_ocpp(raw) -> bool:
    s = str(raw or "").strip().lower()
    return s in ("так", "yes", "true", "1", "y", "+")


def _catalog_for(power: float | None, ocpp: bool) -> str:
    """Home if under 40 kW without OCPP; otherwise business."""
    if power is not None and power < 40 and not ocpp:
        return "home"
    return "business"


def _save_section_images(ws) -> dict[str, str]:
    """Map section title keywords → saved image URL (first image near section)."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    # Collect images by row
    by_row: dict[int, object] = {}
    for img in getattr(ws, "_images", []) or []:
        try:
            by_row[int(img.anchor._from.row)] = img
        except Exception:
            continue

    # Section header rows → nearest image at or above
    section_imgs: dict[str, str] = {}
    section_rows = {
        "wall20": 7,
        "portable20": 14,
        "commercial_wall": 21,
        "commercial_street": 29,
        "split": 38,
        "dispenser": 46,
    }
    for key, row in section_rows.items():
        img = by_row.get(row) or by_row.get(row - 1) or by_row.get(row + 1)
        if not img:
            # walk up
            for r in range(row, -1, -1):
                if r in by_row:
                    img = by_row[r]
                    break
        if not img:
            continue
        path = IMG_DIR / f"epg-{key}"
        data = img._data()
        ext = (getattr(img, "format", None) or "png").lower()
        if ext == "jpeg":
            ext = "jpg"
        if ext not in ("png", "jpg", "gif", "webp"):
            ext = "png"
        out = path.with_suffix(f".{ext}")
        out.write_bytes(data)
        section_imgs[key] = f"/static/chargers/eport/{out.name}"
    return section_imgs


def _title(base: str, connectors: list[str], mount: str, form: str, kw: float | None) -> str:
    conn = "+".join(connectors) if connectors else ""
    kw_s = f"{int(kw) if kw and kw == int(kw) else kw} кВт" if kw is not None else ""
    mount_uk = {
        "Wall": "навісна",
        "Portable": "переносна",
        "Street": "вулична",
    }.get(mount, mount.lower() if mount else "")
    if form == "split":
        return f"EPG силовий блок {kw_s} (спліт)".strip()
    if form == "dispenser":
        return f"EPG диспенсер {kw_s} {conn}".strip()
    bits = ["EPG", mount_uk, "DC", kw_s]
    if conn:
        bits.append(conn)
    return " ".join(b for b in bits if b)


def import_epg(xlsx: Path) -> list[dict]:
    wb = load_workbook(xlsx, data_only=True)
    ws = wb["EPG-DC"] if "EPG-DC" in wb.sheetnames else wb.worksheets[0]
    section_imgs = _save_section_images(ws)

    rows_out: list[dict] = []
    section = ""
    section_key = ""
    form = "single"

    for row in ws.iter_rows(values_only=True):
        cols = list(row)
        a = str(cols[1]).strip() if len(cols) > 1 and cols[1] is not None else ""
        if not a:
            continue
        if _SECTION_SKIP.search(a):
            continue
        low = a.lower()
        if "домашні навісні" in low:
            section, section_key, form = "home_wall", "wall20", "single"
            continue
        if "домашні переносні" in low:
            section, section_key, form = "home_portable", "portable20", "single"
            continue
        if "комерційні" in low and "швидкісн" in low:
            # Distinguish wall block vs street by next product mount; set generic for now
            section, section_key, form = "commercial", "commercial_wall", "single"
            continue
        if "силові блоки" in low or "спліт-система" in low and "диспансер" not in low:
            if "силові" in low:
                section, section_key, form = "split", "split", "split"
                continue
        if a.startswith("Диспансер") or "диспансер (спліт" in low:
            section, section_key, form = "dispenser", "dispenser", "dispenser"
            continue
        if a in ("Тип",) or a.startswith("Тип"):
            continue
        if not section:
            continue
        if not a.upper().startswith("EPG"):
            continue

        # Layout differs by section
        ocpp = False
        if form == "split":
            # Тип | Потужність | empty | empty | mount | empty | dispensers | size | price
            sku_base = a
            power = _parse_kw(cols[2] if len(cols) > 2 else None)
            mount = str(cols[5]).strip() if len(cols) > 5 and cols[5] else "Street"
            price = _parse_price(cols[9] if len(cols) > 9 else None)
            connectors: list[str] = []
            conn_raw = ""
            ocpp = True  # split cabinets are commercial infrastructure
        elif form == "dispenser":
            # Тип | Потужність | Conn1 | Conn2 | mount | empty | current | size | price
            sku_base = a
            power = _parse_kw(cols[2] if len(cols) > 2 else None)
            c1 = _norm_conn(str(cols[3]) if len(cols) > 3 and cols[3] else "")
            c2 = _norm_conn(str(cols[4]) if len(cols) > 4 and cols[4] else "")
            connectors = [c for c in (c1, c2) if c]
            conn_raw = "+".join(connectors)
            mount = str(cols[5]).strip() if len(cols) > 5 and cols[5] else "Street"
            price = _parse_price(cols[9] if len(cols) > 9 else None)
            ocpp = True  # dispensers are commercial
        else:
            # Тип | APP/share | connector | power | mount | OCPP | size | price at col 9
            sku_base = a
            conn_raw = str(cols[3]).strip() if len(cols) > 3 and cols[3] else ""
            connectors = _connectors_list(conn_raw)
            power = _parse_kw(cols[4] if len(cols) > 4 else None)
            mount = str(cols[5]).strip() if len(cols) > 5 and cols[5] else ""
            ocpp = _parse_ocpp(cols[7] if len(cols) > 7 else None)
            price = _parse_price(cols[9] if len(cols) > 9 else None)
            # Street commercial section — update section image key when mount is Street
            if mount == "Street" and section == "commercial":
                section_key = "commercial_street"

        if price is None or power is None:
            continue

        # Unique SKU
        suffix_parts = []
        if mount:
            suffix_parts.append(mount)
        if connectors:
            suffix_parts.append("-".join(c.replace("/", "") for c in connectors))
        elif conn_raw:
            suffix_parts.append(_slug(conn_raw))
        sku = sku_base if not suffix_parts else f"{sku_base}-{'/'.join(suffix_parts)}"
        # Prefer hyphen slug without slash
        sku = sku.replace("/", "-").replace(" ", "")

        ports = _ports_for(connectors, form)
        image = section_imgs.get(section_key, "")
        title = _title(sku_base, connectors, mount, form, power)
        catalog = _catalog_for(power, ocpp)

        rows_out.append(
            {
                "sku": sku,
                "title": title,
                "brand": "EPG",
                "kind": "dc",
                "connector": "+".join(connectors) if connectors else conn_raw,
                "power_kw": power,
                "phases": "",
                "cable": "",
                "price_uah": price,
                "image": image,
                "form": form,
                "ports": ports,
                "mount": mount,
                "ocpp": "1" if ocpp else "0",
                "catalog": catalog,
            }
        )

    return rows_out


def _load_home_ac_rows(path: Path) -> list[dict]:
    """Keep existing AC home rows; drop previous EPG DC imports."""
    if not path.is_file():
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sku = (row.get("sku") or "").strip()
            if not sku:
                continue
            if sku.upper().startswith("EPG-"):
                continue
            out.append(row)
    return out


def _home_row(r: dict) -> dict:
    return {
        "sku": r["sku"],
        "title": r["title"],
        "brand": "E-port",
        "kind": "charger",
        "connector": r.get("connector") or "",
        "power_kw": r.get("power_kw") or "",
        "phases": "",
        "cable": r.get("cable") or "",
        "price_uah": r.get("price_uah") or "",
        "image": r.get("image") or "",
    }


def main(argv: list[str]) -> int:
    xlsx = Path(argv[1]) if len(argv) > 1 else DEFAULT_XLSX
    if not xlsx.is_file():
        print(f"missing: {xlsx}", file=sys.stderr)
        return 1
    epg = import_epg(xlsx)
    home_epg = [r for r in epg if r.get("catalog") == "home"]
    biz_epg = [r for r in epg if r.get("catalog") != "home"]

    biz_fields = [
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
        "form",
        "ports",
        "mount",
        "ocpp",
    ]
    COMMERCIAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    with COMMERCIAL_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=biz_fields, extrasaction="ignore")
        w.writeheader()
        for r in biz_epg:
            w.writerow(r)

    home_fields = [
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
    home_rows = _load_home_ac_rows(HOME_CSV) + [_home_row(r) for r in home_epg]
    with HOME_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=home_fields, extrasaction="ignore")
        w.writeheader()
        for r in home_rows:
            w.writerow({k: r.get(k, "") for k in home_fields})

    print(
        f"wrote {len(biz_epg)} business -> {COMMERCIAL_CSV}; "
        f"{len(home_epg)} home EPG (+{len(home_rows) - len(home_epg)} AC) -> {HOME_CSV}"
    )
    for r in home_epg:
        print(f"  HOME {r['sku']}: {r['power_kw']}kW ocpp={r['ocpp']} {r['price_uah']} UAH")
    for r in biz_epg:
        print(
            f"  BIZ  {r['sku']}: {r['power_kw']}kW ocpp={r['ocpp']} "
            f"{r['form']} {r['price_uah']} UAH"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
