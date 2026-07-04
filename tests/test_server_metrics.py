"""Server metrics disk free percent helper."""

from app.routers.server_metrics import _disk_free_percent


def test_disk_free_percent_is_sane():
    pct = _disk_free_percent("/")
    assert pct is None or (0.0 <= pct <= 100.0)
