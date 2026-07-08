"""Major Ukrainian cities for trip origin/destination snapping (lat, lon, name)."""

from __future__ import annotations

import math
from typing import Optional

# ~100 cities; name is Latin for open-data API stability.
UKRAINIAN_CITIES: list[tuple[str, float, float]] = [
    ("Kyiv", 50.4501, 30.5234),
    ("Kharkiv", 49.9935, 36.2304),
    ("Odesa", 46.4825, 30.7233),
    ("Dnipro", 48.4647, 35.0462),
    ("Lviv", 49.8397, 24.0297),
    ("Zaporizhzhia", 47.8388, 35.1396),
    ("Kryvyi Rih", 47.9105, 33.3918),
    ("Mykolaiv", 46.9750, 31.9946),
    ("Vinnytsia", 49.2328, 28.4682),
    ("Poltava", 49.5883, 34.5514),
    ("Chernihiv", 51.4982, 31.2893),
    ("Cherkasy", 49.4444, 32.0598),
    ("Zhytomyr", 50.2547, 28.6587),
    ("Sumy", 50.9077, 34.7981),
    ("Rivne", 50.6199, 26.2516),
    ("Ivano-Frankivsk", 48.9226, 24.7111),
    ("Ternopil", 49.5535, 25.5948),
    ("Lutsk", 50.7472, 25.3254),
    ("Uzhhorod", 48.6208, 22.2879),
    ("Khmelnytskyi", 49.4229, 26.9871),
    ("Chernivtsi", 48.2915, 25.9403),
    ("Kropyvnytskyi", 48.5079, 32.2623),
    ("Kherson", 46.6354, 32.6169),
    ("Mariupol", 47.0951, 37.5413),
    ("Melitopol", 46.8478, 35.3674),
    ("Simferopol", 44.9521, 34.1024),
    ("Sevastopol", 44.6167, 33.5254),
    ("Bila Tserkva", 49.8094, 30.1121),
    ("Brovary", 50.5181, 30.8066),
    ("Irpin", 50.5218, 30.2505),
    ("Bucha", 50.5434, 30.2120),
    ("Fastiv", 50.0767, 29.9177),
    ("Vyshhorod", 50.5833, 30.4833),
    ("Uman", 48.7500, 30.2167),
    ("Kamianets-Podilskyi", 48.6845, 26.5856),
    ("Kremenchuk", 49.0685, 33.4104),
    ("Konotop", 51.2403, 33.2029),
    ("Shostka", 51.8730, 33.4697),
    ("Berdiansk", 46.7547, 36.7987),
    ("Nikopol", 47.5681, 34.3963),
    ("Pavlohrad", 48.5342, 35.8708),
    ("Kamianske", 48.5167, 34.6167),
    ("Sloviansk", 48.8575, 37.6081),
    ("Kramatorsk", 48.7231, 37.5564),
    ("Sievierodonetsk", 48.9482, 38.4917),
    ("Lysychansk", 48.9047, 38.4420),
    ("Rubizhne", 49.0100, 38.3792),
    ("Mukachevo", 48.4432, 22.7178),
    ("Kovel", 51.2089, 24.7056),
    ("Drohobych", 49.3490, 23.5056),
    ("Stryi", 49.2620, 23.8561),
    ("Kolomyia", 48.5300, 25.0400),
    ("Kalush", 49.0239, 24.3722),
    ("Chortkiv", 49.0172, 25.7981),
    ("Korosten", 50.9594, 28.6386),
    ("Novohrad-Volynskyi", 50.5942, 27.6164),
    ("Berdychiv", 49.8944, 28.6028),
    ("Zhovkva", 50.0581, 23.9728),
    ("Yavoriv", 49.9386, 23.3825),
    ("Sambir", 49.5183, 23.1972),
    ("Truskavets", 49.2783, 23.5061),
    ("Dubno", 50.4167, 25.7500),
    ("Kostopil", 50.8786, 26.4517),
    ("Varash", 51.3533, 25.8517),
    ("Shepetivka", 50.1850, 27.0636),
    ("Netishyn", 50.3300, 26.6500),
    ("Slavuta", 50.3014, 27.0650),
    ("Starokostiantyniv", 49.7572, 27.2036),
    ("Khmilnyk", 49.5592, 27.9575),
    ("Mohyliv-Podilskyi", 48.4600, 27.7994),
    ("Voznesensk", 47.5647, 31.3308),
    ("Pervomaisk", 48.0433, 30.8500),
    ("Yuzhne", 46.6225, 31.1019),
    ("Chornomorsk", 46.3011, 30.6531),
    ("Izmail", 45.3506, 28.8389),
    ("Bilhorod-Dnistrovskyi", 46.1958, 30.3433),
    ("Korostyshiv", 50.3172, 29.0569),
    ("Obukhiv", 50.1069, 30.6186),
    ("Pereiaslav", 50.0667, 31.4500),
    ("Kaniv", 49.7500, 31.4667),
    ("Smila", 49.2225, 31.8872),
    ("Znamianka", 48.7206, 32.6672),
    ("Oleksandriia", 48.6700, 33.1200),
    ("Svitlovodsk", 49.0483, 33.2417),
    ("Kupiansk", 49.7100, 37.6167),
    ("Izium", 49.2086, 37.2486),
    ("Balakliia", 49.4500, 36.8500),
    ("Chuhuiv", 49.8356, 36.6861),
    ("Okhtyrka", 50.3100, 34.9000),
    ("Romny", 50.7511, 33.4747),
    ("Hlukhiv", 51.6781, 33.9164),
    ("Pryluky", 50.5942, 32.3867),
    ("Nizhyn", 51.0481, 31.8867),
    ("Boryspil", 50.3527, 30.9500),
    ("Vasylkiv", 50.1919, 30.3139),
    ("Boyarka", 50.3167, 30.2833),
    ("Vyshneve", 50.3867, 30.3700),
    ("Horishni Plavni", 49.0167, 33.6500),
    ("Enerhodar", 47.4989, 34.6578),
    ("Tokmak", 47.2553, 35.7125),
    ("Druzhkivka", 48.6303, 37.5278),
    ("Kostiantynivka", 48.5333, 37.7167),
    ("Bakhmut", 48.5950, 38.0000),
    ("Popasna", 48.6333, 38.3833),
    ("Svatove", 49.4100, 38.1500),
    ("Kreminna", 49.0494, 38.1306),
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def nearest_city(lat: float, lon: float, max_km: float = 80.0) -> Optional[str]:
    best: Optional[str] = None
    best_d = max_km
    for name, clat, clon in UKRAINIAN_CITIES:
        d = haversine_km(lat, lon, clat, clon)
        if d < best_d:
            best_d = d
            best = name
    return best
