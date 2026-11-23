-- Utility disconnected (energyFlow.gridData.gridConnected = false) at the 5-minute sample.
-- NULL = unknown (rows written before this column).

ALTER TABLE ubetter_power_sample ADD COLUMN IF NOT EXISTS off_grid BOOLEAN;
