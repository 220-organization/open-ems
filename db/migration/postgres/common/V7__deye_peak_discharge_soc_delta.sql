-- Per-inverter target SoC drop % for manual discharge and peak-DAM auto (2..40).

ALTER TABLE deye_peak_auto_discharge_pref
    ADD COLUMN discharge_soc_delta_pct SMALLINT NOT NULL DEFAULT 2;

ALTER TABLE deye_peak_auto_discharge_pref
    ADD CONSTRAINT chk_peak_pref_discharge_soc_delta_pct
    CHECK (discharge_soc_delta_pct >= 2 AND discharge_soc_delta_pct <= 40);
