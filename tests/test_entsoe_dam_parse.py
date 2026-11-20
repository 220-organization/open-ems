"""ENTSO-E day-ahead XML: sparse curves hold the previous price."""

from __future__ import annotations

import unittest

from app.entsoe_dam_service import parse_entsoe_price_points_xml

_NS = "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0"


def _doc(body: str) -> bytes:
    return (
        f'<Publication_MarketDocument xmlns="{_NS}">{body}</Publication_MarketDocument>'
    ).encode()


class TestEntsoeDamParse(unittest.TestCase):
    def test_sparse_hourly_curve_holds_previous_price(self) -> None:
        xml = _doc(
            """
            <TimeSeries>
              <currency><name>UAH</name></currency>
              <Period>
                <timeInterval>
                  <start>2025-11-20T22:00Z</start>
                  <end>2025-11-21T22:00Z</end>
                </timeInterval>
                <resolution>PT60M</resolution>
                <Point><position>1</position><price.amount>10</price.amount></Point>
                <Point><position>8</position><price.amount>20</price.amount></Point>
                <Point><position>12</position><price.amount>30</price.amount></Point>
                <Point><position>24</position><price.amount>40</price.amount></Point>
              </Period>
            </TimeSeries>
            """
        )
        err, hours, currency = parse_entsoe_price_points_xml(xml)
        self.assertIsNone(err)
        self.assertEqual(currency, "UAH")
        self.assertEqual(len(hours), 24)
        self.assertEqual(hours[1], 10)
        self.assertEqual(hours[7], 10)
        self.assertEqual(hours[8], 20)
        self.assertEqual(hours[11], 20)
        self.assertEqual(hours[12], 30)
        self.assertEqual(hours[23], 30)
        self.assertEqual(hours[24], 40)

    def test_sparse_quarter_hours_average_to_one_hour(self) -> None:
        xml = _doc(
            """
            <TimeSeries>
              <currency><name>EUR</name></currency>
              <Period>
                <timeInterval>
                  <start>2026-03-29T23:00Z</start>
                  <end>2026-03-30T22:00Z</end>
                </timeInterval>
                <resolution>PT15M</resolution>
                <Point><position>1</position><price.amount>4</price.amount></Point>
                <Point><position>3</position><price.amount>8</price.amount></Point>
                <Point><position>5</position><price.amount>12</price.amount></Point>
              </Period>
            </TimeSeries>
            """
        )
        err, hours, currency = parse_entsoe_price_points_xml(xml)
        self.assertIsNone(err)
        self.assertEqual(currency, "EUR")
        # Hour 1 slots 1..4: 4, 4, 8, 8
        self.assertEqual(hours[1], 6)
        # Hour 2 starts at slot 5 and holds through the rest of a 23h period.
        self.assertEqual(hours[2], 12)
        self.assertEqual(hours[23], 12)
        self.assertNotIn(24, hours)


if __name__ == "__main__":
    unittest.main()
