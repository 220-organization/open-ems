"""DAM (OREE) hourly prices from open-ems DB; chart-day is DB-only unless lazy sync is explicitly enabled."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app import settings
from app.dam_prices_xlsx import build_hourly_dam_prices_xlsx, dam_xlsx_filename
from app.entsoe_dam_service import list_entsoe_dam_prices_for_year, list_entsoe_dam_years, resolve_zone_eic
from app.oree_dam_service import (
    KYIV,
    ensure_dam_indexes_for_day,
    get_hourly_dam_with_optional_sync,
    get_lazy_oree_chart_meta,
    list_oree_dam_prices_for_year,
    list_oree_dam_years,
    oree_dam_configured,
    sync_dam_prices_to_db,
)
from app.rdn_consultation_payment import (
    DAM_XLSX_AMOUNT_UAH,
    create_dam_xlsx_invoice,
    fetch_invoice_status,
    is_test_payment_enabled,
    with_query,
)
from app.telegram_notify import format_dam_xlsx_paid_message, send_telegram_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dam", tags=["dam"])

_NO_STORE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


def _kyiv_today() -> date:
    return datetime.now(KYIV).date()


_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_XLSX_SUCCESS = frozenset({"SUCCESS"})
_XLSX_PENDING: dict[str, dict] = {}


class XlsxPayCreateRequest(BaseModel):
    redirect_url: str = Field(..., min_length=8, max_length=2000)


class XlsxPayCreateResponse(BaseModel):
    payment_id: str
    invoice_id: str
    page_url: str
    amount_uah: int = DAM_XLSX_AMOUNT_UAH


class XlsxPayStatusResponse(BaseModel):
    payment_id: str
    invoice_id: str
    status: str
    amount_uah: int


def _xlsx_payment_unlocked(payment_id: Optional[str]) -> bool:
    if not payment_id:
        return False
    row = _XLSX_PENDING.get(str(payment_id).strip())
    if row is None:
        return False
    return str(row.get("status") or "").upper() in _XLSX_SUCCESS


def _xlsx_status_response(payment_id: str, row: dict) -> XlsxPayStatusResponse:
    return XlsxPayStatusResponse(
        payment_id=payment_id,
        invoice_id=row["invoice_id"],
        status=str(row.get("status") or "created"),
        amount_uah=int(row.get("amount_uah") or DAM_XLSX_AMOUNT_UAH),
    )


def _xlsx_webhook_url(request: Request) -> Optional[str]:
    host = (request.headers.get("x-forwarded-host") or request.url.hostname or "").split(",")[0].strip()
    if not host or host in {"localhost", "127.0.0.1"}:
        return None
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    return f"{proto}://{host}/api/dam/xlsx-webhook"


async def _notify_xlsx_paid(row: dict) -> None:
    if str(row.get("status") or "").upper() not in _XLSX_SUCCESS:
        return
    if row.get("tg_notified") or row.get("tg_notify_started"):
        return
    row["tg_notify_started"] = True
    msg = format_dam_xlsx_paid_message(amount_uah=int(row.get("amount_uah") or DAM_XLSX_AMOUNT_UAH))
    ok = await send_telegram_message(msg)
    if ok:
        row["tg_notified"] = True
        logger.info("DAM xlsx payment notified invoice=%s", row.get("invoice_id"))
    else:
        row["tg_notify_started"] = False
        logger.warning("DAM xlsx TG notify failed invoice=%s", row.get("invoice_id"))


def pick_xlsx_year(requested: Optional[int], years: list[int]) -> Optional[int]:
    """Choose a year that has DAM rows: requested if present, else the latest year."""
    if not years:
        return None
    if requested is not None and int(requested) in years:
        return int(requested)
    return years[-1]


async def _xlsx_years_for_market(
    db: AsyncSession, market: str, zone: str
) -> tuple[str, str, list[int]]:
    m = (market or "oree").strip().lower()
    if m not in ("oree", "entsoe"):
        raise HTTPException(status_code=400, detail="market must be oree or entsoe")
    if m == "entsoe":
        ze = resolve_zone_eic(zone)
        if ze is None:
            raise HTTPException(status_code=400, detail=f"Unknown zone: {zone!r}")
        years = await list_entsoe_dam_years(db, ze)
        return m, ze, years
    ze = settings.OREE_COMPARE_ZONE_EIC
    years = await list_oree_dam_years(db, ze)
    return m, ze, years


@router.post("/sync")
async def dam_sync_now(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """
    Fetch DAM from OREE API and upsert into oree_dam_price (requires OREE_API_KEY).

    Disabled unless OREE_DAM_MANUAL_SYNC_ENABLED=1 — normal flow is daily background sync only.
    """
    if not settings.OREE_DAM_MANUAL_SYNC_ENABLED:
        return JSONResponse(
            content={
                "ok": False,
                "configured": oree_dam_configured(),
                "rows": 0,
                "detail": "Manual DAM sync is disabled (set OREE_DAM_MANUAL_SYNC_ENABLED=1 to enable POST /api/dam/sync)",
            },
            status_code=403,
            headers=_NO_STORE,
        )
    if not oree_dam_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "rows": 0, "detail": "OREE_API_KEY not set"},
            headers=_NO_STORE,
        )
    try:
        n = await sync_dam_prices_to_db(db)
        return JSONResponse(
            content={"ok": True, "configured": True, "rows": n},
            headers=_NO_STORE,
        )
    except Exception as exc:
        logger.exception("DAM sync failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/chart-day")
async def dam_chart_day(
    date_param: Optional[date] = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    DAM chart hourly prices: read from DB only (UAH/kWh = MWh/1000).

    OREE is not called from this endpoint when OREE_DAM_LAZY_FETCH_MAX=0. Default is 5 on-demand pulls
    per trade day when DB is empty for Kyiv tomorrow. Otherwise populate prices via the daily scheduler
    (OREE_DAM_DAILY_SYNC_* Europe/Kyiv) or manual POST /api/dam/sync if enabled.
    """
    day = date_param or _kyiv_today()
    zone = settings.OREE_COMPARE_ZONE_EIC

    hourly_mwh, sync_triggered = await get_hourly_dam_with_optional_sync(db, day, zone)
    lazy_oree = await get_lazy_oree_chart_meta(db, day)
    hourly_dam_uah_per_kwh: list[Optional[float]] = []
    for m in hourly_mwh:
        if m is None:
            hourly_dam_uah_per_kwh.append(None)
        else:
            hourly_dam_uah_per_kwh.append(float(m) / 1000.0)

    return JSONResponse(
        content={
            "ok": True,
            "date": day.isoformat(),
            "zoneEic": zone,
            "hourlyPriceDamUahMwh": hourly_mwh,
            "hourlyPriceDamUahPerKwh": hourly_dam_uah_per_kwh,
            "oreeConfigured": oree_dam_configured(),
            "syncTriggered": sync_triggered,
            "lazyOree": lazy_oree,
        },
        headers=_NO_STORE,
    )


