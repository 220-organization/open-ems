-- Local buy requests for admin calendar (station / BESS). Slots relative to Kyiv "this week".
-- Idempotent by fixed UUIDs.

WITH week AS (
    SELECT (date_trunc('week', (NOW() AT TIME ZONE 'Europe/Kyiv'))::date) AS mon
)
INSERT INTO sales_buy_request (
    id,
    kind,
    name,
    phone,
    slot_id,
    slot_label,
    title,
    amount_label,
    status,
    page_url,
    payload,
    created_on,
    updated_on
)
SELECT
    seed.id,
    seed.kind,
    seed.name,
    seed.phone,
    seed.slot_id,
    seed.slot_label,
    seed.title,
    seed.amount_label,
    seed.status,
    seed.page_url,
    seed.payload,
    seed.created_on,
    seed.updated_on
FROM week,
LATERAL (
    VALUES
        (
            'b43c0001-0001-4001-8001-000000000001'::uuid,
            'station',
            'Maksym Pavlov',
            '+380971983759',
            to_char(week.mon + 2, 'YYYY-MM-DD') || 'T14:00',
            to_char(week.mon + 2, 'DD.MM.YYYY') || ', 14:00',
            'EDS 120 kW DC',
            '€24 900',
            'requested',
            'http://localhost:9220/buy-commercial-charger?brand=eds',
            '{"catalog":"commercial","sku":"eds-120","brand":"eds"}'::jsonb,
            NOW() - INTERVAL '2 hours',
            NOW() - INTERVAL '2 hours'
        ),
        (
            'b43c0002-0002-4002-8002-000000000002'::uuid,
            'bess',
            'Maksym Pavlov',
            '+380971983759',
            to_char(week.mon + 2, 'YYYY-MM-DD') || 'T10:00',
            to_char(week.mon + 2, 'DD.MM.YYYY') || ', 10:00',
            '30 кВт + 30 кВт·год',
            '$10 839.00',
            'requested',
            'http://localhost:9220/order-bess?biz=cash&preset=custom&units=2&brand=sigen',
            '{"preset_id":"custom","business_type":"cash","total_usd":10839}'::jsonb,
            NOW() - INTERVAL '3 hours',
            NOW() - INTERVAL '3 hours'
        ),
        (
            'b43c0003-0003-4003-8003-000000000003'::uuid,
            'station',
            'Олена Кравець',
            '+380671110801',
            to_char(week.mon + 3, 'YYYY-MM-DD') || 'T18:00',
            to_char(week.mon + 3, 'DD.MM.YYYY') || ', 18:00',
            'Eltis 60 kW',
            '€9 800',
            'requested',
            'http://localhost:9220/buy-commercial-charger?brand=eltis',
            '{"catalog":"commercial","brand":"eltis"}'::jsonb,
            NOW() - INTERVAL '1 day',
            NOW() - INTERVAL '1 day'
        ),
        (
            'b43c0004-0004-4004-8004-000000000004'::uuid,
            'bess_discount',
            'Олег Савчук',
            '+380671110901',
            to_char(week.mon + 4, 'YYYY-MM-DD') || 'T14:00',
            to_char(week.mon + 4, 'DD.MM.YYYY') || ', 14:00',
            'cabinet-100',
            '$82 000',
            'requested',
            'http://localhost:9220/order-bess',
            '{"preset_id":"cabinet-100","units":4}'::jsonb,
            NOW() - INTERVAL '5 hours',
            NOW() - INTERVAL '5 hours'
        )
) AS seed(
    id, kind, name, phone, slot_id, slot_label, title, amount_label, status, page_url, payload, created_on, updated_on
)
ON CONFLICT (id) DO NOTHING;

-- Also put a consultation on the same week so the legend is visible together.
INSERT INTO rdn_consultation (
    id,
    kind,
    name,
    phone,
    slot_id,
    slot_label,
    description,
    amount_uah,
    status,
    invoice_id,
    payment_id,
    created_on,
    updated_on
)
SELECT
    'a38c00aa-00aa-40aa-80aa-0000000000aa'::uuid,
    'payment',
    'Maksym Pavlov',
    '+380971983759',
    to_char(week.mon + 2, 'YYYY-MM-DD') || 'T18:00',
    to_char(week.mon + 2, 'DD.MM.YYYY') || ', 18:00',
    'Консультація РДН (local seed)',
    148400,
    'created',
    'local-seed-invoice-week',
    'local-seed-payment-week',
    NOW() - INTERVAL '90 minutes',
    NOW() - INTERVAL '90 minutes'
FROM (
    SELECT (date_trunc('week', (NOW() AT TIME ZONE 'Europe/Kyiv'))::date) AS mon
) AS week
ON CONFLICT (id) DO NOTHING;
