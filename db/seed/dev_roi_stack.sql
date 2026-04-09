-- Local dev: seed deye_soc_sample (5-min PV + grid pattern) for the last 3 months + DAM rows + ROI CAPEX start (Kyiv midnight, 3 months ago).
-- Grid power varies by Kyiv calendar month (stronger peak import / dip export in current month vs previous) so landing «Arbitrage revenue» MoM % is non-trivial.
-- Enables ROI stack (needs: start in past, >=2 PV samples, >=6h elapsed — see RoiStackStatistics MIN_ELAPSED_MS_FOR_ROI).
--
-- Usage:
--   export DATABASE_URL="postgresql://..."
--   export DEVICE_SN="your_numeric_inverter_serial"
--   ./scripts/seed_roi_dev_data.sh
--
-- Or manually:
--   psql "$DATABASE_URL" -v device_sn="$DEVICE_SN" -v zone_eic="$ZONE_EIC" -f db/seed/dev_roi_stack.sql
--
-- Variables (psql -v):
--   device_sn  — required, Deye inverter serial (digits only as in UI)
--   zone_eic     — optional; default matches settings.OREE_COMPARE_ZONE_EIC (UAH DAM zone)

\set ON_ERROR_STOP on

-- Replace whole history for this inverter with synthetic samples (local dev only).
DELETE FROM deye_soc_sample WHERE device_sn = :'device_sn';

-- Kyiv hour kh: ~30 kWh/day PV during 08–18 (flat ~3000 W); ~35 kWh/day load at night 22–06 with
-- pseudo-random active buckets (~70% of night intervals) at ~6300 W so trapezoids match targets.
-- grid_power_w: month-aware arbitrage-shaped signal (import in high-DAM evening hours, export in low-DAM midday).
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
    :'device_sn'::varchar(64),
    g,
    65.0 + (random() * 20.0),
    CASE
      WHEN to_char(timezone('Europe/Kiev', g), 'YYYY-MM')
        = to_char(timezone('Europe/Kiev', now()), 'YYYY-MM') THEN
        CASE
          WHEN kh >= 19 AND kh <= 22 THEN 3200.0
          WHEN kh >= 13 AND kh <= 15 THEN -2800.0
          ELSE 150.0
        END
      WHEN to_char(timezone('Europe/Kiev', g), 'YYYY-MM')
        = to_char(timezone('Europe/Kiev', now()) - interval '1 month', 'YYYY-MM') THEN
        CASE
          WHEN kh >= 19 AND kh <= 22 THEN 1600.0
          WHEN kh >= 13 AND kh <= 15 THEN -1400.0
          ELSE 80.0
        END
      ELSE
        CASE
          WHEN kh >= 19 AND kh <= 22 THEN 2200.0
          WHEN kh >= 13 AND kh <= 15 THEN -2000.0
          ELSE 100.0
        END
    END,
    CASE
        WHEN kh >= 8 AND kh < 18 THEN 300.0
        WHEN (kh >= 22 OR kh < 7) AND mod(abs(hashtext(g::text)), 10) < 7 THEN
            6300.0 + (random() * 200.0)::double precision
        ELSE 220.0
    END,
    CASE
        WHEN kh >= 8 AND kh < 18 THEN 3000.0
        ELSE 0.0
    END,
    CASE
        WHEN kh >= 8 AND kh < 18 THEN 3000.0
        ELSE 0.0
    END,
    0.0
FROM generate_series(
    date_trunc('minute', now() - interval '3 months'),
    date_trunc('minute', now()),
    interval '5 minutes'
) AS g
CROSS JOIN LATERAL (
    SELECT EXTRACT(HOUR FROM timezone('Europe/Kiev', g))::int AS kh
) AS z;

-- Hourly DAM (UAH/MWh): emulate typical Kyiv DAM shape — night moderate, morning peak, midday solar dip,
-- evening peak (~11 UAH/kWh at hour 21). DB stores MWh; UI shows /1000 as UAH/kWh.
-- Period p = hour (p-1)..(p) Kyiv for that trade_day (same convention as OREE hourly rows).
INSERT INTO oree_dam_price (trade_day, zone_eic, period, price_uah_mwh)
SELECT
    d::date,
    :'zone_eic'::varchar(64),
    p::smallint,
    (
        CASE p::int
            WHEN 1 THEN 3500
            WHEN 2 THEN 3300
            WHEN 3 THEN 3100
            WHEN 4 THEN 2800
            WHEN 5 THEN 2500
            WHEN 6 THEN 2800
            WHEN 7 THEN 3500
            WHEN 8 THEN 5200
            WHEN 9 THEN 6500
            WHEN 10 THEN 7000
            WHEN 11 THEN 7000
            WHEN 12 THEN 5200
            WHEN 13 THEN 2800
            WHEN 14 THEN 500
            WHEN 15 THEN 500
            WHEN 16 THEN 900
            WHEN 17 THEN 2200
            WHEN 18 THEN 4500
            WHEN 19 THEN 6800
            WHEN 20 THEN 8800
            WHEN 21 THEN 10200
            WHEN 22 THEN 10900
            WHEN 23 THEN 9500
            WHEN 24 THEN 7000
        END
        * (0.985 + random() * 0.03)
    )::double precision
FROM generate_series(
    ((timezone('Europe/Kiev', now()))::date - interval '3 months')::date,
    ((timezone('Europe/Kiev', now()))::date + 1),
    interval '1 day'
) AS d
CROSS JOIN generate_series(1, 24) AS p
ON CONFLICT (trade_day, zone_eic, period) DO NOTHING;

-- Period start: start of Kyiv local day, 3 calendar months ago (aligned with seeded window).
INSERT INTO deye_roi_capex (device_sn, capex_usd, period_start_at)
VALUES (
    :'device_sn'::varchar(64),
    4200.0,
    (
        (date_trunc('day', timezone('Europe/Kiev', now())) - interval '3 months')
        AT TIME ZONE 'Europe/Kyiv'
    )
)
ON CONFLICT (device_sn) DO UPDATE SET
    capex_usd = EXCLUDED.capex_usd,
    period_start_at = EXCLUDED.period_start_at,
    updated_on = now();
