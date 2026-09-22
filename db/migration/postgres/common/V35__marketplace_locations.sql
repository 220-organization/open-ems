-- Marketplace locations + info payments (ported from activecharge admin-portal).

CREATE TABLE marketplace_location (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_type VARCHAR(16) NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    kw_available VARCHAR(16) NOT NULL,
    distribution_contract BOOLEAN NULL,
    messenger VARCHAR(16) NULL,
    locations JSONB NOT NULL DEFAULT '[]'::jsonb,
    parking_photos JSONB NOT NULL DEFAULT '[]'::jsonb,
    connection_point_photos JSONB NOT NULL DEFAULT '[]'::jsonb,
    distribution_contract_photos JSONB NOT NULL DEFAULT '[]'::jsonb,
    distance_meters INT NULL,
    price_per_kwh_extra NUMERIC(4, 2) NULL,
    monthly_price_parking INTEGER NULL,
    view_count INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'PUBLISHED',
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_marketplace_location_type_status ON marketplace_location (request_type, status);
CREATE INDEX idx_marketplace_location_created_on ON marketplace_location (created_on DESC);

CREATE TABLE marketplace_info_payment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    location_id UUID NULL REFERENCES marketplace_location(id) ON DELETE CASCADE,
    payment_kind TEXT NOT NULL DEFAULT 'location_info',
    invoice_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'CREATED',
    client_ui_id TEXT NULL,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_marketplace_info_payment_invoice ON marketplace_info_payment(invoice_id);
CREATE INDEX idx_marketplace_info_payment_location ON marketplace_info_payment(location_id);
CREATE INDEX idx_marketplace_info_payment_kind ON marketplace_info_payment(payment_kind);
