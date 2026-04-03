"""Trailing PIN suffix in Deye inverter device names (e.g. \"My site pin1345\") — strip for UI, verify on writes."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Optional

from fastapi import HTTPException

# Match trailing " pin1234" on the device name (case-insensitive "pin" + digits).
_INVERTER_PIN_SUFFIX_RE = re.compile(r"(?i)\s+pin(\d{1,12})\s*$")


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


def assert_inverter_write_pin(submitted_pin: Optional[str], expected_pin: Optional[str]) -> None:
    """
    Remote writes are allowed only when the Deye plant/device name encodes a trailing `` pin<digits>``.
    Then the submitted PIN must match (SHA-256 + compare_digest).
    """
    if expected_pin is None:
        raise HTTPException(
            status_code=403,
            detail=(
                'Remote control requires a PIN suffix in the inverter or plant name in Deye Cloud '
                '(e.g. add " pin1234" at the end of the name).'
            ),
        )
    got = (submitted_pin or "").strip()
    if not got:
        raise HTTPException(status_code=403, detail="Invalid or missing inverter PIN")
    gh = hashlib.sha256(got.encode("utf-8")).digest()
    eh = hashlib.sha256(expected_pin.encode("utf-8")).digest()
    if not hmac.compare_digest(gh, eh):
        raise HTTPException(status_code=403, detail="Invalid or missing inverter PIN")
