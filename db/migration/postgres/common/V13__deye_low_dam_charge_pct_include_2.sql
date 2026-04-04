-- Allow +2% SoC charge delta (same allowed set as UI / API).

ALTER TABLE deye_low_dam_charge_pref DROP CONSTRAINT chk_low_dam_charge_pct;
ALTER TABLE deye_low_dam_charge_pref
    ADD CONSTRAINT chk_low_dam_charge_pct CHECK (charge_soc_delta_pct IN (2, 10, 20, 50, 100));