@router.get("/damindexes")
async def dam_damindexes(
    date_param: Optional[date] = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    DAM price indices (DAY/NIGHT/PEAK/HPEAK/BASE) for `date` (YYYY-MM-DD), default Kyiv today.
    Reads `oree_dam_index` first; if empty, calls OREE /damindexes and upserts, then returns.
    Response `data` matches OREE shape (prices in UAH/MWh strings); UI converts to UAH/kWh.
    """
    day = date_param or _kyiv_today()
    if not oree_dam_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "detail": "OREE_API_KEY not set",
                "data": None,
                "date": day.isoformat(),
            },
            headers=_NO_STORE,
        )
    try:
        data, source = await ensure_dam_indexes_for_day(db, day)
        if data is None:
            return JSONResponse(
                content={
                    "ok": False,
                    "configured": True,
                    "detail": "No DAM index data for this date.",
                    "data": None,
                    "date": day.isoformat(),
                },
                headers=_NO_STORE,
            )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "date": day.isoformat(),
                "source": source,
                "data": data,
            },
            headers=_NO_STORE,
        )
    except Exception as exc:
        logger.exception("damindexes failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/xlsx-pay", response_model=XlsxPayCreateResponse)
async def create_xlsx_pay(payload: XlsxPayCreateRequest, request: Request) -> XlsxPayCreateResponse:
    """Create a 5000 UAH Monobank invoice; success unlocks GET /prices.xlsx."""
    payment_id = str(uuid.uuid4())
    redirect_url = with_query(payload.redirect_url, damXlsxPayment=payment_id)
    try:
        invoice = create_dam_xlsx_invoice(
            redirect_url=redirect_url,
            reference=payment_id,
            webhook_url=_xlsx_webhook_url(request),
        )
    except RuntimeError as exc:
        logger.exception("Failed to create DAM xlsx invoice")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    invoice_id = (invoice.get("invoiceId") or "").strip()
    page_url = (invoice.get("pageUrl") or "").strip()
    if not invoice_id or not page_url:
        raise HTTPException(status_code=502, detail="Invalid Monobank invoice response")

    _XLSX_PENDING[payment_id] = {
        "invoice_id": invoice_id,
        "amount_uah": DAM_XLSX_AMOUNT_UAH,
        "status": "created",
    }
    return XlsxPayCreateResponse(
        payment_id=payment_id,
        invoice_id=invoice_id,
        page_url=page_url,
        amount_uah=DAM_XLSX_AMOUNT_UAH,
    )


@router.get("/xlsx-payments/{payment_id}", response_model=XlsxPayStatusResponse)
async def get_xlsx_payment_status(payment_id: str) -> XlsxPayStatusResponse:
    row = _XLSX_PENDING.get(payment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    status = (row.get("status") or "created").upper()
    if status not in _XLSX_SUCCESS and status not in {"FAILURE", "EXPIRED", "REVERSED"}:
        remote = fetch_invoice_status(row["invoice_id"])
        if remote:
            status = remote
            row["status"] = status
    if status in _XLSX_SUCCESS:
        await _notify_xlsx_paid(row)
    return _xlsx_status_response(payment_id, row)


class XlsxInvoiceStatusRequest(BaseModel):
    invoice_id: str = Field(..., min_length=4, max_length=120)
    payment_id: Optional[str] = Field(None, max_length=80)


@router.post("/xlsx-invoice-status", response_model=XlsxPayStatusResponse)
async def post_xlsx_invoice_status(payload: XlsxInvoiceStatusRequest) -> XlsxPayStatusResponse:
    """Fallback when in-memory payment map was lost after Monobank redirect."""
    invoice_id = payload.invoice_id.strip()
    remote = fetch_invoice_status(invoice_id)
    if not remote:
        raise HTTPException(status_code=502, detail="Unable to fetch invoice status")
    row = next((r for r in _XLSX_PENDING.values() if r.get("invoice_id") == invoice_id), None)
    payment_id = (payload.payment_id or "").strip() or next(
        (pid for pid, r in _XLSX_PENDING.items() if r.get("invoice_id") == invoice_id),
        f"invoice:{invoice_id}",
    )
    if row is None:
        row = {
            "invoice_id": invoice_id,
            "amount_uah": DAM_XLSX_AMOUNT_UAH,
            "status": remote,
        }
        _XLSX_PENDING[payment_id] = row
    else:
        row["status"] = remote
        _XLSX_PENDING[payment_id] = row
    if remote in _XLSX_SUCCESS:
        await _notify_xlsx_paid(row)
    return _xlsx_status_response(payment_id, row)


@router.post("/xlsx-webhook")
async def xlsx_monobank_webhook(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {"ok": True}
    if not isinstance(body, dict):
        return {"ok": True}
    invoice_id = str(body.get("invoiceId") or "").strip()
    status = str(body.get("status") or "").upper()
    if not invoice_id:
        return {"ok": True}
    row = next((r for r in _XLSX_PENDING.values() if r.get("invoice_id") == invoice_id), None)
    if row is None:
        return {"ok": True}
    if status:
        row["status"] = status
    if status in _XLSX_SUCCESS:
        await _notify_xlsx_paid(row)
    return {"ok": True}


@router.post("/xlsx-pay-test", response_model=XlsxPayStatusResponse)
async def create_xlsx_test_pay() -> XlsxPayStatusResponse:
    """Local/dev only: mark 5000 UAH xlsx payment SUCCESS without Monobank."""
    if not is_test_payment_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    payment_id = str(uuid.uuid4())
    invoice_id = f"local-test-{payment_id}"
    _XLSX_PENDING[payment_id] = {
        "invoice_id": invoice_id,
        "amount_uah": DAM_XLSX_AMOUNT_UAH,
        "status": "SUCCESS",
    }
    await _notify_xlsx_paid(_XLSX_PENDING[payment_id])
    return _xlsx_status_response(payment_id, _XLSX_PENDING[payment_id])


@router.get("/xlsx-years")
async def dam_xlsx_years(
    market: str = Query(default="oree", description="oree or entsoe"),
    zone: str = Query(default="ES", description="ENTSO-E alias when market=entsoe"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Calendar years that have DAM rows for the selected market/zone (for the Excel year switcher)."""
    m, ze, years = await _xlsx_years_for_market(db, market, zone)
    return JSONResponse(
        content={"ok": True, "market": m, "zone": ze, "years": years},
        headers=_NO_STORE,
    )


@router.get("/prices.xlsx")
async def dam_prices_xlsx(
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    market: str = Query(default="oree", description="oree or entsoe"),
    zone: str = Query(default="ES", description="ENTSO-E alias when market=entsoe"),
    payment_id: Optional[str] = Query(default=None, alias="paymentId"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Hourly DAM prices for a calendar year as Excel (.xlsx).

    Requires a successful 5000 UAH payment (``paymentId`` from POST /api/dam/xlsx-pay).
    ``year`` defaults to the latest year that has prices for the selected market/zone.
    Only years with at least one DAM row are allowed.
    OREE export is UAH/kWh; ENTSO-E export is EUR/kWh. One row per trade day, hours 00:00–23:00.
    """
    if not _xlsx_payment_unlocked(payment_id):
        return JSONResponse(
            content={
                "ok": False,
                "detail": f"Pay {DAM_XLSX_AMOUNT_UAH} UAH to download DAM prices",
                "amountUah": DAM_XLSX_AMOUNT_UAH,
            },
            status_code=403,
            headers=_NO_STORE,
        )
    m, ze, years = await _xlsx_years_for_market(db, market, zone)
    y = pick_xlsx_year(year, years)
    if y is None:
        return JSONResponse(
            content={"ok": False, "detail": "No DAM prices in database for this market", "years": years},
            status_code=404,
            headers=_NO_STORE,
        )
    if year is not None and int(year) != y:
        return JSONResponse(
            content={
                "ok": False,
                "detail": f"year must be one of {years}",
                "year": int(year),
                "years": years,
            },
            status_code=400,
            headers=_NO_STORE,
        )

    if m == "entsoe":
        rows = await list_entsoe_dam_prices_for_year(db, y, ze)
        xlsx = build_hourly_dam_prices_xlsx(
            rows,
            year=y,
            market_label="ENTSO-E",
            zone_label=f"{zone.strip().upper()} ({ze})",
            unit_label="EUR/kWh",
        )
        filename = dam_xlsx_filename("entsoe", y, zone.strip().upper())
    else:
        rows = await list_oree_dam_prices_for_year(db, y, ze)
        xlsx = build_hourly_dam_prices_xlsx(
            rows,
            year=y,
            market_label="Ukraine (OREE)",
            zone_label=ze,
            unit_label="UAH/kWh",
        )
        filename = dam_xlsx_filename("oree", y)

    return Response(
        content=xlsx,
        media_type=_XLSX_MEDIA,
        headers={
            **_NO_STORE,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
