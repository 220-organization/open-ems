"""Build a minimal .xlsx workbook of hourly DAM prices (stdlib zipfile, no Excel deps)."""

from __future__ import annotations

import zipfile
from collections import defaultdict
from datetime import date
from io import BytesIO
from typing import Iterable, Optional
from xml.sax.saxutils import escape

_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_ODREL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_ODREL_SHEET = f"{_NS_ODREL}/worksheet"
_NS_ODREL_DOC = f"{_NS_ODREL}/officeDocument"

_HOUR_LABELS: tuple[str, ...] = tuple(f"{h:02d}:00" for h in range(24))


def _col_letter(n: int) -> str:
    """1-based column index → Excel letters (1=A)."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _xml_text(value: str) -> str:
    return escape(value, {"'": "&apos;"})


def _num_xml(value: float) -> str:
    s = f"{value:.8f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _inline_str_cell(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{_xml_text(text)}</t></is></c>'


def _number_cell(ref: str, value: float) -> str:
    return f'<c r="{ref}" t="n"><v>{_num_xml(value)}</v></c>'


def _row_xml(r: int, cells: list[str]) -> str:
    return f'<row r="{r}">{"".join(cells)}</row>'


def build_hourly_dam_prices_xlsx(
    rows: Iterable[tuple[date, int, float]],
    *,
    year: int,
    market_label: str,
    zone_label: str,
    unit_label: str,
    price_scale: float = 0.001,
    sheet_name: str = "DAM prices",
) -> bytes:
    """
    Wide sheet: Date | 00:00 … 23:00 | Average.

    ``rows`` are (trade_day, period 1..24, native price e.g. UAH/MWh or EUR/MWh).
    ``price_scale`` converts native units to the exported unit (0.001 → per kWh).
    """
    by_day: dict[date, dict[int, float]] = defaultdict(dict)
    for trade_day, period, price in rows:
        p = int(period)
        if 1 <= p <= 24:
            by_day[trade_day][p] = float(price) * price_scale

    days = sorted(by_day)
    last_col = 26  # Date + 24 hours + Average
    last_letter = _col_letter(last_col)
    header_row = 6
    last_data_row = header_row + max(len(days), 1)
    dim = f"A1:{last_letter}{last_data_row}"

    sheet_rows: list[str] = [
        _row_xml(1, [_inline_str_cell("A1", "DAM prices"), _inline_str_cell("B1", market_label)]),
        _row_xml(2, [_inline_str_cell("A2", "Zone"), _inline_str_cell("B2", zone_label)]),
        _row_xml(3, [_inline_str_cell("A3", "Year"), _number_cell("B3", float(year))]),
        _row_xml(4, [_inline_str_cell("A4", "Unit"), _inline_str_cell("B4", unit_label)]),
        _row_xml(5, []),
    ]

    header_cells = [_inline_str_cell("A6", "Date")]
    for i, label in enumerate(_HOUR_LABELS, start=2):
        header_cells.append(_inline_str_cell(f"{_col_letter(i)}6", label))
    header_cells.append(_inline_str_cell(f"{_col_letter(last_col)}6", "Average"))
    sheet_rows.append(_row_xml(header_row, header_cells))

    if days:
        for idx, day in enumerate(days):
            r = header_row + 1 + idx
            hours = by_day[day]
            cells = [_inline_str_cell(f"A{r}", day.isoformat())]
            present: list[float] = []
            for p in range(1, 25):
                ref = f"{_col_letter(p + 1)}{r}"
                val = hours.get(p)
                if val is None:
                    continue
                cells.append(_number_cell(ref, val))
                present.append(val)
            if present:
                avg = sum(present) / len(present)
                cells.append(_number_cell(f"{_col_letter(last_col)}{r}", avg))
            sheet_rows.append(_row_xml(r, cells))
    else:
        sheet_rows.append(
            _row_xml(
                header_row + 1,
                [_inline_str_cell(f"A{header_row + 1}", "No prices in database for this year")],
            )
        )

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_NS_MAIN}">'
        f'<dimension ref="{dim}"/>'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        "</worksheet>"
    )

    safe_sheet = _xml_text(sheet_name[:31] or "DAM prices")
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{_NS_MAIN}" xmlns:r="{_NS_ODREL}">'
        f'<sheets><sheet name="{safe_sheet}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_NS_REL}">'
        f'<Relationship Id="rId1" Type="{_NS_ODREL_SHEET}" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_NS_REL}">'
        f'<Relationship Id="rId1" Type="{_NS_ODREL_DOC}" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{_NS_CT}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def dam_xlsx_filename(market: str, year: int, zone: Optional[str] = None) -> str:
    if market == "entsoe":
        z = (zone or "ES").upper()
        return f"dam-prices-entsoe-{z}-{year}.xlsx"
    return f"dam-prices-oree-{year}.xlsx"
