-- Manual (UI) SoC discharge: grid export energy for the SELLING_FIRST → ZERO_EXPORT restore window.

CREATE TABLE deye_manual_discharge_session (
    id BIGSERIAL PRIMARY KEY,
    device_sn VARCHAR(64) NOT NULL,
    success_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    export_session_start_at TIMESTAMPTZ,
    export_session_end_at TIMESTAMPTZ,
    export_session_kwh DOUBLE PRECISION,
    discharge_hit_target BOOLEAN
);

CREATE INDEX idx_manual_discharge_device_success ON deye_manual_discharge_session (device_sn, success_at DESC);
