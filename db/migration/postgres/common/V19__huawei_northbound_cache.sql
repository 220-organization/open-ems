-- Huawei Northbound cache: replaces on-disk JSON files in var/huawei_northbound/.

-- Station list from getStationList (407 fallback; one row per pageNo:pageSize key).
CREATE TABLE huawei_station_list_cache (
    cache_key       VARCHAR(64)  NOT NULL,
    saved_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    items           JSONB        NOT NULL DEFAULT '[]',
    PRIMARY KEY (cache_key)
);

-- Device-pair resolved by getDevList (meterId/Type + inverterId/Type per station).
CREATE TABLE huawei_power_devices_cache (
    station_code        VARCHAR(64)  NOT NULL,
    saved_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    meter_dev_id        VARCHAR(64)  NOT NULL,
    meter_dev_type_id   INTEGER      NOT NULL,
    inverter_dev_id     VARCHAR(64)  NOT NULL,
    inverter_dev_type_id INTEGER     NOT NULL,
    PRIMARY KEY (station_code)
);
