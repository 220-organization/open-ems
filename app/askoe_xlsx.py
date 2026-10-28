"""DTEK ASKOE hourly consumption workbook.

Layout matches the commercial export (hours down, days across, values in MWh):

    Розташування / Точка обліку / Канал обліку A+
    Серійний номер, then one column per calendar day
    00:00-01:00 … 23:00-24:00, Разом, Разом, загальне
"""

from __future__ import annotations

import zipfile
from datetime import date
from io import BytesIO
from typing import Optional
from xml.sax.saxutils import escape

# ASKOE A+ cells are megawatt-hours. Open EMS stores kilowatt-hours.
KWH_PER_MWH = 1000.0

HOUR_LABELS = tuple(
    f"{hour:02d}:00-{hour + 1:02d}:00" if hour < 23 else "23:00-24:00" for hour in range(24)
)

CHANNEL_A_PLUS = "A+ (Лічильник) Основн."


def kwh_to_mwh(kwh: Optional[float]) -> Optional[float]:
    if kwh is None:
        return None
    return float(kwh) / KWH_PER_MWH


def _col_letter(index: int) -> str:
    """1-based column index to Excel letters."""
    n = int(index)
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _cell_ref(col: int, row: int) -> str:
    return f"{_col_letter(col)}{row}"


def _text_cell(col: int, row: int, value: str) -> str:
    return (
        f'<c r="{_cell_ref(col, row)}" t="inlineStr"><is><t xml:space="preserve">'
        f"{escape(value)}</t></is></c>"
    )


def _number_cell(col: int, row: int, value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    if text in {"", "-", "-0"}:
        text = "0"
    return f'<c r="{_cell_ref(col, row)}"><v>{text}</v></c>'


def build_askoe_xlsx(
    *,
    serial: str,
    days: list[date],
    hourly_kwh: list[list[Optional[float]]],
    location: str = "Deye",
    point: str = "",
) -> bytes:
    """One sheet. ``hourly_kwh[day_index]`` is 24 Kyiv hours of consumption, kWh."""
    if len(hourly_kwh) != len(days):
        raise ValueError("hourly_kwh must have one row of hours per day")
    point_label = point or serial
    rows: list[str] = []

    def add_row(row_index: int, cells: list[str]) -> None:
        rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    add_row(1, [_text_cell(1, 1, "Розташування"), _text_cell(2, 1, location)])
    add_row(2, [_text_cell(1, 2, "Точка обліку"), _text_cell(2, 2, point_label)])
    add_row(3, [_text_cell(1, 3, "Канал обліку"), _text_cell(2, 3, CHANNEL_A_PLUS)])

    serial_cells = [_text_cell(1, 4, "Серійний номер")]
    date_cells = [_text_cell(1, 5, "Час \\\\ дата")]
    for index, day in enumerate(days):
        col = index + 2
        serial_cells.append(_text_cell(col, 4, serial))
        date_cells.append(_text_cell(col, 5, day.strftime("%d.%m.%Y")))
    add_row(4, serial_cells)
    add_row(5, date_cells)

    daily_totals: list[Optional[float]] = []
    for index, hours in enumerate(hourly_kwh):
        total = 0.0
        seen = False
        for value in hours[:24]:
            mwh = kwh_to_mwh(value)
            if mwh is None:
                continue
            total += mwh
            seen = True
        daily_totals.append(total if seen else None)

    for hour, label in enumerate(HOUR_LABELS):
        row_index = 6 + hour
        cells = [_text_cell(1, row_index, label)]
        for index, hours in enumerate(hourly_kwh):
            mwh = kwh_to_mwh(hours[hour] if hour < len(hours) else None)
            if mwh is None:
                continue
            cells.append(_number_cell(index + 2, row_index, mwh))
        add_row(row_index, cells)

    total_cells = [_text_cell(1, 30, "Разом")]
    for index, total in enumerate(daily_totals):
        if total is None:
            continue
        total_cells.append(_number_cell(index + 2, 30, total))
    add_row(30, total_cells)

    grand = sum(value for value in daily_totals if value is not None)
    grand_cells = [_text_cell(1, 31, "Разом, загальне")]
    if any(value is not None for value in daily_totals):
        grand_cells.append(_number_cell(2, 31, grand))
    add_row(31, grand_cells)

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(rows)}</sheetData></worksheet>"
    )
    start = days[0].strftime("%d.%m.%Y") if days else ""
    end = days[-1].strftime("%d.%m.%Y") if days else ""
    sheet_name = f"з {start} по {end}"[:31] or "ASKOE"
    return _pack_xlsx(sheet_name, sheet)


def _pack_xlsx(sheet_name: str, sheet_xml: str) -> bytes:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()
