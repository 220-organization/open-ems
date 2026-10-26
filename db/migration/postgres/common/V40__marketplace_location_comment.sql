-- Optional free-text comment on marketplace location leads (after phone).

ALTER TABLE marketplace_location
    ADD COLUMN comment TEXT NULL;
