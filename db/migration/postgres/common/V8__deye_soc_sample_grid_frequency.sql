-- Mean grid / AC frequency (Hz) from Deye device/latest samples for DAM chart overlay.

ALTER TABLE deye_soc_sample ADD COLUMN IF NOT EXISTS grid_frequency_hz DOUBLE PRECISION;

ALTER TABLE deye_soc_sample DROP CONSTRAINT IF EXISTS deye_soc_sample_at_least_one_metric;
ALTER TABLE deye_soc_sample ADD CONSTRAINT deye_soc_sample_at_least_one_metric
    CHECK (
        soc_percent IS NOT NULL
        OR grid_power_w IS NOT NULL
        OR grid_frequency_hz IS NOT NULL
    );
