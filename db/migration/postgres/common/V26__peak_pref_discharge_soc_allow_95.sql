-- Allow till-SoC 95% for peak DAM prefs (UI + deye_peak_auto_service.DISCHARGE_TARGET_SOC_PCT_ALLOWED).

ALTER TABLE deye_peak_auto_discharge_pref
    DROP CONSTRAINT IF EXISTS chk_peak_pref_discharge_soc_delta_pct;

ALTER TABLE deye_peak_auto_discharge_pref
    ADD CONSTRAINT chk_peak_pref_discharge_soc_delta_pct
    CHECK (discharge_soc_delta_pct IN (5, 10, 20, 50, 80, 95));
