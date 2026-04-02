-- OREE DAM price indices (DAY/NIGHT/PEAK/HPEAK/BASE), UAH/MWh from API; UI shows UAH/kWh = MWh/1000.
CREATE TABLE oree_dam_index (
    trade_day DATE NOT NULL,
    zone_code VARCHAR(16) NOT NULL,
    band VARCHAR(16) NOT NULL,
    price_uah_mwh DOUBLE PRECISION NOT NULL,
    percent_vs_prev DOUBLE PRECISION NULL,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_day, zone_code, band),
    CONSTRAINT oree_dam_index_band_chk CHECK (
        band IN ('DAY', 'NIGHT', 'PEAK', 'HPEAK', 'BASE')
    )
);

CREATE INDEX idx_oree_dam_index_trade_day ON oree_dam_index (trade_day);
