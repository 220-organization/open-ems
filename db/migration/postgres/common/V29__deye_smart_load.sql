-- Per-inverter: smart-load automation (PV vs Smart Load, Gen port On Grid always on).

CREATE TABLE deye_smart_load_pref (
    device_sn VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
