import { createContext, useCallback, useContext, useMemo } from 'react';
import { formatEnergyKwhText, inverterNeedsKwhCalibration } from './kwhCalibration';

const KwhCalibrationContext = createContext(null);

const NOOP = {
  kwhHidden: false,
  needsCalibration: false,
  isApproximate: true,
  approximateNote: '',
  requestReveal: () => {},
  formatEnergyKwh: (value, fmt, unit) => formatEnergyKwhText(value, fmt, unit, true),
};

/**
 * Energy display context for the control panel: all kWh values are approximate (``~``)
 * with a shared footnote explaining precision limits.
 */
export function KwhCalibrationProvider({ inverterSn, t, children }) {
  const needsCalibration = inverterNeedsKwhCalibration(inverterSn);
  /** Main page always shows approximate kWh (tilted values + footnote). */
  const isApproximate = true;
  const approximateNote = String(t?.('kwhCalibrationPrecisionNote') || '').trim();
  /** Kept for callers; values are never hidden anymore. */
  const kwhHidden = false;

  const requestReveal = useCallback(() => {}, []);

  const formatEnergyKwh = useCallback(
    (value, fmt, unit) => formatEnergyKwhText(value, fmt, unit, isApproximate),
    [isApproximate],
  );

  const value = useMemo(
    () => ({
      kwhHidden,
      needsCalibration,
      isApproximate,
      approximateNote,
      requestReveal,
      formatEnergyKwh,
    }),
    [kwhHidden, needsCalibration, isApproximate, approximateNote, requestReveal, formatEnergyKwh],
  );

  return <KwhCalibrationContext.Provider value={value}>{children}</KwhCalibrationContext.Provider>;
}

export function useKwhCalibration() {
  return useContext(KwhCalibrationContext) ?? NOOP;
}
