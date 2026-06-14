-- EV port aggregate power (DC/AC fleets): 5-minute UTC buckets for DB-backed hourly grid-import charts.

CREATE TABLE ev_port_power_sample (
    acdc VARCHAR(2) NOT NULL CHECK (acdc IN ('dc', 'ac')),
    bucket_start TIMESTAMPTZ NOT NULL,
    power_w DOUBLE PRECISION,
    active_sessions INTEGER,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (acdc, bucket_start)
);

CREATE INDEX idx_ev_port_power_sample_acdc_time ON ev_port_power_sample (acdc, bucket_start DESC);
