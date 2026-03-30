-- Low-DAM auto charge: Kyiv clock hour of minimum DAM price for the day (DB), same retry semantics as peak discharge.

CREATE TABLE deye_low_dam_charge_pref (
    device_sn VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    charge_soc_delta_pct SMALLINT NOT NULL DEFAULT 10,
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_low_dam_charge_pct CHECK (charge_soc_delta_pct IN (10, 20, 50, 100))
);

CREATE TABLE deye_low_dam_charge_fired (
    trade_day DATE NOT NULL,
    device_sn VARCHAR(64) NOT NULL,
    low_hour SMALLINT NOT NULL CHECK (low_hour >= 0 AND low_hour <= 23),
    success_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_day, device_sn, low_hour)
);

CREATE INDEX IF NOT EXISTS idx_low_dam_charge_fired_device_day ON deye_low_dam_charge_fired (device_sn, trade_day);
