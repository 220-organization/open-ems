-- Local dev pins for the marketplace map. Idempotent by primary key.
INSERT INTO marketplace_location (
    id,
    request_type,
    name,
    phone,
    kw_available,
    distribution_contract,
    messenger,
    locations,
    parking_photos,
    connection_point_photos,
    distribution_contract_photos,
    distance_meters,
    price_per_kwh_extra,
    monthly_price_parking,
    view_count,
    status,
    created_on,
    updated_on
)
VALUES
    (
        'c1000001-0001-4001-8001-000000000001'::uuid,
        'PROPOSE', 'Андрій Петренко', '+380501110001', '150', TRUE, 'telegram',
        '[{"label": "Либідська, Київ", "lat": 50.4122, "lng": 30.5225}]'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
        40, 1.50, 8000, 4, 'PUBLISHED',
        NOW() - INTERVAL '6 days', NOW() - INTERVAL '6 days'
    ),
    (
        'c1000002-0002-4002-8002-000000000002'::uuid,
        'PROPOSE', 'Марина Коваленко', '+380671110002', '80', FALSE, 'whatsapp',
        '[{"label": "Набережна Перемоги, Дніпро", "lat": 48.4647, "lng": 35.0462}]'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
        15, 2.00, 5000, 2, 'PUBLISHED',
        NOW() - INTERVAL '4 days', NOW() - INTERVAL '4 days'
    ),
    (
        'c1000003-0003-4003-8003-000000000003'::uuid,
        'PROPOSE', 'Богдан Кравець', '+380931110003', '240', TRUE, 'telegram',
        '[{"label": "пл. Ринок, Львів", "lat": 49.8419, "lng": 24.0315}]'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
        20, 1.00, 12000, 6, 'PUBLISHED',
        NOW() - INTERVAL '3 days', NOW() - INTERVAL '3 days'
    ),
    (
        'c1000004-0004-4004-8004-000000000004'::uuid,
        'PROPOSE', 'Софія Романюк', '+380501110004', '120', TRUE, 'telegram',
        '[{"label": "Приморський бульвар, Одеса", "lat": 46.4886, "lng": 30.7414}]'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
        25, 1.80, 9000, 1, 'PUBLISHED',
        NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'
    ),
    (
        'c1000005-0005-4005-8005-000000000005'::uuid,
        'PROPOSE', 'Ірина Бондар', '+380671110005', '60', NULL, 'whatsapp',
        '[{"label": "вул. Сумська, Харків", "lat": 50.0044, "lng": 36.2314}]'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
        NULL, 2.50, 4000, 0, 'PUBLISHED',
        NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day'
    ),
    (
        'c1000006-0006-4006-8006-000000000006'::uuid,
        'LOOKING', 'Олег Сидоренко', '+380501110006', '120', NULL, 'telegram',
        '[{"label": "Київ", "lat": 50.4501, "lng": 30.5234}]'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
        NULL, NULL, NULL, 3, 'PUBLISHED',
        NOW() - INTERVAL '8 days', NOW() - INTERVAL '8 days'
    ),
    (
        'c1000007-0007-4007-8007-000000000007'::uuid,
        'LOOKING', 'Тарас Мельник', '+380931110007', '240', NULL, 'telegram',
        '[{"label": "Вінниця", "lat": 49.2331, "lng": 28.4682}]'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
        NULL, NULL, NULL, 1, 'PUBLISHED',
        NOW() - INTERVAL '5 days', NOW() - INTERVAL '5 days'
    ),
    (
        'c1000008-0008-4008-8008-000000000008'::uuid,
        'LOOKING', 'Наталія Ткаченко', '+380671110008', '80', NULL, 'whatsapp',
        '[{"label": "Черкаси", "lat": 49.4444, "lng": 32.0598}]'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
        NULL, NULL, NULL, 0, 'PUBLISHED',
        NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'
    )
ON CONFLICT (id) DO NOTHING;
