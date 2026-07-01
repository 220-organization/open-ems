import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import KwhCalibrationModal from './KwhCalibrationModal';
import {
  formatEnergyKwhText,
  inverterNeedsKwhCalibration,
  readKwhCalibrationChoice,
  writeKwhCalibrationChoice,
} from './kwhCalibration';

const KwhCalibrationContext = createContext(null);

const NOOP = {
  kwhHidden: false,
  needsCalibration: false,
  requestReveal: () => {},
  formatEnergyKwh: (value, fmt, unit) => formatEnergyKwhText(value, fmt, unit, false),
};

export function KwhCalibrationProvider({ inverterSn, t, children }) {
  const needsCalibration = inverterNeedsKwhCalibration(inverterSn);
  /** Approximate kWh visible after user confirms; persisted until local end of day. */
  const [optIn, setOptIn] = useState(() => readKwhCalibrationChoice(inverterSn) === 'confirm');
  /** Modal dismissed for today (decline); no re-prompt until midnight. */
  const [snoozedToday, setSnoozedToday] = useState(() => readKwhCalibrationChoice(inverterSn) === 'decline');
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    const choice = readKwhCalibrationChoice(inverterSn);
    setOptIn(choice === 'confirm');
    setSnoozedToday(choice === 'decline');
    setModalOpen(false);
  }, [inverterSn]);

  const kwhHidden = needsCalibration && !optIn;

  const requestReveal = useCallback(() => {
    if (!needsCalibration || optIn || snoozedToday) return;
    setModalOpen(true);
  }, [needsCalibration, optIn, snoozedToday]);

  const confirmApproximate = useCallback(() => {
    writeKwhCalibrationChoice(inverterSn, 'confirm');
    setOptIn(true);
    setSnoozedToday(false);
    setModalOpen(false);
  }, [inverterSn]);

  const declineApproximate = useCallback(() => {
    writeKwhCalibrationChoice(inverterSn, 'decline');
    setSnoozedToday(true);
    setModalOpen(false);
  }, [inverterSn]);

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
