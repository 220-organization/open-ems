import { createContext, useCallback, useContext, useMemo } from 'react';
import { formatEnergyKwhText, inverterNeedsKwhCalibration } from './kwhCalibration';

const KwhCalibrationContext = createContext(null);

const NOOP = {
  kwhHidden: false,
  needsCalibration: false,
  isApproximate: false,
  requestReveal: () => {},
  formatEnergyKwh: (value, fmt, unit) => formatEnergyKwhText(value, fmt, unit, false),
};

/**
 * Energy display context for Deye: uncalibrated inverters show approximate ``~kWh``
 * immediately (no precision popup).
 */
export function KwhCalibrationProvider({ inverterSn, t: _t, children }) {
  const needsCalibration = inverterNeedsKwhCalibration(inverterSn);
  const isApproximate = needsCalibration;
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
      requestReveal,
      formatEnergyKwh,
    }),
    [kwhHidden, needsCalibration, isApproximate, requestReveal, formatEnergyKwh],
  );

  return <KwhCalibrationContext.Provider value={value}>{children}</KwhCalibrationContext.Provider>;
}

export function useKwhCalibration() {
  return useContext(KwhCalibrationContext) ?? NOOP;
}
