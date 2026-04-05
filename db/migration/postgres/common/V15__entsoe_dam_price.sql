-- ENTSO-E Transparency Platform: day-ahead energy prices (EUR/MWh) per bidding zone EIC.
CREATE TABLE entsoe_dam_price (
    trade_day DATE NOT NULL,
    zone_eic VARCHAR(64) NOT NULL,
    period SMALLINT NOT NULL CHECK (period >= 1 AND period <= 24),
    price_eur_mwh DOUBLE PRECISION NOT NULL,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_day, zone_eic, period)
);

CREATE INDEX idx_entsoe_dam_trade_zone ON entsoe_dam_price (trade_day, zone_eic);
