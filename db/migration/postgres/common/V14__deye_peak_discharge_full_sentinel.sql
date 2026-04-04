-- Allow 100 = "full discharge" (resolve to current SoC at run time) alongside 2, 10, 20.

ALTER TABLE deye_peak_auto_discharge_pref
    DROP CONSTRAINT IF EXISTS chk_peak_pref_discharge_soc_delta_pct;

ALTER TABLE deye_peak_auto_discharge_pref
    ADD CONSTRAINT chk_peak_pref_discharge_soc_delta_pct
    CHECK (discharge_soc_delta_pct IN (2, 10, 20, 100));
