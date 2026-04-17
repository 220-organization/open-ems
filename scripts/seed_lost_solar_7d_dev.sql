-- Dev seed: "Lost solar" scenario — 7 Kyiv calendar days of synthetic 5-min samples.
-- Morning ramp (SoC < 100%, strong PV) then afternoon clip (SoC 100%, low PV).
-- pv_generation_w is NULL so hourly PV kWh uses pv_power_w with FLOW_BALANCE_DEVICE_SNS scaling (e.g. 2512291445 gets 2x), matching production when only inverter "PV power" is present.
-- Run: docker compose exec -T db psql -U openems -d openems -v device_sn=YOUR_SN -f scripts/seed_lost_solar_7d_dev.sql
\set ON_ERROR_STOP on

-- Drop conflicting day-time rows (ROI seed uses a different 5-min phase; duplicates dilute hourly SoC and break lost-solar).
DELETE FROM deye_soc_sample
WHERE device_sn = :'device_sn'::varchar(64)
  AND (bucket_start AT TIME ZONE 'Europe/Kiev')::date >= ((timezone('Europe/Kiev', now()))::date - interval '6 days')
  AND (bucket_start AT TIME ZONE 'Europe/Kiev')::date <= ((timezone('Europe/Kiev', now()))::date)
  AND EXTRACT(HOUR FROM (bucket_start AT TIME ZONE 'Europe/Kiev'))::int >= 8
  AND EXTRACT(HOUR FROM (bucket_start AT TIME ZONE 'Europe/Kiev'))::int <= 18;

INSERT INTO deye_soc_sample (
    device_sn,
    bucket_start,
    soc_percent,
    grid_power_w,
    grid_frequency_hz,
    load_power_w,
    pv_power_w,
    pv_generation_w,
    battery_power_w
)
SELECT
    :'device_sn'::varchar(64),
    x.bucket_start,
    CASE
        WHEN x.kyiv_hour < 12 THEN (62.0 + (x.kyiv_hour - 8) * 10.0)::double precision
        WHEN x.kyiv_hour = 12 THEN 94.0::double precision
        ELSE 100.0::double precision
    END,
    0.0::double precision,
    50.0::double precision,
    300.0::double precision,
    CASE
        WHEN x.kyiv_hour < 13 THEN (2500.0 + (x.kyiv_hour - 8) * 200.0)::double precision
        ELSE 200.0::double precision
    END,
    NULL::double precision,
    0.0::double precision
FROM (
    SELECT
        gs AS bucket_start,
        (EXTRACT(HOUR FROM (gs AT TIME ZONE 'Europe/Kiev')))::int AS kyiv_hour
    FROM (
        SELECT
            ((timezone('Europe/Kiev', now()))::date - day_off) AS kyiv_d
        FROM generate_series(0, 6) AS day_off
    ) days
    CROSS JOIN LATERAL generate_series(
        (days.kyiv_d + time '08:00')::timestamp AT TIME ZONE 'Europe/Kiev',
        (days.kyiv_d + time '18:55')::timestamp AT TIME ZONE 'Europe/Kiev',
        interval '5 minutes'
    ) AS gs
) x
WHERE x.kyiv_hour >= 8 AND x.kyiv_hour <= 18
ON CONFLICT (device_sn, bucket_start) DO UPDATE SET
    soc_percent = EXCLUDED.soc_percent,
    grid_power_w = EXCLUDED.grid_power_w,
    grid_frequency_hz = EXCLUDED.grid_frequency_hz,
    load_power_w = EXCLUDED.load_power_w,
    pv_power_w = EXCLUDED.pv_power_w,
    pv_generation_w = EXCLUDED.pv_generation_w,
    battery_power_w = EXCLUDED.battery_power_w;
