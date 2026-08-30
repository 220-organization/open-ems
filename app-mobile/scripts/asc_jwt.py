#!/usr/bin/env python3
"""Mint a short-lived App Store Connect JWT (ES256, IEEE-P1363) via openssl."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

KEY_ID = os.environ.get("APP_STORE_CONNECT_API_KEY_ID", "3DJ5UR88C2")
ISSUER_ID = os.environ.get(
    "APP_STORE_CONNECT_ISSUER_ID", "7406b3c6-c0e2-4518-bdcd-eafa6028da3b"
)
DEFAULT_KEYS = [
    os.environ.get("APP_STORE_CONNECT_API_KEY_PATH", ""),
    str(Path.home() / f".appstoreconnect/private_keys/AuthKey_{KEY_ID}.p8"),
    "/Users/maksym_pavlov/git/220km/activecharge/app-220km/ios/App/private_keys/"
    f"AuthKey_{KEY_ID}.p8",
    "/Users/maksym_pavlov/git/220km/activecharge/app-220km/ios/private_keys/"
    f"AuthKey_{KEY_ID}.p8",
]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _der_ecdsa_to_p1363(der: bytes) -> bytes:
    """Convert OpenSSL DER ECDSA signature to raw r||s (32+32 bytes)."""
    if not der or der[0] != 0x30:
        raise ValueError("not a DER SEQUENCE")
    idx = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)

    def read_int(i: int) -> tuple[bytes, int]:
        if der[i] != 0x02:
            raise ValueError("expected INTEGER")
        i += 1
        ln = der[i]
        i += 1
        raw = der[i : i + ln]
        i += ln
        if raw and raw[0] == 0x00:
            raw = raw[1:]
        return raw, i

    r, idx = read_int(idx)
    s, _ = read_int(idx)
    return r.rjust(32, b"\x00")[-32:] + s.rjust(32, b"\x00")[-32:]


def find_key_path() -> Path:
    for candidate in DEFAULT_KEYS:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError(f"AuthKey_{KEY_ID}.p8 not found")


def mint_token(ttl_sec: int = 1100) -> str:
    now = int(time.time())
    header = {"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}
    payload = {
        "iss": ISSUER_ID,
        "iat": now,
        "exp": now + ttl_sec,
        "aud": "appstoreconnect-v1",
    }
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    key_path = find_key_path()
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(signing_input.encode("ascii"))
        tmp_path = tmp.name
    try:
        der = subprocess.check_output(
            ["openssl", "dgst", "-sha256", "-sign", str(key_path), tmp_path],
        )
    finally:
        os.unlink(tmp_path)
    sig = _der_ecdsa_to_p1363(der)
    return f"{signing_input}.{_b64url(sig)}"


if __name__ == "__main__":
    print(mint_token())
