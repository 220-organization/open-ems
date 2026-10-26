-- Local dev leads for the BESS discount admin section. Idempotent by contact.
INSERT INTO bess_discount_request (
    preset_id,
    business_type,
    units,
    total_usd,
    contact,
    kit_json,
    created_on
)
SELECT
    seed.preset_id,
    seed.business_type,
    seed.units,
    seed.total_usd,
    seed.contact,
    seed.kit_json,
    seed.created_on
FROM (
    VALUES
        (
            'cabinet-100',
            'installer',
            4,
            82000::double precision,
            'Олег Савчук / +380671110901',
            '{"preset":"cabinet-100"}'::jsonb,
            NOW() - INTERVAL '2 days'
        ),
        (
            'container-215',
            'developer',
            2,
            146000::double precision,
            'ТОВ «Світло Парк» / +380501110902',
            '{"preset":"container-215"}'::jsonb,
            NOW() - INTERVAL '6 hours'
        )
) AS seed(preset_id, business_type, units, total_usd, contact, kit_json, created_on)
WHERE NOT EXISTS (
    SELECT 1 FROM bess_discount_request existing WHERE existing.contact = seed.contact
);
