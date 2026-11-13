from app.spa_page_meta import commercial_charger_meta_for_lang, inject_spa_meta

SAMPLE = """<!doctype html>
<html>
<head>
    <title>Open EMS — old</title>
    <meta name="description" content="old desc" />
    <meta name="keywords" content="old kw" />
    <link rel="canonical" href="https://220-km.com:9220/" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Open EMS" />
    <meta property="og:title" content="old og" />
    <meta property="og:description" content="old og desc" />
    <meta property="og:url" content="https://220-km.com:9220/" />
    <meta property="og:image" content="https://220-km.com:9220/static/open-ems-og.png" />
    <meta property="og:locale" content="uk_UA" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="old tw" />
    <meta name="twitter:description" content="old tw desc" />
    <meta name="twitter:image" content="https://220-km.com:9220/static/open-ems-og.png" />
</head>
<body></body>
</html>
"""


def test_inject_commercial_uk_meta():
    meta = commercial_charger_meta_for_lang("uk")
    html = inject_spa_meta(SAMPLE, meta)
    assert meta["title"] in html
    assert meta["description"] in html
    assert meta["og_title"] in html
    assert "/buy-commercial-charger" in html
    assert "commercial-chargers-og.png" in html
    assert "summary_large_image" in html


def test_lang_fallback():
    assert commercial_charger_meta_for_lang("xx")["og_locale"] == "uk_UA"
    assert commercial_charger_meta_for_lang("en")["og_locale"] == "en_US"
