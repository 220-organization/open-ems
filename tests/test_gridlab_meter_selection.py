"""Unit tests for GridLab meter selection (overlapping roles — no sum-by-role)."""

from app.gridlab_power_service import (
    find_first_physical_by_role,
    find_meter_by_id,
    select_site_meters,
    sum_ev_power_kw,
)


def _m(mid, role, power_kw=1.0, *, virtual=False, stale=False):
    return {
        "id": mid,
        "name": f"m{mid}",
        "role": role,
        "is_virtual": virtual,
        "power_kw": power_kw,
        "stale": stale,
        "data_age_seconds": 1.0,
    }


# Device 16 topology (overlapping production / load meters).
DEVICE16 = [
    _m(21, "pcc", 25.8),
    _m(22, "load", 21.9),  # site load (preferred)
    _m(23, "production", 200.0),  # whole PV (preferred)
    _m(24, "load", 21.6),  # consumption — overlaps 22
    _m(25, "production", 80.0),  # SES 1-2 — overlaps 23
    _m(26, "production", 120.0),  # SES 3-4 — overlaps 23
    _m(27, "load", 0.086),  # EV TOKA 1
    _m(28, "load", 0.016),  # EV TOKA 2
    _m(31, "production", 200.0, virtual=True),
    _m(32, "load", 0.1, virtual=True),
]


def test_select_by_explicit_ids_device16():
    sel = select_site_meters(
        DEVICE16, pcc_id=21, pv_id=23, load_id=22, ev_ids=(27, 28)
    )
    assert sel["pcc"]["id"] == 21
    assert sel["pv"]["id"] == 23
    assert sel["load"]["id"] == 22
    assert [m["id"] for m in sel["ev"]] == [27, 28]
    assert sel["selectedIds"]["pv"] == 23
    # Must NOT pick overlapping 25+26 or 24.
    assert sel["pv"]["power_kw"] == 200.0
    assert sel["load"]["power_kw"] == 21.9


def test_virtual_meters_excluded_from_id_lookup():
    assert find_meter_by_id(DEVICE16, 31) is None
    assert find_meter_by_id(DEVICE16, 31, allow_virtual=True)["id"] == 31
    assert find_meter_by_id(DEVICE16, 32) is None


def test_fallback_first_physical_by_role():
    meters = [
        _m(99, "production", 1.0, virtual=True),
        _m(50, "production", 10.0),
        _m(51, "production", 20.0),
    ]
    assert find_first_physical_by_role(meters, "production")["id"] == 50
    sel = select_site_meters(meters, pcc_id=999, pv_id=999, load_id=999, ev_ids=())
    assert sel["pv"]["id"] == 50


def test_no_double_count_pv_when_using_explicit_id():
    """Summing all production meters would double-count; explicit 23 avoids 25+26."""
    sel = select_site_meters(DEVICE16, pcc_id=21, pv_id=23, load_id=22, ev_ids=(27, 28))
    physical_prod = [
        m for m in DEVICE16 if m["role"] == "production" and not m["is_virtual"]
    ]
    naive_sum = sum(m["power_kw"] for m in physical_prod)
    assert naive_sum == 200.0 + 80.0 + 120.0
    assert sel["pv"]["power_kw"] == 200.0
    assert sel["pv"]["power_kw"] != naive_sum


def test_sum_ev_skips_stale():
    ev = [
        _m(27, "load", 1.0, stale=False),
        _m(28, "load", 2.0, stale=True),
    ]
    assert sum_ev_power_kw(ev) == 1.0
    assert sum_ev_power_kw([_m(27, "load", None), _m(28, "load", None)]) is None
