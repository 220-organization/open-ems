import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Double, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)


class DeyeSocSample(Base):
    """
    Deye metrics sampled every ~5 minutes (UTC bucket_start aligned to 5 min).

    pv_power_w: raw PV from Deye (grid balance formulas use this with FLOW_BALANCE_PV_FACTOR).
    pv_generation_w: effective PV for generation/ROI (raw × factor on calibrated sites).
    """

    __tablename__ = "deye_soc_sample"

    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    bucket_start: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    soc_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    grid_power_w: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    grid_frequency_hz: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    load_power_w: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    pv_power_w: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    pv_generation_w: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    battery_power_w: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    created_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class HuaweiPowerSample(Base):
    """
    Huawei plant power in 5-minute UTC buckets (aligned with Deye snapshot cadence).
    Same sign convention as Deye / Power flow UI: grid_power_w > 0 = import, < 0 = export.
    """

    __tablename__ = "huawei_power_sample"

    station_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    bucket_start: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    pv_power_w: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    grid_power_w: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    load_power_w: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    created_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DeyeRoiCapex(Base):
    """User-configured CAPEX (USD) and ROI period start per inverter (Setup ROI statistics)."""

    __tablename__ = "deye_roi_capex"

    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    capex_usd: Mapped[float] = mapped_column(Double, nullable=False)
    period_start_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
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
    """Per-inverter: peak-DAM auto flag; discharge_soc_delta_pct is target SoC % (5, 10, 20, 50, or 80) after discharge."""

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
    export_session_start_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    export_session_end_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    export_session_kwh: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    peak_discharge_hit_target: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)


class DeyeManualDischargeSession(Base):
    """Manual discharge from UI/API: export kWh for one completed SELLING_FIRST session."""

    __tablename__ = "deye_manual_discharge_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_sn: Mapped[str] = mapped_column(String(64), nullable=False)
    success_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    export_session_start_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    export_session_end_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    export_session_kwh: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discharge_hit_target: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)


class DeyeSelfConsumptionPref(Base):
    """Per-inverter: self-consumption flag (battery discharges freely to load; TOU SoC = 5%)."""

    __tablename__ = "deye_self_consumption_pref"

    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DeyeSelfConsumptionAutoDamPref(Base):
    """Per-inverter: when enabled, server toggles self-consumption from DAM (Kyiv hour) vs reference battery LCOE."""

    __tablename__ = "deye_self_consumption_auto_dam_pref"

    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
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


class DeyeNightChargePref(Base):
    """Per-inverter: night-window (Kyiv 23:00–06:59) auto charge flag and SoC rise % (same set as low-DAM charge)."""

    __tablename__ = "deye_night_charge_pref"

    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    charge_soc_delta_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DeyeNightChargeFired(Base):
    """Successful night-window auto charge (one row per night anchor / device)."""

    __tablename__ = "deye_night_charge_fired"

    night_window_start: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    device_sn: Mapped[str] = mapped_column(String(64), primary_key=True)
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


class EntsoeDamPrice(Base):
    """Hourly DAM price from ENTSO-E Transparency (EUR/MWh); period 1..24."""

    __tablename__ = "entsoe_dam_price"

    trade_day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    zone_eic: Mapped[str] = mapped_column(String(64), primary_key=True)
    period: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    price_eur_mwh: Mapped[float] = mapped_column(Double, nullable=False)
    created_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class HuaweiStationListCache(Base):
    """
    getStationList result cached per pageNo:pageSize key.
    Used as a 407-rate-limit fallback so the station list survives process restarts.
    """

    __tablename__ = "huawei_station_list_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    saved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    items: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)


class HuaweiPowerFlowCache(Base):
    """
    Last successful power-flow JSON per station (getDevRealKpi) for failCode 407 fallback.
    """

    __tablename__ = "huawei_power_flow_cache"

    station_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    saved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)


class HuaweiPowerDevicesCache(Base):
    """
    Resolved meter+inverter device pair per stationCode.
    Avoids a getDevList call on every power-flow request after first resolution.
    """

    __tablename__ = "huawei_power_devices_cache"

    station_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    saved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    meter_dev_id: Mapped[str] = mapped_column(String(64), nullable=False)
    meter_dev_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    inverter_dev_id: Mapped[str] = mapped_column(String(64), nullable=False)
    inverter_dev_type_id: Mapped[int] = mapped_column(Integer, nullable=False)


class HuaweiStationEnergyTotals(Base):
    """
    Cached station energy KPIs from FusionSolar getKpiStationDay/Month/Year.

    period in ('day', 'month', 'year').
    period_key: 'YYYY-MM-DD' for day; 'YYYY-MM' for month; 'YYYY' for year.
    Background scheduler refreshes; UI reads from this table.
    """

    __tablename__ = "huawei_station_energy_totals"

    station_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    period: Mapped[str] = mapped_column(String(8), primary_key=True)
    period_key: Mapped[str] = mapped_column(String(16), primary_key=True)
    saved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    pv_kwh: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    consumption_kwh: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    grid_import_kwh: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    grid_export_kwh: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    self_consumption_kwh: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    radiation_kwh_m2: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    theory_kwh: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    perpower_ratio: Mapped[Optional[float]] = mapped_column(Double, nullable=True)


class OreeDamIndex(Base):
    """OREE /damindexes band prices (UAH/MWh); UI shows UAH/kWh = MWh/1000."""

    __tablename__ = "oree_dam_index"

    trade_day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    zone_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    band: Mapped[str] = mapped_column(String(16), primary_key=True)
    price_uah_mwh: Mapped[float] = mapped_column(Double, nullable=False)
    percent_vs_prev: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    created_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
