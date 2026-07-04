-- Ubetter EMS: 5-minute power samples (UTC bucket_start) for DB-backed hourly charts.

CREATE TABLE ubetter_power_sample (
    device_sn VARCHAR(128) NOT NULL,
    bucket_start TIMESTAMPTZ NOT NULL,
    soc_percent DOUBLE PRECISION,
    grid_power_w DOUBLE PRECISION,
    load_power_w DOUBLE PRECISION,
    pv_power_w DOUBLE PRECISION,
    pv_generation_w DOUBLE PRECISION,
    battery_power_w DOUBLE PRECISION,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_sn, bucket_start)
);

CREATE INDEX idx_ubetter_power_sample_sn_time ON ubetter_power_sample (device_sn, bucket_start DESC);
