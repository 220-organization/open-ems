-- Utility absent (GridVoltage under 50 V) at the 5-minute sample. NULL = unknown (rows written before this column).

ALTER TABLE deye_soc_sample ADD COLUMN IF NOT EXISTS off_grid BOOLEAN;
