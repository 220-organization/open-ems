"""
Deye sites where the reported grid power does not match the physical balance.

Use the same balance as Power flow / DAM history:
grid (W, signed) = load − PV_FACTOR × pv − battery
(positive = import). PV is scaled by PV_FACTOR (e.g. 2 strings on one reported channel).
"""

from __future__ import annotations

from typing import Optional

# Serials that need derived grid + doubled PV in UI (keep in sync with ui/src/deyeFlowBalanceSites.js).
FLOW_BALANCE_DEVICE_SNS: frozenset[str] = frozenset({"2407316052", "2505212137"})
FLOW_BALANCE_PV_FACTOR: float = 2.0


def device_uses_flow_balance(device_sn: str) -> bool:
    return (device_sn or "").strip() in FLOW_BALANCE_DEVICE_SNS


def flow_balance_grid_w(
    load_w: Optional[float],
    pv_w: Optional[float],
    battery_w: Optional[float],
    pv_factor: float = FLOW_BALANCE_PV_FACTOR,
) -> Optional[float]:
    if load_w is None or pv_w is None or battery_w is None:
        return None
    return float(load_w) - float(pv_factor) * float(pv_w) - float(battery_w)


def effective_pv_generation_watts(device_sn: str, pv_w: float) -> float:
    """
    PV power (W) used for generation / ROI energy accounting.
    Matches UI DEYE_FLOW_BALANCE_PV_FACTOR for calibrated serials (same set as device_uses_flow_balance).
    """
    v = max(0.0, float(pv_w))
    if device_uses_flow_balance(device_sn):
        return v * float(FLOW_BALANCE_PV_FACTOR)
    return v
