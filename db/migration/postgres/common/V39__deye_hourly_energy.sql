-- Hourly kWh backfilled from Deye Cloud device/history (scaled to daily totals).

CREATE TABLE deye_hourly_energy (
    device_sn VARCHAR(64) NOT NULL,
    hour_start TIMESTAMPTZ NOT NULL,
    consumption_kwh DOUBLE PRECISION NULL,
    generation_kwh DOUBLE PRECISION NULL,
    import_kwh DOUBLE PRECISION NULL,
    export_kwh DOUBLE PRECISION NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'deye_cloud',
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_sn, hour_start)
);

CREATE INDEX idx_deye_hourly_energy_hour_start ON deye_hourly_energy (hour_start);
