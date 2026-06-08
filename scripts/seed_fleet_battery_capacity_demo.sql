-- Fleet battery capacity demo for landing /about (~1.23 MWh).
-- Two flow-balance Deye SNs (load_power_w present); each deep manual discharge:
--   battery_kwh = load − grid_import − solar over a 3 h window; nominal = battery_kwh / (ΔSoC%).
--
-- Per device target: 615 kWh (70% discharge → 430.5 kWh from battery).
-- Fleet total: 1230 kWh ≈ 1.23 MWh.
--
-- Usage:
--   docker compose exec -T db psql -U openems -d openems -f scripts/seed_fleet_battery_capacity_demo.sql

\set ON_ERROR_STOP on

WITH devices AS (
    SELECT unnest(ARRAY['2512291445', '2407316052']::varchar(64)[]) AS sn
),
cap_window AS (
    SELECT
        d.sn,
        to_timestamp(floor(extract(epoch FROM now()) / 300) * 300) - interval '1 day' - interval '3 hours' AS start_utc,
        to_timestamp(floor(extract(epoch FROM now()) / 300) * 300) - interval '1 day' - interval '5 minutes' AS end_utc
    FROM devices d
)
DELETE FROM deye_soc_sample s
USING cap_window w
WHERE s.device_sn = w.sn
  AND s.bucket_start >= w.start_utc
  AND s.bucket_start <= w.end_utc;

WITH devices AS (
    SELECT unnest(ARRAY['2512291445', '2407316052']::varchar(64)[]) AS sn
),
cap_window AS (
    SELECT
        d.sn,
        to_timestamp(floor(extract(epoch FROM now()) / 300) * 300) - interval '1 day' - interval '3 hours' AS start_utc,
        to_timestamp(floor(extract(epoch FROM now()) / 300) * 300) - interval '1 day' - interval '5 minutes' AS end_utc
    FROM devices d
),
series AS (
    SELECT
        w.sn,
        g AS bucket_start,
        (
            80.0
            - 70.0 * EXTRACT(EPOCH FROM (g - w.start_utc))
                / NULLIF(EXTRACT(EPOCH FROM (w.end_utc - w.start_utc)), 0)
        )::double precision AS soc,
        10000.0::double precision AS grid_w,
        160166.67::double precision AS load_w,
        6666.67::double precision AS pv_w,
        6666.67::double precision AS pv_gen_w,
        -150000.0::double precision AS bat_w
    FROM cap_window w
    CROSS JOIN LATERAL generate_series(w.start_utc, w.end_utc, interval '5 minutes') AS g
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
    soc,
    grid_w,
    load_w,
    pv_w,
    pv_gen_w,
    bat_w
FROM series;

DELETE FROM deye_manual_discharge_session
WHERE device_sn IN ('2512291445', '2407316052');

WITH devices AS (
    SELECT unnest(ARRAY['2512291445', '2407316052']::varchar(64)[]) AS sn
),
cap_window AS (
    SELECT
        d.sn,
        to_timestamp(floor(extract(epoch FROM now()) / 300) * 300) - interval '1 day' - interval '3 hours' AS start_utc,
        to_timestamp(floor(extract(epoch FROM now()) / 300) * 300) - interval '1 day' - interval '5 minutes' AS end_utc
    FROM devices d
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
    now() - interval '1 day',
    w.start_utc,
    w.end_utc,
    0.0,
    true
FROM cap_window w;
