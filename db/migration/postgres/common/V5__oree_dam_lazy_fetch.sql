-- Tracks on-demand OREE DAM API fetches for Kyiv tomorrow (chart-day lazy sync), capped in application code.

CREATE TABLE oree_dam_lazy_fetch (
    trade_day DATE PRIMARY KEY,
    attempts SMALLINT NOT NULL DEFAULT 0 CHECK (attempts >= 0 AND attempts <= 32767),
    updated_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
