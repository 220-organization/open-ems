-- UI "peak DAM" auto discharge: per-device enable flag + one successful fire per (Kyiv day, device, peak hour).

CREATE TABLE deye_peak_auto_discharge_pref (
    device_sn VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE deye_peak_auto_discharge_fired (
    trade_day DATE NOT NULL,
    device_sn VARCHAR(64) NOT NULL,
    peak_hour SMALLINT NOT NULL CHECK (peak_hour >= 0 AND peak_hour <= 23),
    success_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_day, device_sn, peak_hour)
);

CREATE INDEX IF NOT EXISTS idx_peak_auto_fired_device_day ON deye_peak_auto_discharge_fired (device_sn, trade_day);
