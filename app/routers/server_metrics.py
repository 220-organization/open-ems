"""Host metrics for ops dashboard (CPU, RAM, PostgreSQL size)."""

import logging
from typing import Optional

import psutil
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["server"])


class ServerMetricsOut(BaseModel):
    cpu_percent: float = Field(..., description="Mean CPU usage over a short sample window, 0–100")
    memory_used_mb: float
    memory_total_mb: float
    db_size_mb: Optional[float] = Field(None, description="PostgreSQL database size; null if unavailable")


@router.get("/server-metrics", response_model=ServerMetricsOut)
async def server_metrics(db: AsyncSession = Depends(get_db)) -> ServerMetricsOut:
    # Short blocking sample — acceptable for infrequent polling (e.g. every 10s from UI).
    cpu = float(psutil.cpu_percent(interval=0.1))
    vm = psutil.virtual_memory()
    used_mb = float(vm.used) / (1024 * 1024)
    total_mb = float(vm.total) / (1024 * 1024)

    db_mb: Optional[float] = None
    try:
        result = await db.execute(text("SELECT pg_database_size(current_database())"))
        row = result.scalar_one()
        if row is not None:
            db_mb = float(row) / (1024 * 1024)
    except Exception as e:
        logger.warning("server-metrics: could not read DB size: %s", e)

    return ServerMetricsOut(
        cpu_percent=round(cpu, 1),
        memory_used_mb=round(used_mb, 1),
        memory_total_mb=round(total_mb, 1),
        db_size_mb=round(db_mb, 1) if db_mb is not None else None,
    )
