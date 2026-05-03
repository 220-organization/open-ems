-- Peak / manual discharge pref: store target SoC % (5, 10, 20, 50, 80) instead of delta (2, 10, 20) or full sentinel 100.

ALTER TABLE deye_peak_auto_discharge_pref
    DROP CONSTRAINT IF EXISTS chk_peak_pref_discharge_soc_delta_pct;

UPDATE deye_peak_auto_discharge_pref
SET discharge_soc_delta_pct = CASE discharge_soc_delta_pct
    WHEN 2 THEN 80
    WHEN 10 THEN 50
    WHEN 20 THEN 20
    WHEN 100 THEN 5
    ELSE discharge_soc_delta_pct
END;

UPDATE deye_peak_auto_discharge_pref
SET discharge_soc_delta_pct = 80
WHERE discharge_soc_delta_pct NOT IN (5, 10, 20, 50, 80);

ALTER TABLE deye_peak_auto_discharge_pref
    ADD CONSTRAINT chk_peak_pref_discharge_soc_delta_pct
    CHECK (discharge_soc_delta_pct IN (5, 10, 20, 50, 80));
