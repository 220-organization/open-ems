-- GridLab External BESS API: live 5-min samples + hourly history (Kyiv calendar).

CREATE TABLE gridlab_power_sample (
    device_id INTEGER NOT NULL,
    bucket_start TIMESTAMPTZ NOT NULL,
    soc_percent DOUBLE PRECISION,
    battery_power_w DOUBLE PRECISION,
    grid_power_w DOUBLE PRECISION,
    pv_power_w DOUBLE PRECISION,
    load_power_w DOUBLE PRECISION,
    ev_power_w DOUBLE PRECISION,
    is_online BOOLEAN,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_id, bucket_start)
);

CREATE INDEX idx_gridlab_power_sample_device_time
    ON gridlab_power_sample (device_id, bucket_start DESC);

CREATE TABLE gridlab_meter_reading (
    device_id INTEGER NOT NULL,
    meter_id INTEGER NOT NULL,
    bucket_start TIMESTAMPTZ NOT NULL,
    power_kw DOUBLE PRECISION,
    kwh_import DOUBLE PRECISION,
    kwh_export DOUBLE PRECISION,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_id, meter_id, bucket_start)
);

CREATE INDEX idx_gridlab_meter_reading_device_meter_time
    ON gridlab_meter_reading (device_id, meter_id, bucket_start DESC);

CREATE TABLE gridlab_hourly_meter (
    device_id INTEGER NOT NULL,
    meter_id INTEGER NOT NULL,
    target_date DATE NOT NULL,
    hour SMALLINT NOT NULL,
    energy_import_kwh DOUBLE PRECISION,
    energy_export_kwh DOUBLE PRECISION,
    avg_power_kw DOUBLE PRECISION,
    samples INTEGER,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_id, meter_id, target_date, hour),
    CONSTRAINT chk_gridlab_hourly_meter_hour CHECK (hour >= 0 AND hour <= 23)
);

CREATE INDEX idx_gridlab_hourly_meter_device_date
    ON gridlab_hourly_meter (device_id, target_date);

CREATE TABLE gridlab_hourly_soc (
    device_id INTEGER NOT NULL,
    target_date DATE NOT NULL,
    hour SMALLINT NOT NULL,
    soc_percent DOUBLE PRECISION,
    sample_ts TIMESTAMPTZ,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_id, target_date, hour),
    CONSTRAINT chk_gridlab_hourly_soc_hour CHECK (hour >= 0 AND hour <= 23)
);

CREATE INDEX idx_gridlab_hourly_soc_device_date
    ON gridlab_hourly_soc (device_id, target_date);

CREATE TABLE gridlab_hourly_flow (
    device_id INTEGER NOT NULL,
    target_date DATE NOT NULL,
    hour SMALLINT NOT NULL,
    pv_total DOUBLE PRECISION,
    pv_to_bess DOUBLE PRECISION,
    pv_to_grid DOUBLE PRECISION,
    grid_to_bess DOUBLE PRECISION,
    bess_to_grid DOUBLE PRECISION,
    bess_to_load DOUBLE PRECISION,
    grid_to_load DOUBLE PRECISION,
    load DOUBLE PRECISION,
    losses DOUBLE PRECISION,
    fiscal_grid_import DOUBLE PRECISION,
    fiscal_grid_export DOUBLE PRECISION,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_id, target_date, hour),
    CONSTRAINT chk_gridlab_hourly_flow_hour CHECK (hour >= 0 AND hour <= 23)
);

CREATE INDEX idx_gridlab_hourly_flow_device_date
    ON gridlab_hourly_flow (device_id, target_date);
