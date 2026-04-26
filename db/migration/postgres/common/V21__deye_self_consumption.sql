-- Self-consumption mode: battery freely discharges to cover home load (ZERO_EXPORT_TO_CT, TOU SoC = 5%).
-- Peak export still fires at peak hour using whatever SoC remains.

CREATE TABLE deye_self_consumption_pref (
    device_sn VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
