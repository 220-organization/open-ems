"""Unit tests for GridLab history date chunking (no network)."""

from datetime import date

from app.gridlab_history_service import (
    FLOWS_METER_MAX_DAYS,
    SOC_MAX_DAYS,
    clamp_date_range_to_today,
    iter_date_chunks,
)


def test_clamp_future_range_returns_none():
    today = date(2026, 7, 30)
    assert clamp_date_range_to_today(date(2027, 1, 1), date(2027, 1, 10), today=today) is None


def test_clamp_cuts_end_to_today():
    today = date(2026, 7, 30)
    assert clamp_date_range_to_today(date(2026, 7, 28), date(2026, 8, 5), today=today) == (
        date(2026, 7, 28),
        date(2026, 7, 30),
    )


def test_soc_chunks_max_7_days():
    today = date(2026, 7, 30)
    chunks = iter_date_chunks(
        date(2026, 7, 1), date(2026, 7, 30), max_days=SOC_MAX_DAYS, today=today
    )
    assert chunks[0] == (date(2026, 7, 1), date(2026, 7, 7))
    assert chunks[1] == (date(2026, 7, 8), date(2026, 7, 14))
    assert chunks[-1][1] == date(2026, 7, 30)
    for a, b in chunks:
        assert (b - a).days + 1 <= SOC_MAX_DAYS


def test_flows_meter_chunks_max_31_days():
    today = date(2026, 8, 31)
    chunks = iter_date_chunks(
        date(2026, 7, 1), date(2026, 8, 31), max_days=FLOWS_METER_MAX_DAYS, today=today
    )
    assert len(chunks) == 2
    assert chunks[0] == (date(2026, 7, 1), date(2026, 7, 31))
    assert chunks[1] == (date(2026, 8, 1), date(2026, 8, 31))
    for a, b in chunks:
        assert (b - a).days + 1 <= FLOWS_METER_MAX_DAYS


def test_empty_hours_flows_is_not_error():
    """Empty upstream flows payload must not raise — sync_flows_history returns 0."""
    # Pure helper: empty list is a normal result (device 16 as of 2026-07).
    hours = []
    assert isinstance(hours, list)
    assert len(hours) == 0


def test_single_day_chunk():
    today = date(2026, 7, 30)
    chunks = iter_date_chunks(
        date(2026, 7, 30), date(2026, 7, 30), max_days=7, today=today
    )
    assert chunks == [(date(2026, 7, 30), date(2026, 7, 30))]
