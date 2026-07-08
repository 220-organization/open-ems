-- EV driver GPS tracker: raw pings (short retention), processed stays and trips.

CREATE TABLE ev_driver_gps_raw (
    driver_id VARCHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    source VARCHAR(8) NOT NULL,
    accuracy_m DOUBLE PRECISION,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (driver_id, recorded_at)
);

CREATE TABLE ev_driver_stay (
    id BIGSERIAL PRIMARY KEY,
    driver_id VARCHAR(64) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    point_count INT NOT NULL,
    best_source VARCHAR(8) NOT NULL,
    is_charging_guess BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (driver_id, started_at)
);

CREATE TABLE ev_driver_trip (
    id BIGSERIAL PRIMARY KEY,
    driver_id VARCHAR(64) NOT NULL,
    kyiv_day DATE NOT NULL,
    origin_lat DOUBLE PRECISION NOT NULL,
    origin_lon DOUBLE PRECISION NOT NULL,
    dest_lat DOUBLE PRECISION NOT NULL,
    dest_lon DOUBLE PRECISION NOT NULL,
    origin_city VARCHAR(64),
    dest_city VARCHAR(64),
    distance_km DOUBLE PRECISION NOT NULL,
    route_points JSONB NOT NULL,
    charge_stop_count INT NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_ev_driver_stay_time ON ev_driver_stay (started_at DESC);
CREATE INDEX idx_ev_driver_stay_driver ON ev_driver_stay (driver_id, started_at DESC);
CREATE INDEX idx_ev_driver_trip_day ON ev_driver_trip (kyiv_day DESC);
CREATE INDEX idx_ev_driver_trip_cities ON ev_driver_trip (origin_city, dest_city);
CREATE INDEX idx_ev_driver_gps_raw_unprocessed ON ev_driver_gps_raw (processed, recorded_at);
