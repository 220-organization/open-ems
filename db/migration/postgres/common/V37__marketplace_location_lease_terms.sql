-- Lease terms collected when a landowner publishes a marketplace location.

ALTER TABLE marketplace_location
    ADD COLUMN min_rent_years VARCHAR(8) NULL,
    ADD COLUMN restroom_coffee_nearby BOOLEAN NULL,
    ADD COLUMN more_stations_possible BOOLEAN NULL,
    ADD COLUMN parking_spaces_now INTEGER NULL,
    ADD COLUMN parking_spaces_future INTEGER NULL,
    ADD COLUMN landlord_legal_form VARCHAR(8) NULL;

ALTER TABLE marketplace_location
    ADD CONSTRAINT marketplace_location_min_rent_years_chk
        CHECK (min_rent_years IS NULL OR min_rent_years IN ('1', '2', '3', '5', '5+')),
    ADD CONSTRAINT marketplace_location_landlord_legal_form_chk
        CHECK (landlord_legal_form IS NULL OR landlord_legal_form IN ('FOP', 'TOV')),
    ADD CONSTRAINT marketplace_location_parking_spaces_chk
        CHECK (
            (parking_spaces_now IS NULL OR parking_spaces_now >= 1)
            AND (parking_spaces_future IS NULL OR parking_spaces_future >= 1)
            AND (
                parking_spaces_now IS NULL
                OR parking_spaces_future IS NULL
                OR parking_spaces_future >= parking_spaces_now
            )
        );
