-- Peak / manual discharge pref: allow target SoC 0% and 1%.

ALTER TABLE deye_peak_auto_discharge_pref
    DROP CONSTRAINT IF EXISTS chk_peak_pref_discharge_soc_delta_pct;

ALTER TABLE deye_peak_auto_discharge_pref
    ADD CONSTRAINT chk_peak_pref_discharge_soc_delta_pct
    CHECK (discharge_soc_delta_pct IN (0, 1, 5, 10, 20, 50, 80, 95));
