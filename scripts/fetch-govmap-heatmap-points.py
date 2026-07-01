#!/usr/bin/env python3
"""Download Ukraine gov EV charging sites map (Google My Maps) and export heatmap points JSON."""

from __future__ import annotations

import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ui/public/static/govmap-heatmap-points.json'
KML_URL = 'https://www.google.com/maps/d/kml?mid=152V-agzlIvSo9KH0MlIiu5OfGTrfp44&forcekml=1'
MAP_ID = '152V-agzlIvSo9KH0MlIiu5OfGTrfp44'
NS = {'kml': 'http://www.opengis.net/kml/2.2'}


def parse_kml_points(kml_bytes: bytes) -> list[dict[str, float]]:
    root = ET.fromstring(kml_bytes)
    seen: set[tuple[float, float]] = set()
    points: list[dict[str, float]] = []
    for pt in root.iter('{http://www.opengis.net/kml/2.2}Point'):
        coords = pt.find('kml:coordinates', NS)
        if coords is None or not coords.text:
            continue
        parts = coords.text.strip().split(',')
        if len(parts) < 2:
            continue
        lng, lat = float(parts[0]), float(parts[1])
        key = (round(lat, 5), round(lng, 5))
        if key in seen:
            continue
        seen.add(key)
        points.append({'lat': round(lat, 6), 'lng': round(lng, 6)})
    return points


def main() -> int:
    print(f'Fetching {KML_URL} ...')
    with urllib.request.urlopen(KML_URL, timeout=120) as resp:
        kml_bytes = resp.read()
    points = parse_kml_points(kml_bytes)
    if not points:
        print('No points parsed from KML', file=sys.stderr)
        return 1
    payload = {
        'source': 'govmap',
        'mapId': MAP_ID,
        'points': points,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote {len(points)} points to {OUT} ({OUT.stat().st_size} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
