import datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Double, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)


class DeyeSocSample(Base):
    """Deye metrics sampled every ~5 minutes (UTC bucket_start aligned to 5 min)."""

    __tablename__ = "deye_soc_sample"

    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    bucket_start: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    soc_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    grid_power_w: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    grid_frequency_hz: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    created_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OreeDamLazyFetch(Base):
    """OREE API pull attempts for a trade_day when using chart-day lazy sync (Kyiv tomorrow only)."""

    __tablename__ = "oree_dam_lazy_fetch"

    trade_day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DeyePeakAutoDischargePref(Base):
    """Per-inverter: peak-DAM auto flag and SoC drop % for manual + scheduled discharge."""

    __tablename__ = "deye_peak_auto_discharge_pref"

    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discharge_soc_delta_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DeyePeakAutoDischargeFired(Base):
    """Successful peak-hour auto discharge (retry allowed if row missing / failed attempt not stored)."""

    __tablename__ = "deye_peak_auto_discharge_fired"

    trade_day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    peak_hour: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    success_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DeyeLowDamChargePref(Base):
    """Per-inverter: low-DAM auto charge flag and SoC rise % (10/20/50/100)."""

    __tablename__ = "deye_low_dam_charge_pref"

    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    charge_soc_delta_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DeyeLowDamChargeFired(Base):
    """Successful low-hour auto charge (one row per Kyiv day / device / low hour)."""

    __tablename__ = "deye_low_dam_charge_fired"

    trade_day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    low_hour: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    success_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OreeDamPrice(Base):
    """Hourly DAM price from OREE (UAH/MWh); period 1..24."""

    __tablename__ = "oree_dam_price"

    trade_day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    zone_eic: Mapped[str] = mapped_column(String(64), primary_key=True)
    period: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    price_uah_mwh: Mapped[float] = mapped_column(Double, nullable=False)
    created_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
