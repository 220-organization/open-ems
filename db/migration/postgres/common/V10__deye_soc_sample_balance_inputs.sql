-- Deye hourly grid balance (load / PV / battery) for calibrated inverter SN; see app/deye_soc_service.py
ALTER TABLE deye_soc_sample ADD COLUMN IF NOT EXISTS load_power_w DOUBLE PRECISION;
ALTER TABLE deye_soc_sample ADD COLUMN IF NOT EXISTS pv_power_w DOUBLE PRECISION;
ALTER TABLE deye_soc_sample ADD COLUMN IF NOT EXISTS battery_power_w DOUBLE PRECISION;
