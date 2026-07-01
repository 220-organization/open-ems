"""In-memory state for Deye smart-load automation (process-local; one day of PV vs SL history)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from app.oree_dam_service import KYIV


@dataclass
class HourlyPvSlBucket:
    samples: int = 0
    pv_below_count: int = 0

    def record(self, pv_below: bool) -> None:
        self.samples += 1
        if pv_below:
            self.pv_below_count += 1

    def all_pv_below(self) -> bool:
        return self.samples > 0 and self.pv_below_count == self.samples

    def majority_pv_below(self) -> bool:
        return self.samples > 0 and self.pv_below_count * 2 > self.samples


@dataclass
class DeviceSmartLoadState:
    pv_below_streak: int = 0
    gen_on_grid_always_on: Optional[bool] = None
    hourly: dict[date, dict[int, HourlyPvSlBucket]] = field(default_factory=dict)
    last_hourly_probe_kyiv: Optional[tuple[date, int]] = None
    pending_probe_check: bool = False


_state: dict[str, DeviceSmartLoadState] = {}


def _device_state(sn: str) -> DeviceSmartLoadState:
    key = (sn or "").strip()
    if key not in _state:
        _state[key] = DeviceSmartLoadState()
    return _state[key]


def kyiv_now() -> datetime:
    return datetime.now(KYIV)


def prune_hourly_cache(sn: str, today: date, yesterday: date) -> None:
    """Keep only yesterday and today buckets."""
    st = _device_state(sn)
    keep = {today, yesterday}
    st.hourly = {d: buckets for d, buckets in st.hourly.items() if d in keep}


def record_hourly_sample(sn: str, when: datetime, pv_below: bool) -> None:
    loc = when.astimezone(KYIV)
    d = loc.date()
    h = loc.hour
    today = kyiv_now().date()
    yesterday = today.fromordinal(today.toordinal() - 1)
    prune_hourly_cache(sn, today, yesterday)
    st = _device_state(sn)
    day_buckets = st.hourly.setdefault(d, {})
    bucket = day_buckets.setdefault(h, HourlyPvSlBucket())
    bucket.record(pv_below)


def yesterday_hour_all_pv_below(sn: str, hour: int, *, min_samples: int) -> bool:
    today = kyiv_now().date()
    yesterday = today.fromordinal(today.toordinal() - 1)
    st = _device_state(sn)
    buckets = st.hourly.get(yesterday, {})
    bucket = buckets.get(hour)
    if bucket is None or bucket.samples < min_samples:
        return False
    return bucket.all_pv_below()


def get_pv_below_streak(sn: str) -> int:
    return _device_state(sn).pv_below_streak


def set_pv_below_streak(sn: str, value: int) -> None:
    _device_state(sn).pv_below_streak = max(0, int(value))


def bump_pv_below_streak(sn: str) -> int:
    st = _device_state(sn)
    st.pv_below_streak += 1
    return st.pv_below_streak


def reset_pv_below_streak(sn: str) -> None:
    _device_state(sn).pv_below_streak = 0


def get_gen_on_grid_always_on(sn: str) -> Optional[bool]:
    return _device_state(sn).gen_on_grid_always_on


def set_gen_on_grid_always_on(sn: str, value: Optional[bool]) -> None:
    _device_state(sn).gen_on_grid_always_on = value


def clear_device_state(sn: str) -> None:
    key = (sn or "").strip()
    _state.pop(key, None)


def should_run_hourly_probe(sn: str, kyiv_date: date, kyiv_hour: int) -> bool:
    st = _device_state(sn)
    key = (kyiv_date, kyiv_hour)
    return st.last_hourly_probe_kyiv != key


def mark_hourly_probe_started(sn: str, kyiv_date: date, kyiv_hour: int) -> None:
    st = _device_state(sn)
    st.last_hourly_probe_kyiv = (kyiv_date, kyiv_hour)
    st.pending_probe_check = True


def consume_pending_probe_check(sn: str) -> bool:
    st = _device_state(sn)
    if not st.pending_probe_check:
        return False
    st.pending_probe_check = False
    return True


def clear_pending_probe_check(sn: str) -> None:
    _device_state(sn).pending_probe_check = False
