-- Demo data for Power flow landing totals: per-inverter export samples + peak DAM + manual discharge rows.
-- Run: docker compose exec -T db psql ... -v demo_sn=2410102121 -f scripts/seed_power_flow_demo_sn.sql
\set ON_ERROR_STOP on

WITH ref AS (
    SELECT
        :'demo_sn'::varchar(64) AS sn,
        to_timestamp(floor(extract(epoch FROM now()) / 300) * 300) AS floor_utc
),
windows AS (
    SELECT
        sn,
        floor_utc,
        floor_utc - interval '120 minutes' AS peak_start,
        floor_utc - interval '95 minutes' AS peak_end,
        floor_utc - interval '55 minutes' AS manual_start,
        floor_utc - interval '40 minutes' AS manual_end
    FROM ref
),
series AS (
    SELECT
        w.sn,
        g AS bucket_start,
        CASE
            WHEN g >= w.peak_start AND g <= w.peak_end THEN -2400.0::double precision
            WHEN g >= w.manual_start AND g <= w.manual_end THEN -2550.0::double precision
            ELSE 0.0::double precision
        END AS grid_w
    FROM windows w,
        LATERAL generate_series(
            w.floor_utc - interval '150 minutes',
            w.floor_utc,
            interval '5 minutes'
        ) AS g
)
INSERT INTO deye_soc_sample (
    device_sn,
    bucket_start,
    soc_percent,
    grid_power_w,
    load_power_w,
    pv_power_w,
    pv_generation_w,
    battery_power_w
)
SELECT
    sn,
    bucket_start,
    52.0,
    grid_w,
    400.0,
    1200.0,
    1200.0,
    0.0
FROM series
ON CONFLICT (device_sn, bucket_start) DO UPDATE SET
    soc_percent = EXCLUDED.soc_percent,
    grid_power_w = EXCLUDED.grid_power_w,
    load_power_w = EXCLUDED.load_power_w,
    pv_power_w = EXCLUDED.pv_power_w,
    pv_generation_w = EXCLUDED.pv_generation_w,
    battery_power_w = EXCLUDED.battery_power_w;

WITH ref AS (
    SELECT
        :'demo_sn'::varchar(64) AS sn,
        to_timestamp(floor(extract(epoch FROM now()) / 300) * 300) AS floor_utc
),
windows AS (
    SELECT
        sn,
        floor_utc,
        floor_utc - interval '120 minutes' AS peak_start,
        floor_utc - interval '95 minutes' AS peak_end
    FROM ref
)
INSERT INTO deye_peak_auto_discharge_fired (
    trade_day,
    device_sn,
    peak_hour,
    success_at,
    export_session_start_at,
    export_session_end_at,
    export_session_kwh,
    peak_discharge_hit_target
)
SELECT
    (timezone('Europe/Kiev', w.floor_utc))::date,
    w.sn,
    12::smallint,
    now(),
    w.peak_start,
    w.peak_end + interval '5 minutes',
    -- Must not exceed sum(|W|/12000) over peak buckets (5×5 min at −2400 W → 1.0 kWh); stays < total with manual export.
    1.0,
    true
FROM windows w
ON CONFLICT (trade_day, device_sn, peak_hour) DO UPDATE SET
    success_at = EXCLUDED.success_at,
    export_session_start_at = EXCLUDED.export_session_start_at,
    export_session_end_at = EXCLUDED.export_session_end_at,
    export_session_kwh = EXCLUDED.export_session_kwh,
    peak_discharge_hit_target = EXCLUDED.peak_discharge_hit_target;

DELETE FROM deye_manual_discharge_session WHERE device_sn = :'demo_sn';

WITH ref AS (
    SELECT
        :'demo_sn'::varchar(64) AS sn,
        to_timestamp(floor(extract(epoch FROM now()) / 300) * 300) AS floor_utc
),
windows AS (
    SELECT
        sn,
        floor_utc - interval '55 minutes' AS manual_start,
        floor_utc - interval '40 minutes' AS manual_end
    FROM ref
)
INSERT INTO deye_manual_discharge_session (
    device_sn,
    success_at,
    export_session_start_at,
    export_session_end_at,
    export_session_kwh,
    discharge_hit_target
)
SELECT
    w.sn,
    now() - interval '8 minutes',
    w.manual_start,
    w.manual_end + interval '5 minutes',
    0.85,
    false
FROM windows w;
