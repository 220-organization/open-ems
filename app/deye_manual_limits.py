"""Manual Deye limits. Automation must not call these.

Read: Modbus holding registers (works while dynamicControl/read is busy).
Single-phase: 0x0035 solar W, 0x00D2 charge A, 0x00D3 discharge A.
HV 3-phase: 0x0154 solar in 10 W steps (80 kW is 8000), 0x00D4 charge A,
0x00D5 discharge A (0x00D2 is charge voltage). 0x0035 stays 0 on HV, and
/config/system keeps the old maxSolarPower, so that field is not the HV ceiling.

Write: POST /order/sys/power/update (MAX_SOLAR_POWER, watts) and
POST /order/battery/parameter/update (MAX_CHARGE_CURRENT / MAX_DISCHARGE_CURRENT, amperes).
kW from the UI is converted with live battery voltage.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

from app.deye_api import (
    _metric_key,
    _poll_deye_order_if_needed,
    _post_deye_json,
    _read_holding_register_modbus,
    assert_inverter_owned,
)

# Same window as DEYE_DYNAMIC_CONTROL_RATED_POWER_W.
_POWER_W_MIN = 500
_POWER_W_MAX = 200_000
_VOLTAGE_V_MIN = 40.0
_VOLTAGE_V_MAX = 1500.0
_CURRENT_A_MIN = 1
_CURRENT_A_MAX = 1000

# Single-phase hybrid (confirmed on 2410102121 via dynamicControl/read and Modbus).
_REG_MAX_SOLAR_POWER = 0x0035
# HV 3-phase: MAX_SOLAR_POWER order writes 0x0154. Counts are watts/10 (80 kW → 8000).
_REG_HV_MAX_SOLAR_POWER = 0x0154
_HV_SOLAR_WATTS_PER_COUNT = 10
_REG_LV_MAX_CHARGE_CURRENT = 0x00D2
_REG_LV_MAX_DISCHARGE_CURRENT = 0x00D3
# HV 3-phase: 0x00D2 is charge voltage (0.1 V), not amps. Currents are the next registers.
_REG_HV_MAX_CHARGE_CURRENT = 0x00D4
_REG_HV_MAX_DISCHARGE_CURRENT = 0x00D5
_LV_CURRENT_MAX_A = 400

_BATTERY_VOLTAGE_KEYS = (
    "BATTERY_VOLTAGE",
    "BATT_VOLTAGE",
    "BATTERY_VOLT",
    "BAT_VOLTAGE",
    "BATTERY_PACK_VOLTAGE",
    "PACK_VOLTAGE",
)


def kw_to_watts(kw: float) -> int:
    watts = int(round(float(kw) * 1000.0))
    if watts < _POWER_W_MIN or watts > _POWER_W_MAX:
        raise ValueError(f"power must be {_POWER_W_MIN / 1000:.1f}–{_POWER_W_MAX / 1000:.0f} kW")
    return watts


def watts_to_charge_amps(watts: int, voltage_v: float) -> int:
    """Battery power limit → Deye max charge/discharge current."""
    voltage = float(voltage_v)
    if voltage < _VOLTAGE_V_MIN or voltage > _VOLTAGE_V_MAX:
        raise ValueError("battery voltage unavailable")
    amps = int(round(int(watts) / voltage))
    if amps < _CURRENT_A_MIN or amps > _CURRENT_A_MAX:
        raise ValueError(f"battery current {amps} A is outside {_CURRENT_A_MIN}–{_CURRENT_A_MAX} A")
    return amps


def solar_power_update_body(device_sn: str, watts: int) -> dict[str, Any]:
    return {
        "deviceSn": device_sn,
        "powerType": "MAX_SOLAR_POWER",
        "value": int(watts),
    }


def battery_current_update_body(device_sn: str, parameter_type: str, amps: int) -> dict[str, Any]:
    # Official Deye field name is misspelled paramterType.
    return {
        "deviceSn": device_sn,
        "paramterType": parameter_type,
        "value": int(amps),
    }


def _unwrap_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("data")
    if isinstance(inner, dict):
        return inner
    return payload


def _int_or_none(raw: Any) -> Optional[int]:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return int(round(value))


def _latest_metric_map(payload: Any) -> dict[str, float]:
    devices = None
    if isinstance(payload, dict):
        devices = payload.get("deviceDataList") or payload.get("dataList")
        inner = payload.get("data")
        if devices is None and isinstance(inner, dict):
            devices = inner.get("deviceDataList") or inner.get("dataList")
    if not isinstance(devices, list) or not devices:
        return {}
    entry = devices[0]
    rows = entry.get("dataList") if isinstance(entry, dict) else None
    if not isinstance(rows, list):
        return {}
    by_key: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _metric_key(row.get("key"))
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if value != value:
            continue
        by_key[key] = value
    return by_key


def rated_power_w_from_latest(payload: Any) -> Optional[int]:
    """Inverter nameplate watts (RATED_POWER). The kW dropdown stops here."""
    raw = _latest_metric_map(payload).get("RATED_POWER")
    if raw is None:
        return None
    watts = int(round(raw))
    if watts < _POWER_W_MIN or watts > _POWER_W_MAX:
        return None
    return watts


def battery_voltage_v_from_latest(payload: Any) -> Optional[float]:
    by_key = _latest_metric_map(payload)
    if not by_key:
        return None
    for key in _BATTERY_VOLTAGE_KEYS:
        if key in by_key and _VOLTAGE_V_MIN <= by_key[key] <= _VOLTAGE_V_MAX:
            return by_key[key]
    for key, value in by_key.items():
        if "BATTERY" in key and "VOLT" in key and "CURRENT" not in key:
            if _VOLTAGE_V_MIN <= value <= _VOLTAGE_V_MAX:
                return value
    return None


def registers_from_dynamic_read(order_payload: Any) -> dict[str, int]:
    """Map analysisResult register addresses (hex) to integer values."""
    if not isinstance(order_payload, dict):
        return {}
    raw = order_payload.get("analysisResult")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        addr = str(key).strip().upper()
        if addr.startswith("0X"):
            addr = addr[2:]
        if not addr:
            continue
        addr = addr.zfill(4)
        parsed = _int_or_none(value)
        if parsed is not None:
            out[addr] = parsed
    return out


def limits_view(
    system_payload: Any,
    battery_payload: Any,
    voltage_v: Optional[float],
) -> dict[str, Any]:
    system = _unwrap_config(system_payload)
    battery = _unwrap_config(battery_payload)
    solar_w = _int_or_none(system.get("maxSolarPower"))
    charge_a = _int_or_none(battery.get("maxChargeCurrent"))
    discharge_a = _int_or_none(battery.get("maxDischargeCurrent"))
    voltage = float(voltage_v) if voltage_v is not None else None
    charge_w = None
    discharge_w = None
    if voltage is not None and _VOLTAGE_V_MIN <= voltage <= _VOLTAGE_V_MAX:
        if charge_a is not None:
            charge_w = int(round(charge_a * voltage))
        if discharge_a is not None:
            discharge_w = int(round(discharge_a * voltage))
    return {
        "maxSolarPowerW": solar_w,
        "maxChargeCurrentA": charge_a,
        "maxDischargeCurrentA": discharge_a,
        "batteryVoltageV": voltage,
        "maxChargePowerW": charge_w,
        "maxDischargePowerW": discharge_w,
    }


def _merge_limit(primary: Optional[int], fallback: Optional[int]) -> Optional[int]:
    return primary if primary is not None else fallback


async def _config_or_none(path: str, device_sn: str) -> Optional[dict[str, Any]]:
    """Some hybrids reject /config/* with 2106001. That is not a hard failure."""
    try:
        data = await _post_deye_json(path, {"deviceSn": device_sn}, timeout=30.0)
    except RuntimeError as exc:
        if "not supported" in str(exc).lower():
            return None
        raise
    return data if isinstance(data, dict) else None


# One Deye control read at a time per inverter. The page also reads smart-load, and a second
# dynamicControl/read while that order is open returns "command concurrent running".
_READ_CACHE_SEC = 30.0
_read_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_read_inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}
_read_guard = asyncio.Lock()


async def read_manual_power_limits(device_sn: str) -> dict[str, Any]:
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    await assert_inverter_owned(sn)
    now = time.monotonic()
    async with _read_guard:
        cached = _read_cache.get(sn)
        if cached is not None and now - cached[0] < _READ_CACHE_SEC:
            return dict(cached[1])
        task = _read_inflight.get(sn)
        if task is None:
            task = asyncio.create_task(_read_manual_power_limits_uncached(sn))
            _read_inflight[sn] = task
    try:
        view = await task
    finally:
        async with _read_guard:
            if _read_inflight.get(sn) is task:
                _read_inflight.pop(sn, None)
    _read_cache[sn] = (time.monotonic(), view)
    return dict(view)


async def _holding_register(device_sn: str, register: int) -> Optional[int]:
    try:
        return await _read_holding_register_modbus(device_sn, register)
    except RuntimeError:
        return None


def _plausible_solar_w(raw: Optional[int]) -> Optional[int]:
    if raw is None or raw < _POWER_W_MIN or raw > _POWER_W_MAX:
        return None
    return int(raw)


def solar_watts_from_registers(lv_raw: Optional[int], hv_raw: Optional[int]) -> Optional[int]:
    """Prefer the single-phase watt register. HV stores the same limit at 0x0154 in 10 W steps."""
    lv = _plausible_solar_w(lv_raw)
    if lv is not None:
        return lv
    if hv_raw is None:
        return None
    return _plausible_solar_w(int(hv_raw) * _HV_SOLAR_WATTS_PER_COUNT)


def _plausible_current_a(raw: Optional[int]) -> Optional[int]:
    if raw is None or raw < _CURRENT_A_MIN or raw > _CURRENT_A_MAX:
        return None
    return int(raw)


async def _read_manual_power_limits_uncached(device_sn: str) -> dict[str, Any]:
    sn = device_sn
    latest = await _post_deye_json("/device/latest", {"deviceList": [sn]}, timeout=30.0)
    voltage = battery_voltage_v_from_latest(latest)
    # Modbus reads still work when /strategy/dynamicControl/read is busy ("command concurrent running").
    solar_raw = await _holding_register(sn, _REG_MAX_SOLAR_POWER)
    hv_solar_raw = None
    if _plausible_solar_w(solar_raw) is None:
        hv_solar_raw = await _holding_register(sn, _REG_HV_MAX_SOLAR_POWER)
    lv_charge = await _holding_register(sn, _REG_LV_MAX_CHARGE_CURRENT)
    lv_discharge = await _holding_register(sn, _REG_LV_MAX_DISCHARGE_CURRENT)
    lv_map = (
        lv_charge is not None
        and lv_discharge is not None
        and 0 < lv_charge <= _LV_CURRENT_MAX_A
        and 0 <= lv_discharge <= _LV_CURRENT_MAX_A
    )
    if lv_map:
        charge_a = lv_charge
        discharge_a = lv_discharge
    else:
        charge_a = await _holding_register(sn, _REG_HV_MAX_CHARGE_CURRENT)
        discharge_a = await _holding_register(sn, _REG_HV_MAX_DISCHARGE_CURRENT)
    from_regs = limits_view(
        {"maxSolarPower": solar_watts_from_registers(solar_raw, hv_solar_raw)},
        {
            "maxChargeCurrent": _plausible_current_a(charge_a),
            "maxDischargeCurrent": _plausible_current_a(discharge_a),
        },
        voltage,
    )
    system = None
    battery = None
    if from_regs["maxSolarPowerW"] is None:
        system = await _config_or_none("/config/system", sn)
    if from_regs["maxChargeCurrentA"] is None or from_regs["maxDischargeCurrentA"] is None:
        battery = await _config_or_none("/config/battery", sn)
    from_config = limits_view(system or {}, battery or {}, voltage)
    view = {
        "maxSolarPowerW": _merge_limit(from_regs["maxSolarPowerW"], from_config["maxSolarPowerW"]),
        "maxChargeCurrentA": _merge_limit(from_regs["maxChargeCurrentA"], from_config["maxChargeCurrentA"]),
        "maxDischargeCurrentA": _merge_limit(
            from_regs["maxDischargeCurrentA"], from_config["maxDischargeCurrentA"]
        ),
        "batteryVoltageV": voltage,
        "maxChargePowerW": None,
        "maxDischargePowerW": None,
    }
    if voltage is not None and _VOLTAGE_V_MIN <= voltage <= _VOLTAGE_V_MAX:
        if view["maxChargeCurrentA"] is not None:
            view["maxChargePowerW"] = int(round(view["maxChargeCurrentA"] * voltage))
        if view["maxDischargeCurrentA"] is not None:
            view["maxDischargePowerW"] = int(round(view["maxDischargeCurrentA"] * voltage))
    if (
        view["maxSolarPowerW"] is None
        and view["maxChargeCurrentA"] is None
        and view["maxDischargeCurrentA"] is None
    ):
        raise RuntimeError("inverter did not return power limits")
    view["deviceSn"] = sn
    view["ratedPowerW"] = rated_power_w_from_latest(latest)
    return view


async def _post_order(path: str, body: dict[str, Any]) -> None:
    data = await _post_deye_json(path, body, timeout=60.0)
    if isinstance(data, dict) and data.get("orderId") is not None:
        await _poll_deye_order_if_needed(data)
    inner = data.get("data") if isinstance(data, dict) else None
    if isinstance(inner, dict) and inner.get("orderId") is not None:
        await _poll_deye_order_if_needed(inner)


async def apply_manual_power_limits(
    device_sn: str,
    *,
    max_solar_power_w: Optional[int] = None,
    max_charge_power_w: Optional[int] = None,
    max_discharge_power_w: Optional[int] = None,
) -> dict[str, Any]:
    """Write only the limits the caller passed. Does not touch the others."""
    sn = (device_sn or "").strip()
    if not sn:
        raise ValueError("device_sn required")
    if max_solar_power_w is None and max_charge_power_w is None and max_discharge_power_w is None:
        raise ValueError("nothing to set")
    await assert_inverter_owned(sn)
    _read_cache.pop(sn, None)

    applied: dict[str, Any] = {"deviceSn": sn}
    if max_solar_power_w is not None:
        watts = int(max_solar_power_w)
        if watts < _POWER_W_MIN or watts > _POWER_W_MAX:
            raise ValueError(f"power must be {_POWER_W_MIN / 1000:.1f}–{_POWER_W_MAX / 1000:.0f} kW")
        await _post_order("/order/sys/power/update", solar_power_update_body(sn, watts))
        applied["maxSolarPowerW"] = watts

    if max_charge_power_w is not None or max_discharge_power_w is not None:
        latest = await _post_deye_json("/device/latest", {"deviceList": [sn]}, timeout=30.0)
        voltage = battery_voltage_v_from_latest(latest)
        if voltage is None:
            raise ValueError("battery voltage unavailable")
        if max_charge_power_w is not None:
            amps = watts_to_charge_amps(int(max_charge_power_w), voltage)
            await _post_order(
                "/order/battery/parameter/update",
                battery_current_update_body(sn, "MAX_CHARGE_CURRENT", amps),
            )
            applied["maxChargePowerW"] = int(max_charge_power_w)
            applied["maxChargeCurrentA"] = amps
        if max_discharge_power_w is not None:
            amps = watts_to_charge_amps(int(max_discharge_power_w), voltage)
            await _post_order(
                "/order/battery/parameter/update",
                battery_current_update_body(sn, "MAX_DISCHARGE_CURRENT", amps),
            )
            applied["maxDischargePowerW"] = int(max_discharge_power_w)
            applied["maxDischargeCurrentA"] = amps
        applied["batteryVoltageV"] = voltage
    return applied
