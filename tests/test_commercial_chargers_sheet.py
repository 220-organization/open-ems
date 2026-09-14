"""Unit tests for EDS retail sheet → commercial charger catalog parser."""

from __future__ import annotations

from pathlib import Path

from app.routers.commercial_chargers import parse_eds_price_csv

SAMPLE = """\
"EDS CHARGERS — роздрібні ціни","Модель (SKU)","Серія","кВт","Конфігурація","Артикул для завантаження в CRM","Ціна з ПДВ, €"
"1","EDS CHARGERS S80 UA (CCS+GBT)","S","80","2DC","EDS-S80-2DC","24 700"
"2","EDS CHARGERS S80 UA (CCS+GBT+AC+AC)","S","80","2DC+2AC","EDS-S80-2DC+2AC","27 800"
"3","EDS CHARGERS S80 UA (CCS+GBT+AC)","S","80","2DC+AC","EDS-S80-2DC+AC","26 100"
"18","EDS CHARGERS QS240 UA (CCS2+GB/T+CCS2)","QS","240","3DC","EDS-QS240-3DC","52 700"
"35","EDS CHARGERS Q240 UA (CCS2+GB/T+CCS2+GB/T)","Q","240","4DC","EDS-Q240-4DC","63 400"
"41","EDS CHARGERS SPLIT360 UA POWER UNIT на 12 кабелів (6 диспенсерів) до 500А","SPLIT","360","до 500А","EDS-SPLIT360-до 500А","60 000"
"47","EDS CHARGERS SPLIT UA DISPENSER STANDART (до 500А - peak) на 2 DC","DISPENSER","","2 DC (повітр.)","EDS-DISPENSER-2 DC (повітр.)","18 000"
"54","EDS CHARGERS SPLIT UA DISPENSER PRO (600А - regular, 700A - peak) на 2 DC","DISPENSER","","2 DC (рідин.)","EDS-DISPENSER-2 DC (рідин.)","26 000"
"*POWER UNIT limited to 2 dispensers can be cheaper"
"""


def test_parse_eds_price_csv_skus_and_facets():
    payload = parse_eds_price_csv(SAMPLE)
    assert payload["count"] == 8
    by_id = {p["id"]: p for p in payload["products"]}

    s80 = by_id["EDS-S80-2DC"]
    assert s80["series"] == "S"
    assert s80["family"] == "S80"
    assert s80["power_kw"] == 80.0
    assert s80["power_bucket"] == "upto160"
    assert s80["form"] == "single"
    assert s80["connectors"] == ["CCS2", "GB/T"]
    assert s80["ports"] == "2dc"
    assert s80["warranty_years"] == 3
    assert s80["warranty_downtime"] == "48h"
    assert s80["dedicated_manager"] is True
    assert s80["price"] == 24700.0
    assert s80["currency"] == "EUR"
    assert s80["image"]

    ac = by_id["EDS-S80-2DC+2AC"]
    assert "Type 2" in ac["connectors"]
    assert ac["ports"] == "2dc_2ac"
    assert ac["price"] == 27800.0

    ac1 = by_id["EDS-S80-2DC+AC"]
    assert ac1["ports"] == "2dc_ac"

    qs = by_id["EDS-QS240-3DC"]
    assert qs["series"] == "QS"
    assert qs["family"] == "QS240"
    assert qs["power_bucket"] == "200to320"
    assert qs["connectors"] == ["CCS2", "GB/T"]
    assert qs["ports"] == "3dc"

    q = by_id["EDS-Q240-4DC"]
    assert q["form"] == "dual"
    assert q["power_bucket"] == "200to320"
    assert q["ports"] == "4dc"

    split = by_id["EDS-SPLIT360-до 500А"]
    assert split["form"] == "split"
    assert split["cooling"] == "air"
    assert split["power_bucket"] == "360to480"
    assert split["ports"] is None
    assert split["image"] == "/static/commercial-chargers/split-hub.jpg"

    air = by_id["EDS-DISPENSER-2 DC (повітр.)"]
    assert air["series"] == "DISPENSER"
    assert air["power_kw"] is None
    assert air["power_bucket"] == "720plus"
    assert air["ports"] == "2dc"
    assert air["cooling"] == "air"
    assert air["price"] == 18000.0

    liquid = by_id["EDS-DISPENSER-2 DC (рідин.)"]
    assert liquid["cooling"] == "liquid"

    assert "S" in payload["facets"]["series"]
    assert payload["facets"]["ports"] == ["2dc", "2dc_ac", "2dc_2ac", "3dc", "4dc"]
    assert payload["facets"]["warranty_years"] == [1, 2, 3]
    assert payload["facets"]["warranty_downtime"] == ["48h", "5d", "10d"]
    assert payload["facets"]["dedicated_manager"] == [True, False]
    assert "CCS2" in payload["facets"]["connectors"]
    assert "air" in payload["facets"]["cooling"]
    assert payload["notes"]
    assert payload["facets"]["price_min"] == 18000.0
    assert payload["facets"]["price_max"] == 63400.0


def test_bundled_snapshot_parses_full_catalog():
    path = Path(__file__).resolve().parents[1] / "app" / "data" / "eds_commercial_chargers.csv"
    payload = parse_eds_price_csv(path.read_text(encoding="utf-8-sig"))
    assert payload["count"] == 54
    skus = {p["sku"] for p in payload["products"]}
    assert "EDS-QS240-2DC" in skus
    assert "EDS-Q480-4DC" in skus
    qs240_2dc = next(p for p in payload["products"] if p["sku"] == "EDS-QS240-2DC")
    assert qs240_2dc["price"] == 48800.0
    assert qs240_2dc["connectors"] == ["CCS2"]
    assert qs240_2dc["ports"] == "2dc"
    assert qs240_2dc["warranty_years"] == 3
    assert qs240_2dc["warranty_downtime"] == "48h"
    assert qs240_2dc["dedicated_manager"] is True
    assert payload["facets"]["ports"] == ["2dc", "2dc_ac", "2dc_2ac", "3dc", "4dc"]
    type2 = next(p for p in payload["products"] if p["sku"] == "EDS-S120-3DC+TYPE2")
    assert type2["ports"] == "3dc"
    split_hub = next(p for p in payload["products"] if p["sku"] == "EDS-SPLIT360-до 500А")
    assert split_hub["ports"] is None
