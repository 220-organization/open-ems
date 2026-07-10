-- Allow Blockbaster EV port set (bb = stations 625, 629, 627, 628) in ev_port_power_sample.

ALTER TABLE ev_port_power_sample
    DROP CONSTRAINT IF EXISTS ev_port_power_sample_acdc_check;

ALTER TABLE ev_port_power_sample
    ADD CONSTRAINT ev_port_power_sample_acdc_check
    CHECK (acdc IN ('dc', 'ac', 'bb'));
