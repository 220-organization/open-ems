"""Trailing PIN suffix in Deye inverter device names (e.g. \"My site pin1345\") — strip for UI, verify on writes."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Optional

from fastapi import HTTPException

# Match trailing " pin1234" on the device name (case-insensitive "pin" + digits).
_INVERTER_PIN_SUFFIX_RE = re.compile(r"(?i)\s+pin(\d{1,12})\s*$")
# Same token as ``deye_ev_port_export_service.parse_ev_port_binding`` — EV port binding in the label.
_EVPORT_BINDING_RE = re.compile(r"evport\s*(\d+)", re.IGNORECASE)


def label_has_evport_binding(text: str) -> bool:
    """True when plant/device label contains ``evport<N>`` (220-km EV port binding)."""
    return bool(_EVPORT_BINDING_RE.search((text or "").strip()))


def strip_inverter_pin_suffix(text: str) -> tuple[str, Optional[str]]:
    """
    Remove a trailing `` pin<digits>`` token from the inverter display name.

    Returns (display_name_without_suffix, pin_digits_or_none).
    """
    s = (text or "").strip()
    if not s:
        return s, None
    m = _INVERTER_PIN_SUFFIX_RE.search(s)
    if not m:
        return s, None
    display = s[: m.start()].rstrip()
    return (display if display else s[: m.start()].rstrip()), m.group(1)


def assert_inverter_write_pin(
    submitted_pin: Optional[str],
    expected_pin: Optional[str],
    label: Optional[str] = None,
) -> None:
    """
    Remote writes require either:
    - a trailing `` pin<digits>`` in the Deye name (submitted PIN must match), or
    - an ``evport<N>`` binding in the composed label (same as EV port export — no name PIN).
    """
    if expected_pin is None and label_has_evport_binding(label or ""):
        return
    if expected_pin is None:
        raise HTTPException(
            status_code=403,
            detail=(
                'Remote control requires a PIN suffix in the inverter or plant name in Deye Cloud '
                '(e.g. add " pin1234" at the end of the name), or an evport<N> binding in the name.'
            ),
        )
    got = (submitted_pin or "").strip()
    if not got:
        raise HTTPException(status_code=403, detail="Invalid or missing inverter PIN")
    gh = hashlib.sha256(got.encode("utf-8")).digest()
    eh = hashlib.sha256(expected_pin.encode("utf-8")).digest()
    if not hmac.compare_digest(gh, eh):
        raise HTTPException(status_code=403, detail="Invalid or missing inverter PIN")
