-- OREE DAM hourly prices (UAH/MWh), same schema idea as Java OreeDamPriceRepository.
CREATE TABLE oree_dam_price (
    trade_day DATE NOT NULL,
    zone_eic VARCHAR(64) NOT NULL,
    period SMALLINT NOT NULL CHECK (period >= 1 AND period <= 24),
    price_uah_mwh DOUBLE PRECISION NOT NULL,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_day, zone_eic, period)
);

CREATE INDEX idx_oree_dam_trade_zone ON oree_dam_price (trade_day, zone_eic);
