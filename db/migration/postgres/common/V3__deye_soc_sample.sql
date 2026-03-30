-- 5-minute Deye SoC samples (UTC bucket_start, floor to 5 min) for history charts.

CREATE TABLE deye_soc_sample (
    device_sn VARCHAR(64) NOT NULL,
    bucket_start TIMESTAMPTZ NOT NULL,
    soc_percent DOUBLE PRECISION NOT NULL,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_sn, bucket_start)
);

CREATE INDEX idx_deye_soc_sample_sn_time ON deye_soc_sample (device_sn, bucket_start DESC);
