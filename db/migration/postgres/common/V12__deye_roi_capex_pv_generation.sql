-- Effective PV power (W) for ROI / load energy: raw Deye PV × FLOW_BALANCE_PV_FACTOR where calibrated.
ALTER TABLE deye_soc_sample ADD COLUMN IF NOT EXISTS pv_generation_w DOUBLE PRECISION;

-- Per-inverter CAPEX (USD) and ROI period start (set when user saves Setup ROI statistics).
CREATE TABLE IF NOT EXISTS deye_roi_capex (
    device_sn VARCHAR(64) NOT NULL PRIMARY KEY,
    capex_usd DOUBLE PRECISION NOT NULL CHECK (capex_usd > 0),
    period_start_at TIMESTAMPTZ NOT NULL,
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deye_roi_capex_updated ON deye_roi_capex (updated_on DESC);
