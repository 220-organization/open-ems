-- RDN consultation requests (payments and callbacks) for the admin tab.

CREATE TABLE rdn_consultation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind VARCHAR(16) NOT NULL,
    name TEXT NULL,
    phone TEXT NULL,
    slot_id VARCHAR(32) NULL,
    slot_label TEXT NULL,
    description TEXT NULL,
    amount_uah INTEGER NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'created',
    invoice_id TEXT NULL,
    payment_id TEXT NULL,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rdn_consultation_created_on ON rdn_consultation (created_on DESC);
CREATE INDEX idx_rdn_consultation_payment_id ON rdn_consultation (payment_id);
CREATE INDEX idx_rdn_consultation_invoice_id ON rdn_consultation (invoice_id);
