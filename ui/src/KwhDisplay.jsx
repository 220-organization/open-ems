import { useKwhCalibration } from './KwhCalibrationContext';

/**
 * Renders an energy kWh value. Uncalibrated Deye inverters get a ``~`` prefix.
 */
export default function KwhDisplay({ value, fmt, unit = 'kWh', className, title }) {
  const { formatEnergyKwh } = useKwhCalibration();
  const text = formatEnergyKwh(value, fmt, unit);

  return (
    <span className={className} title={title}>
      {text}
    </span>
  );
}
