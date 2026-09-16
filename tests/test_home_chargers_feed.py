"""Unit tests for Sparks PROM sheet → home charger catalog parser."""

from __future__ import annotations

from pathlib import Path

from app.routers.home_chargers import parse_prom_csv

SAMPLE = """\
Код_товару,Назва_позиції,Назва_позиції_укр,Опис,Опис_укр,Тип_товару,Ціна,Валюта,Посилання_зображення,Наявність,Унікальний_ідентифікатор,Виробник,Країна_виробник,Продукт_на_сайті,Назва_Характеристики,Одиниця_виміру_Характеристики,Значення_Характеристики,Назва_Характеристики,Одиниця_виміру_Характеристики,Значення_Характеристики,Назва_Характеристики,Одиниця_виміру_Характеристики,Значення_Характеристики
,Зарядная станция 22кВт Type 2,Зарядна станція 22кВт Type 2,Wallbox,<p>Wallbox for Tesla and BMW</p>,r,550,USD,https://example.com/a.jpg,+,1,SPARKS CHARGERS,Польща,https://sparkschargers.com.ua/ua/p1,Потужність,кВт,22,Кількість фаз,,3,Тип роз'ємів,,Type 2
,Переходник Type 2 на Type 1,Перехідник Type 2 на Type 1,adapter,adapter,r,1600,UAH,https://example.com/b.jpg,+,2,Besen,Китай,https://sparkschargers.com.ua/ua/p2,Потужність,кВт,7,Кількість фаз,,1,Тип роз'ємів,,Type 2 на Type 1
,Зарядный кабель Type 2,Зарядний кабель для електромобіля 7.4 кВт TYPE 2,cable,cable,r,6300,UAH,https://example.com/c.jpg,+,3,SPARKS CHARGERS,Польща,https://sparkschargers.com.ua/ua/p3,Потужність,кВт,7.4,Кількість фаз,,1,Тип роз'ємів,,Type 2
,Зарядка Tesla USA,Зарядний пристрій SPARKS Tesla USA (набір зарядний + адаптер) 3.7 кВт,kit,kit,r,320,USD,https://example.com/d.jpg,+,4,SPARKS CHARGERS,Польща,https://sparkschargers.com.ua/ua/p4,Потужність,,"3,7 кВт",Кількість фаз,,1,Тип роз'ємів,,Tesla USA
"""


def test_parse_prom_csv_keeps_chargers_adapters_and_cables():
    payload = parse_prom_csv(SAMPLE)
    assert payload["count"] == 4
    by_id = {p["id"]: p for p in payload["products"]}

    wallbox = by_id["1"]
    assert wallbox["kind"] == "charger"
    assert wallbox["power_kw"] == 22.0
    assert wallbox["phases"] == 3
    assert wallbox["connectors"] == ["Type 2"]
    assert wallbox["price"] == 550.0
    assert wallbox["currency"] == "USD"
    assert wallbox["power_bucket"] == "22plus"
    assert wallbox["availability"] == "in stock"
    assert wallbox["description"] == "Wallbox for Tesla and BMW"
    assert "Type 2" in payload["facets"]["connectors"]
    assert 3 in payload["facets"]["phases"]
    assert payload["facets"]["kinds"] == ["charger", "adapter", "cable"]

    adapter = by_id["2"]
    assert adapter["kind"] == "adapter"
    assert adapter["power_bucket"] is None
    assert adapter["connectors"] == ["Type 2", "Type 1"]
    assert adapter["price"] == 1600.0
    assert adapter["currency"] == "UAH"

    cable = by_id["3"]
    assert cable["kind"] == "cable"
    assert cable["power_bucket"] is None
    assert cable["connectors"] == ["Type 2"]

    kit = by_id["4"]
    assert kit["kind"] == "charger"
    assert kit["connectors"] == ["NACS"]
    assert kit["power_kw"] == 3.7
    assert kit["power_bucket"] == "upto4"
    assert kit["currency"] == "USD"


def test_bundled_snapshot_includes_adapters_and_cables():
    path = Path(__file__).resolve().parents[1] / "app" / "data" / "sparks_home_chargers.csv"
    payload = parse_prom_csv(path.read_text(encoding="utf-8-sig"))
    assert payload["count"] == 24
    assert payload["source"] == "sparkschargers.com.ua"
    by_id = {p["id"]: p for p in payload["products"]}
    assert by_id["1899560129"]["kind"] == "charger"  # 22 kW Type 2 station
    assert by_id["2608979477"]["kind"] == "charger"  # LADERGY 22 kW
    assert by_id["2373289399"]["kind"] == "adapter"  # Type 2 → NACS
    assert by_id["2526039893"]["kind"] == "cable"  # Type 2 cable
    assert by_id["2373289399"]["power_bucket"] is None
    assert "CCS2" in payload["facets"]["connectors"]
    assert payload["facets"]["kinds"] == ["charger", "adapter", "cable"]
    brands = payload["facets"]["brands"]
    assert "SPARKS CHARGERS" in brands
    assert "LADERGY" in brands
    assert "NACS" in payload["facets"]["connectors"]
    assert "Type 2" in payload["facets"]["connectors"]
    wallbox = by_id["1899560129"]
    assert wallbox["power_kw"] == 22.0
    assert wallbox["phases"] == 3
    assert wallbox["price"] == 550.0
    assert wallbox["currency"] == "USD"
    assert wallbox["link"].startswith("https://sparkschargers.com.ua/")
    assert wallbox["image"].startswith("https://")
    assert set(payload["facets"]["power_buckets"]) <= {"upto4", "7to8", "11", "22plus"}
    assert "22plus" in payload["facets"]["power_buckets"]
