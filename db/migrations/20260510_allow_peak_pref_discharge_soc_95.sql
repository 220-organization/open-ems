-- Peak DAM prefs: allow till-SoC 95% in UI (matches DISCHARGE_TARGET_SOC_PCT_ALLOWED in app/deye_peak_auto_service.py).
-- Run once against production/staging Postgres (asyncpg IntegrityError chk_peak_pref_discharge_soc_delta_pct).

ALTER TABLE deye_peak_auto_discharge_pref
  DROP CONSTRAINT IF EXISTS chk_peak_pref_discharge_soc_delta_pct;

ALTER TABLE deye_peak_auto_discharge_pref
  ADD CONSTRAINT chk_peak_pref_discharge_soc_delta_pct
  CHECK (discharge_soc_delta_pct IN (5, 10, 20, 50, 80, 95));
