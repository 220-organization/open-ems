-- Huawei FusionSolar: cached station energy KPIs (getKpiStationDay/Month/Year).
-- One row per (station_code, period, period_key); period_key is 'YYYY-MM-DD' for day,
-- 'YYYY-MM' for month, 'YYYY' for year. Background scheduler refreshes; UI reads from this table.

CREATE TABLE huawei_station_energy_totals (
    station_code         VARCHAR(64)      NOT NULL,
    period               VARCHAR(8)       NOT NULL,
    period_key           VARCHAR(16)      NOT NULL,
    saved_at             TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    pv_kwh               DOUBLE PRECISION,
    consumption_kwh      DOUBLE PRECISION,
    grid_import_kwh      DOUBLE PRECISION,
    grid_export_kwh      DOUBLE PRECISION,
    self_consumption_kwh DOUBLE PRECISION,
    radiation_kwh_m2     DOUBLE PRECISION,
    theory_kwh           DOUBLE PRECISION,
    perpower_ratio       DOUBLE PRECISION,
    PRIMARY KEY (station_code, period, period_key),
    CONSTRAINT huawei_station_energy_totals_period_chk CHECK (period IN ('day', 'month', 'year'))
);

CREATE INDEX idx_huawei_station_energy_totals_saved
    ON huawei_station_energy_totals (saved_at DESC);
