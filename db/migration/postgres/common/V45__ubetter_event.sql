-- Ubetter alarm log. Each faultList row is kept after it clears so the UI can show history.

CREATE TABLE IF NOT EXISTS ubetter_event (
    device_sn VARCHAR(128) NOT NULL,
    alarm_id VARCHAR(64) NOT NULL,
    alarm_name TEXT,
    alarm_name_en TEXT,
    alarm_source TEXT,
    alarm_level INTEGER,
    event_status INTEGER,
    is_fault BOOLEAN,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    occurred_at TIMESTAMPTZ,
    cleared_at TIMESTAMPTZ,
    component_category_en TEXT,
    component_model_en TEXT,
    fault_position TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_sn, alarm_id)
);

CREATE INDEX IF NOT EXISTS idx_ubetter_event_sn_time ON ubetter_event (device_sn, occurred_at DESC);
