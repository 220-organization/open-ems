-- Discharge target SoC and charge delta: 5% steps (keep 1% floor and +2% charge).

ALTER TABLE deye_peak_auto_discharge_pref
    DROP CONSTRAINT IF EXISTS chk_peak_pref_discharge_soc_delta_pct;

ALTER TABLE deye_peak_auto_discharge_pref
    ADD CONSTRAINT chk_peak_pref_discharge_soc_delta_pct
    CHECK (discharge_soc_delta_pct IN (0, 1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95));

ALTER TABLE deye_low_dam_charge_pref
    DROP CONSTRAINT IF EXISTS chk_low_dam_charge_pct;

ALTER TABLE deye_low_dam_charge_pref
    ADD CONSTRAINT chk_low_dam_charge_pct
    CHECK (charge_soc_delta_pct IN (2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100));

ALTER TABLE deye_night_charge_pref
    DROP CONSTRAINT IF EXISTS chk_night_charge_pct;

ALTER TABLE deye_night_charge_pref
    ADD CONSTRAINT chk_night_charge_pct
    CHECK (charge_soc_delta_pct IN (2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100));
