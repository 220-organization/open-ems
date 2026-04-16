-- Huawei FusionSolar: 5-minute power samples (UTC bucket_start) for DB-backed hourly charts.

CREATE TABLE huawei_power_sample (
    station_code VARCHAR(64) NOT NULL,
    bucket_start TIMESTAMPTZ NOT NULL,
    pv_power_w DOUBLE PRECISION,
    grid_power_w DOUBLE PRECISION,
    load_power_w DOUBLE PRECISION,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (station_code, bucket_start)
);

CREATE INDEX idx_huawei_power_sample_code_time ON huawei_power_sample (station_code, bucket_start DESC);
