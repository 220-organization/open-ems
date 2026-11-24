-- Commands this app sent to a Deye inverter, shown in the power-flow events list.

CREATE TABLE IF NOT EXISTS deye_command_event (
    id VARCHAR(40) PRIMARY KEY,
    device_sn VARCHAR(32) NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    occurred_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deye_command_event_sn_time
    ON deye_command_event (device_sn, occurred_at DESC);
