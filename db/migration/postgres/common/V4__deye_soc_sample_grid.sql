-- Signed grid power (W): positive = import from grid, negative = export to grid.

ALTER TABLE deye_soc_sample ADD COLUMN IF NOT EXISTS grid_power_w DOUBLE PRECISION;

ALTER TABLE deye_soc_sample ALTER COLUMN soc_percent DROP NOT NULL;

ALTER TABLE deye_soc_sample DROP CONSTRAINT IF EXISTS deye_soc_sample_at_least_one_metric;
ALTER TABLE deye_soc_sample ADD CONSTRAINT deye_soc_sample_at_least_one_metric
    CHECK (soc_percent IS NOT NULL OR grid_power_w IS NOT NULL);
