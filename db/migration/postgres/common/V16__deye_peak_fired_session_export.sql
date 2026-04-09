-- Peak DAM auto discharge: grid export energy during SELLING_FIRST → ZERO_EXPORT restore window.

ALTER TABLE deye_peak_auto_discharge_fired
    ADD COLUMN export_session_start_at TIMESTAMPTZ,
    ADD COLUMN export_session_end_at TIMESTAMPTZ,
    ADD COLUMN export_session_kwh DOUBLE PRECISION,
    ADD COLUMN peak_discharge_hit_target BOOLEAN;
