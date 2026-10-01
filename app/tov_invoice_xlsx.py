"""Payment invoice (.xlsx) for a TOV buyer, matching the FOP invoice layout."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_ODREL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_ODREL_SHEET = f"{_NS_ODREL}/worksheet"
_NS_ODREL_DOC = f"{_NS_ODREL}/officeDocument"
_KYIV = ZoneInfo("Europe/Kyiv")

_MONTHS_UA = (
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)

# Seller block from the issued FOP invoice template.
_SUPPLIER_NAME = "ФОП Павлов Максим Валерійович"
_SUPPLIER_DETAILS = (
    "Код РНОКПП: 3181213230\n"
    "Дата запису: 19.06.2018, Номер запису: 1 024 181 40084\n"
    "Адреса: 02098, м. Київ, пр-кт Соборності, буд. 17/2, кв. 2-92\n"
    "IBAN: UA563220010000026004300057390 в АТ «УНІВЕРСАЛ БАНК»\n"
    "МФО банку: 322001, ЄДРПОУ Банку: 21133352\n"
    "Email: maxpavlov.dp@gmail.com\n"
    "Платник єдиного податку 3 групи (без ПДВ)"
)
_ISSUED_BY = "Павлов Максим Валерійович"
_SERVICE_NAME = "Консультація по EMS + РДН"
_VALIDITY_NOTE = (
    "«Увага! Оплата цього рахунку означає погодження з обсягом, вартістю та умовами "
    "надання послуг. Рахунок дійсний до сплати протягом 3 (трьох) банківських днів "
    "з дати складання.»"
)


@dataclass(frozen=True)
class TovInvoiceBuyer:
    company_name: str
    details: str


def buyer_from_requisites(text: str) -> tuple[TovInvoiceBuyer, str]:
    """First line is the buyer name; the rest is printed as entered."""
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    lines = [line for line in lines if line]
    if len(lines) < 2 or len(lines[0]) < 2:
        raise ValueError("requisites")
    company = lines[0][:200]
    details = "\n".join(lines[1:])[:2000]
    if len(details) < 5:
        raise ValueError("requisites")
    edrpou = next(iter(re.findall(r"\d{8}", text)), "tov")
    return TovInvoiceBuyer(company_name=company, details=details), edrpou


def _xml_text(value: str) -> str:
    return escape(value, {"'": "&apos;"})


def _cell(ref: str, style: int | None = None, text: str | None = None, number: int | None = None) -> str:
    attrs = f' r="{ref}"'
    if style is not None:
        attrs += f' s="{style}"'
    if text is not None:
        body = escape(text).replace("\n", "&#10;")
        return f'<c{attrs} t="inlineStr"><is><t xml:space="preserve">{body}</t></is></c>'
    if number is not None:
        return f'<c{attrs}><v>{int(number)}</v></c>'
    return f'<c{attrs}/>'


def _sheet_row(r: int, cells: list[str], height: float | None = None, *, custom: bool = False) -> str:
    extras = ""
    if height is not None:
        extras += f' ht="{height}"'
        if custom:
            extras += ' customHeight="1"'
    return f'<row r="{r}"{extras} spans="1:11">{"".join(cells)}</row>'


def _blank_span(row: int, start: str, end: str, style: int) -> list[str]:
    start_i = ord(start) - ord("A")
    end_i = ord(end) - ord("A")
    return [_cell(f"{chr(ord('A') + i)}{row}", style) for i in range(start_i, end_i + 1)]


def _hryvnia_word(amount: int) -> str:
    n = abs(int(amount)) % 100
    if 11 <= n <= 14:
        return "гривень"
    last = n % 10
    if last == 1:
        return "гривня"
    if 2 <= last <= 4:
        return "гривні"
    return "гривень"


def _thousand_word(n: int) -> str:
    n = abs(int(n)) % 100
    if 11 <= n <= 14:
        return "тисяч"
    last = n % 10
    if last == 1:
        return "тисяча"
    if 2 <= last <= 4:
        return "тисячі"
    return "тисяч"


def _under_1000(n: int, *, feminine: bool) -> str:
    ones_m = (
        "",
        "один",
        "два",
        "три",
        "чотири",
        "п'ять",
        "шість",
        "сім",
        "вісім",
        "дев'ять",
    )
    ones_f = ("", "одна", "дві", *ones_m[3:])
    teens = (
        "десять",
        "одинадцять",
        "дванадцять",
        "тринадцять",
        "чотирнадцять",
        "п'ятнадцять",
        "шістнадцять",
        "сімнадцять",
        "вісімнадцять",
        "дев'ятнадцять",
    )
    tens = (
        "",
        "",
        "двадцять",
        "тридцять",
        "сорок",
        "п'ятдесят",
        "шістдесят",
        "сімдесят",
        "вісімдесят",
        "дев'яносто",
    )
    hundreds = (
        "",
        "сто",
        "двісті",
        "триста",
        "чотириста",
        "п'ятсот",
        "шістсот",
        "сімсот",
        "вісімсот",
        "дев'ятсот",
    )
    parts: list[str] = []
    if n >= 100:
        parts.append(hundreds[n // 100])
        n %= 100
    if n >= 20:
        parts.append(tens[n // 10])
        n %= 10
    elif n >= 10:
        parts.append(teens[n - 10])
        n = 0
    if n:
        parts.append((ones_f if feminine else ones_m)[n])
    return " ".join(p for p in parts if p)


def uah_amount_words(amount: int) -> str:
    """Whole hryvnias as a Ukrainian phrase, e.g. «дві тисячі двісті гривень 00 копійок»."""
    value = int(amount)
    if value < 0:
        raise ValueError("amount must be non-negative")
    thousands = value // 1000
    rest = value % 1000
    parts: list[str] = []
    if thousands:
        parts.append(_under_1000(thousands, feminine=True))
        parts.append(_thousand_word(thousands))
    if rest or not thousands:
        # «гривня» is feminine: одна / дві гривні.
        parts.append(_under_1000(rest, feminine=True) or "нуль")
    phrase = " ".join(parts)
    return f"{phrase} {_hryvnia_word(value)} 00 копійок"


def _format_money_ua(amount: int) -> str:
    grouped = f"{int(amount):,}".replace(",", " ")
    return f"{grouped},00"


def _invoice_date_ua(day: date) -> str:
    return f"{day.day} {_MONTHS_UA[day.month - 1]} {day.year} р."


def buyer_details_text(buyer: TovInvoiceBuyer) -> str:
    return buyer.details.strip()


def build_tov_invoice_xlsx(
    buyer: TovInvoiceBuyer,
    *,
    amount_uah: int,
    issued_on: date | None = None,
) -> bytes:
    """One-line service invoice: consultation amount, buyer requisites, no VAT."""
    day = issued_on or datetime.now(tz=_KYIV).date()
    amount = int(amount_uah)
    title = f"Рахунок на оплату №{day.strftime('%Y%m%d')} від {_invoice_date_ua(day)}"
    total_line = (
        f"Всього найменувань 1, на суму {_format_money_ua(amount)} грн.\n"
        f"{uah_amount_words(amount)[:1].upper()}{uah_amount_words(amount)[1:]}, без ПДВ"
    )
    company = buyer.company_name.strip()

    # Style ids match the FOP invoice template (fonts, borders, gray header, wrap).
    rows = [
        _sheet_row(
            2,
            [_cell("A2", 29, text=_VALIDITY_NOTE), *_blank_span(2, "B", "J", 20), _cell("K2", 21)],
            14.25,
            custom=True,
        ),
        _sheet_row(3, [*_blank_span(3, "A", "J", 20), _cell("K3", 21)], 14.25, custom=True),
        _sheet_row(4, [*_blank_span(4, "A", "J", 20), _cell("K4", 21)], 14.25, custom=True),
        _sheet_row(
            5,
            [_cell("A5", 39, text=title), *_blank_span(5, "B", "J", 20), _cell("K5", 21)],
            31.5,
            custom=True,
        ),
        _sheet_row(6, [], 9.75, custom=True),
        _sheet_row(
            7,
            [
                _cell("A7", 25, text="Постачальник:"),
                _cell("B7", 20),
                _cell("C7", 19, text=_SUPPLIER_NAME),
                *_blank_span(7, "D", "J", 20),
                _cell("K7", 21),
            ],
            24,
            custom=True,
        ),
        _sheet_row(
            9,
            [_cell("C9", 35, text=_SUPPLIER_DETAILS), *_blank_span(9, "D", "J", 20), _cell("K9", 21)],
            99.95,
            custom=True,
        ),
        _sheet_row(
            11,
            [
                _cell("A11", 25, text="Замовник (Покупець):"),
                _cell("B11", 20),
                _cell("C11", 26, text=company),
                *_blank_span(11, "D", "J", 20),
                _cell("K11", 21),
            ],
            21,
            custom=True,
        ),
        _sheet_row(12, _blank_span(12, "C", "K", 2), 14.25, custom=True),
        _sheet_row(
            13,
            [_cell("C13", 36, text=buyer_details_text(buyer)), *_blank_span(13, "D", "J", 20), _cell("K13", 21)],
            75,
            custom=True,
        ),
        _sheet_row(14, [*_blank_span(14, "C", "J", 20), _cell("K14", 21)], 57.75, custom=True),
        _sheet_row(
            16,
            [
                _cell("A16", 25, text="Платник:"),
                _cell("B16", 20),
                _cell("C16", 19, text=f"той самий ({company})"),
                *_blank_span(16, "D", "J", 20),
                _cell("K16", 21),
            ],
            15,
            custom=True,
        ),
        _sheet_row(
            18,
            [
                _cell("A18", 12, text="№"),
                _cell("B18", 38, text="Товари (роботи, послуги)"),
                *_blank_span(18, "C", "G", 23),
                _cell("H18", 13, text="Кіл-сть"),
                _cell("I18", 14, text="Од."),
                _cell("J18", 15, text="Ціна без ПДВ"),
                _cell("K18", 15, text="Сума без ПДВ"),
            ],
            27.75,
            custom=True,
        ),
        _sheet_row(
            19,
            [
                _cell("A19", 16, number=1),
                _cell("B19", 22, text=_SERVICE_NAME),
                *_blank_span(19, "C", "F", 23),
                _cell("G19", 24),
                _cell("H19", 11, number=1),
                _cell("I19", 10, text="послуга"),
                _cell("J19", 7, number=amount),
                _cell("K19", 7, number=amount),
            ],
            15,
        ),
        _sheet_row(
            20,
            [
                _cell("A20", 17),
                _cell("B20", 22),
                *_blank_span(20, "C", "F", 23),
                _cell("G20", 24),
                _cell("H20", 10),
                _cell("I20", 8),
                _cell("J20", 9),
                _cell("K20", 7),
            ],
            15,
        ),
        _sheet_row(22, [_cell("J22", 18, text="Разом до сплати:"), _cell("K22", 7, number=amount)], 15),
        _sheet_row(
            26,
            [_cell("B26", 30, text=total_line), *_blank_span(26, "C", "K", 31)],
            32,
            custom=True,
        ),
        _sheet_row(30, [_cell("B30", 33), *_blank_span(30, "C", "K", 34)], 15, custom=True),
        _sheet_row(32, [_cell("H32", 32, text="Виписав:"), _cell("I32", 20)], 15, custom=True),
        _sheet_row(33, [_cell("J33", 37), _cell("K33", 31)], 15),
        _sheet_row(34, [_cell("J34", 27, text=_ISSUED_BY), _cell("K34", 28)], 15),
    ]
    merges = (
        "A2:K4",
        "A5:K5",
        "A7:B7",
        "C7:K7",
        "C9:K9",
        "A11:B11",
        "C11:K11",
        "C13:K14",
        "A16:B16",
        "C16:K16",
        "B18:G18",
        "B19:G19",
        "B20:G20",
        "B26:K26",
        "B30:K30",
        "H32:I32",
        "J33:K33",
        "J34:K34",
    )
    merge_xml = "".join(f'<mergeCell ref="{ref}"/>' for ref in merges)
    cols = (
        '<cols>'
        '<col min="1" max="1" width="6" style="1" customWidth="1"/>'
        '<col min="2" max="2" width="19.5703125" style="1" customWidth="1"/>'
        '<col min="3" max="7" width="9.140625" style="1" customWidth="1"/>'
        '<col min="8" max="8" width="8" style="1" customWidth="1"/>'
        '<col min="9" max="9" width="11" style="1" customWidth="1"/>'
        '<col min="10" max="10" width="17.140625" style="1" customWidth="1"/>'
        '<col min="11" max="11" width="16.5703125" style="3" customWidth="1"/>'
        "</cols>"
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_NS_MAIN}">'
        '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>'
        '<dimension ref="A2:K34"/>'
        '<sheetViews><sheetView workbookViewId="0" showGridLines="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="14.25"/>'
        f"{cols}"
        f'<sheetData>{"".join(rows)}</sheetData>'
        f'<mergeCells count="{len(merges)}">{merge_xml}</mergeCells>'
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
        '<pageSetup paperSize="9" orientation="portrait" fitToWidth="1" fitToHeight="1"/>'
        "</worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{_NS_MAIN}" xmlns:r="{_NS_ODREL}">'
        f'<sheets><sheet name="{_xml_text("Рахунок")}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_NS_REL}">'
        f'<Relationship Id="rId1" Type="{_NS_ODREL_SHEET}" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{_NS_ODREL}/styles" Target="styles.xml"/>'
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
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    styles_xml = (Path(__file__).with_name("tov_invoice_styles.xml")).read_text(encoding="utf-8")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr("xl/worksheets/sheet1.xml", worksheet)
    return buf.getvalue()
