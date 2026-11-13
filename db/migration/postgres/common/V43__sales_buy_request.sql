-- Unified buy requests (station / BESS / BESS discount) for admin calendar + Buy Request tab.

CREATE TABLE sales_buy_request (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind VARCHAR(32) NOT NULL,
    name TEXT NULL,
    phone TEXT NULL,
    slot_id VARCHAR(32) NULL,
    slot_label TEXT NULL,
    title TEXT NULL,
    amount_label TEXT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'requested',
    page_url TEXT NULL,
    payload JSONB NULL,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sales_buy_request_created_on ON sales_buy_request (created_on DESC);
CREATE INDEX idx_sales_buy_request_kind ON sales_buy_request (kind, created_on DESC);
CREATE INDEX idx_sales_buy_request_slot_id ON sales_buy_request (slot_id);
