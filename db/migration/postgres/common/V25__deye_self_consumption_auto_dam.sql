-- Optional automation: server toggles self-consumption when current-hour DAM (UAH/kWh) exceeds reference battery LCOE.

CREATE TABLE deye_self_consumption_auto_dam_pref (
    device_sn VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
