import { useKwhCalibration } from './KwhCalibrationContext';

/**
 * Renders an energy kWh value; when calibration is pending, shows a clickable placeholder.
 */
export default function KwhDisplay({ value, fmt, unit = 'kWh', className, title }) {
  const { kwhHidden, requestReveal, formatEnergyKwh } = useKwhCalibration();
  const text = formatEnergyKwh(value, fmt, unit);

  if (!kwhHidden) {
    return (
      <span className={className} title={title}>
        {text}
      </span>
    );
  }

  return (
    <button
      type="button"
      className={`kwh-display--masked${className ? ` ${className}` : ''}`}
      title={title}
      aria-label={title}
      onClick={requestReveal}
    >
      {text}
    </button>
  );
}
