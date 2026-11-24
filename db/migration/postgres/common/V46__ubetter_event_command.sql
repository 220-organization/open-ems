-- Command log beside cloud alarms. detail holds the run-strategy JSON for rows with alarm_source = command.

ALTER TABLE ubetter_event ADD COLUMN IF NOT EXISTS detail TEXT;
