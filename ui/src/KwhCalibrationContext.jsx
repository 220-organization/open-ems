import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import KwhCalibrationModal from './KwhCalibrationModal';
import { formatEnergyKwhText, inverterNeedsKwhCalibration } from './kwhCalibration';

const KwhCalibrationContext = createContext(null);

const NOOP = {
  kwhHidden: false,
  needsCalibration: false,
  requestReveal: () => {},
  formatEnergyKwh: (value, fmt, unit) => formatEnergyKwhText(value, fmt, unit, false),
};

export function KwhCalibrationProvider({ inverterSn, t, children }) {
  const needsCalibration = inverterNeedsKwhCalibration(inverterSn);
  /** Session-only: approximate kWh shown until reload or inverter change. */
  const [optIn, setOptIn] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    setOptIn(false);
    setModalOpen(false);
  }, [inverterSn]);

  const kwhHidden = needsCalibration && !optIn;

  const requestReveal = useCallback(() => {
    if (!needsCalibration || optIn) return;
    setModalOpen(true);
  }, [needsCalibration, optIn]);

  const confirmApproximate = useCallback(() => {
    setOptIn(true);
    setModalOpen(false);
  }, []);

  const declineApproximate = useCallback(() => {
    setModalOpen(false);
  }, []);

  const formatEnergyKwh = useCallback(
    (value, fmt, unit) => formatEnergyKwhText(value, fmt, unit, kwhHidden),
    [kwhHidden],
  );

  const value = useMemo(
    () => ({
      kwhHidden,
      needsCalibration,
      requestReveal,
      formatEnergyKwh,
    }),
    [kwhHidden, needsCalibration, requestReveal, formatEnergyKwh],
  );

  return (
    <KwhCalibrationContext.Provider value={value}>
      {children}
      {needsCalibration ? (
        <KwhCalibrationModal
          open={modalOpen}
          onConfirm={confirmApproximate}
          onDecline={declineApproximate}
          t={t}
        />
      ) : null}
    </KwhCalibrationContext.Provider>
  );
}

export function useKwhCalibration() {
  return useContext(KwhCalibrationContext) ?? NOOP;
}
