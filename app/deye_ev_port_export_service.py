"""Poll 220-km EV station status for inverters whose label binds ``evport<station>``; dynamic SELLING_FIRST export."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

from app import settings
from app.deye_api import (
    apply_selling_first_max_power_w,
    deye_configured,
    list_inverter_devices,
    restore_zero_export_ct_current_soc,
)

logger = logging.getLogger(__name__)

# e.g. "port A (220-km pin9220 evport738)" or "… evport738"
_RE_EVPORT = re.compile(r"evport\s*(\d+)", re.IGNORECASE)
# Optional override: "clientuiMyToken" in plant/device name shown in label
_RE_CLIENTUI = re.compile(r"clientui\s*([a-z0-9]+)", re.IGNORECASE)


def parse_ev_port_binding(label: str) -> Optional[tuple[str, str]]:
    """
    Returns (station_number, client_ui_id) if ``evport<N>`` is present.
    client_ui_id is from ``clientui<token>`` in the label, else EV_PORT_DEVICE_CLIENT_UI_ID.
    """
    text = (label or "").strip()
    if not text:
        return None
    m = _RE_EVPORT.search(text)
    if not m:
        return None
    station = m.group(1).strip()
    if not station:
        return None
    uim = _RE_CLIENTUI.search(text)
    client_ui = (uim.group(1).strip() if uim else "") or settings.EV_PORT_DEVICE_CLIENT_UI_ID
    return station, client_ui


def _job_state_norm(job: Any) -> str:
    if not isinstance(job, dict):
        return ""
    s = job.get("state")
    if s is None:
        return ""
    return str(s).strip().upper().replace("-", "_")


def _should_export_from_status(payload: dict[str, Any]) -> tuple[bool, Optional[dict[str, Any]]]:
    """
    True when last job exists, state IN_PROGRESS, deviceOnline True, and powerWt usable.
    Returns (should_export, last_job_or_none).
    """
    if not payload.get("lastJobPresented"):
        return False, None
    job = payload.get("lastJob")
    if job is None or not isinstance(job, dict):
        return False, None
    if _job_state_norm(job) != "IN_PROGRESS":
        return False, job
    if job.get("deviceOnline") is False:
        return False, job
    pw = job.get("powerWt")
    try:
        w = float(pw) if pw is not None else 0.0
    except (TypeError, ValueError):
        w = 0.0
    if w < 1.0:
        return False, job
    return True, job


async def fetch_station_status(station_number: str, client_ui_id: str) -> Optional[dict[str, Any]]:
    base = settings.B2B_API_BASE_URL.rstrip("/")
    url = f"{base}/api/device/v2/station/status"
    params = {"station_number": station_number, "clientUiId": client_ui_id}
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.get(url, params=params)
    except httpx.RequestError as exc:
        logger.warning("EV port export: station status transport error station=%s — %s", station_number, exc)
        return None
    if r.status_code >= 400:
        logger.warning(
            "EV port export: station status HTTP %s station=%s — %s",
            r.status_code,
            station_number,
            (r.text or "")[:400],
        )
        return None
    try:
        data = r.json()
    except Exception:
        logger.warning("EV port export: station status invalid JSON station=%s", station_number)
        return None
    return data if isinstance(data, dict) else None


# We started SELLING_FIRST for this device in the current process (restore on stop).
_ev_export_active: dict[str, bool] = {}
_last_applied_power_w: dict[str, int] = {}


async def run_ev_port_export_tick() -> None:
    if not deye_configured():
        return

    items = await list_inverter_devices()
    tou_soc = float(settings.DEYE_EV_PORT_EXPORT_TOU_SOC_PCT)

    seen: set[str] = set()
    for it in items:
        sn = str(it.get("deviceSn") or "").strip()
        label = str(it.get("label") or "")
        if not sn:
            continue
        binding = parse_ev_port_binding(label)
        if binding is None:
            continue
        station, client_ui = binding
        seen.add(sn)

        data = await fetch_station_status(station, client_ui)
        if data is None:
            continue

        want, job = _should_export_from_status(data)
        if want and job is not None:
            try:
                pw = int(round(float(job.get("powerWt"))))
            except (TypeError, ValueError):
                pw = 0
            if pw < 1:
                want = False

        if want:
            prev = _last_applied_power_w.get(sn)
            if not _ev_export_active.get(sn) or prev != pw:
                try:
                    await apply_selling_first_max_power_w(sn, pw, tou_soc)
                    _ev_export_active[sn] = True
                    _last_applied_power_w[sn] = pw
                    logger.info(
                        "EV port export: SELLING_FIRST device=%s station=%s powerWt=%s",
                        sn,
                        station,
                        pw,
                    )
                except Exception:
                    logger.exception("EV port export: apply SELLING_FIRST failed device=%s", sn)
            continue

        # Stop: job done / not in progress / offline / bad power
        if _ev_export_active.get(sn):
            try:
                await restore_zero_export_ct_current_soc(sn)
                logger.info(
                    "EV port export: restored ZERO_EXPORT_TO_CT device=%s station=%s (job ended or offline)",
                    sn,
                    station,
                )
            except Exception:
                logger.exception("EV port export: restore ZERO_EXPORT_TO_CT failed device=%s", sn)
            finally:
                _ev_export_active.pop(sn, None)
                _last_applied_power_w.pop(sn, None)

    # Label no longer contains evport — restore if we had started export for this device.
    for stale_sn in list(_ev_export_active.keys()):
        if stale_sn not in seen:
            try:
                await restore_zero_export_ct_current_soc(stale_sn)
                logger.info(
                    "EV port export: restored ZERO_EXPORT_TO_CT device=%s (evport removed from label)",
                    stale_sn,
                )
            except Exception:
                logger.exception("EV port export: restore after label unbind failed device=%s", stale_sn)
            finally:
                _ev_export_active.pop(stale_sn, None)
                _last_applied_power_w.pop(stale_sn, None)
