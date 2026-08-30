"""Unit tests for Sparks merchant feed → home charger catalog parser."""

from __future__ import annotations

from app.routers.home_chargers import parse_merchant_rss

SAMPLE = """<?xml version='1.0' encoding='utf-8'?>
<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">
  <channel>
    <title>SPARKS</title>
    <item>
      <g:id>1</g:id>
      <g:title>Зарядна станція 22кВт Type 2</g:title>
      <g:description>Wallbox for Tesla and BMW</g:description>
      <g:link>https://sparkschargers.com.ua/ua/p1</g:link>
      <g:image_link>https://example.com/a.jpg</g:image_link>
      <g:availability>in stock</g:availability>
      <g:price>27000.00 UAH</g:price>
      <g:product_type>авто-, мото &gt; електромобільні зарядні пристрої та станції</g:product_type>
      <g:brand>SPARKS CHARGERS</g:brand>
      <g:product_detail>
        <g:attribute_name>Потужність</g:attribute_name>
        <g:attribute_value>22 кВт</g:attribute_value>
      </g:product_detail>
      <g:product_detail>
        <g:attribute_name>Кількість фаз</g:attribute_name>
        <g:attribute_value>3</g:attribute_value>
      </g:product_detail>
      <g:product_detail>
        <g:attribute_name>Тип роз'ємів</g:attribute_name>
        <g:attribute_value>Type 2</g:attribute_value>
      </g:product_detail>
    </item>
    <item>
      <g:id>2</g:id>
      <g:title>DYNATRAP mosquito trap</g:title>
      <g:description>комарі</g:description>
      <g:link>https://sparkschargers.com.ua/ua/p2</g:link>
      <g:image_link>https://example.com/b.jpg</g:image_link>
      <g:availability>in stock</g:availability>
      <g:price>650.00 UAH</g:price>
      <g:product_type>Товари для дому &gt; захист від комах</g:product_type>
      <g:brand>DYNATRAP</g:brand>
    </item>
  </channel>
</rss>
"""


def test_parse_merchant_rss_keeps_chargers_drops_mosquito():
    payload = parse_merchant_rss(SAMPLE)
    assert payload["count"] == 1
    p = payload["products"][0]
    assert p["id"] == "1"
    assert p["power_kw"] == 22.0
    assert p["phases"] == 3
    assert p["connectors"] == ["Type 2"]
    assert p["price"] == 27000.0
    assert p["currency"] == "UAH"
    assert p["power_bucket"] == "22plus"
    assert "Type 2" in payload["facets"]["connectors"]
    assert 3 in payload["facets"]["phases"]


def test_parse_merchant_rss_drops_adapters():
    xml = SAMPLE.replace(
        "Зарядна станція 22кВт Type 2",
        "Перехідник Type 2 на Type 1",
    ).replace(
        "<g:attribute_value>22 кВт</g:attribute_value>",
        "<g:attribute_value>7 кВт</g:attribute_value>",
    )
    # Keep product_type as charger category but title is adapter → excluded
    payload = parse_merchant_rss(xml)
    assert payload["count"] == 0
