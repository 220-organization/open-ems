import { useKwhCalibration } from './KwhCalibrationContext';

/**
 * Renders an energy kWh value with ``~`` and a ``*`` marker when approximate
 * (main control panel). Title / aria use the shared precision note.
 */
export default function KwhDisplay({ value, fmt, unit = 'kWh', className, title }) {
  const { formatEnergyKwh, isApproximate, approximateNote } = useKwhCalibration();
  const text = formatEnergyKwh(value, fmt, unit);
  const showStar =
    isApproximate && text && !String(text).startsWith('—') && Boolean(approximateNote);
  const tip = title || (showStar ? approximateNote : undefined);

  return (
    <span className={className} title={tip}>
      {text}
      {showStar ? (
        <sup className="kwh-approx-mark" aria-label={approximateNote}>
          *
        </sup>
      ) : null}
    </span>
  );
}
