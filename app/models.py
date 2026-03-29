import datetime

from sqlalchemy import Date, DateTime, Double, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)


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
