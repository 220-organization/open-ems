-- Night-window auto charge (Kyiv 23:00–06:59): one successful run per (night_window_start, device_sn).

CREATE TABLE deye_night_charge_pref (
    device_sn VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    charge_soc_delta_pct SMALLINT NOT NULL DEFAULT 10,
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_night_charge_pct CHECK (charge_soc_delta_pct IN (2, 10, 20, 50, 100))
);

CREATE TABLE deye_night_charge_fired (
    night_window_start DATE NOT NULL,
    device_sn VARCHAR(64) NOT NULL,
    success_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (night_window_start, device_sn)
);

CREATE INDEX IF NOT EXISTS idx_night_charge_fired_device ON deye_night_charge_fired (device_sn);
