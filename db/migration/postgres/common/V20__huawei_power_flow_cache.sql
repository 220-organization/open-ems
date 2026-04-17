-- Last successful GET /api/huawei/power-flow payload per station (Northbound 407 fallback).
CREATE TABLE huawei_power_flow_cache (
    station_code VARCHAR(64)  NOT NULL,
    saved_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    payload      JSONB        NOT NULL,
    PRIMARY KEY (station_code)
);
