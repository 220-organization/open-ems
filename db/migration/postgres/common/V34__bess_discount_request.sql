-- Order BESS: volume discount request leads from the UI.

CREATE TABLE bess_discount_request (
    id BIGSERIAL PRIMARY KEY,
    preset_id VARCHAR(64) NOT NULL,
    business_type VARCHAR(32) NOT NULL,
    units INT NOT NULL,
    total_usd DOUBLE PRECISION,
    contact VARCHAR(200),
    kit_json JSONB,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_bess_discount_request_created ON bess_discount_request (created_on DESC);
CREATE INDEX idx_bess_discount_request_type ON bess_discount_request (business_type, created_on DESC);
