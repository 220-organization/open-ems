import { usesDeyeFlowBalance } from './deyeFlowBalanceSites';

const STORAGE_PREFIX = 'pf-kwh-calibration-choice';

/** Local calendar date YYYY-MM-DD — snooze expires at midnight. */
function todayKey() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function storageKey(deviceSn) {
  return `${STORAGE_PREFIX}:${String(deviceSn ?? '').trim()}`;
}

/** @returns {'confirm' | 'decline' | null} */
export function readKwhCalibrationChoice(deviceSn) {
  const sn = String(deviceSn ?? '').trim();
  if (!sn) return null;
  try {
    const raw = localStorage.getItem(storageKey(sn));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      parsed?.date === todayKey() &&
      (parsed.choice === 'confirm' || parsed.choice === 'decline')
    ) {
      return parsed.choice;
    }
    localStorage.removeItem(storageKey(sn));
    return null;
  } catch {
    return null;
  }
}

/** Remember user's modal choice until local end of day. */
export function writeKwhCalibrationChoice(deviceSn, choice) {
  const sn = String(deviceSn ?? '').trim();
  if (!sn || (choice !== 'confirm' && choice !== 'decline')) return;
  try {
    localStorage.setItem(storageKey(sn), JSON.stringify({ date: todayKey(), choice }));
  } catch {
    /* ignore quota / private mode */
  }
}

/** Deye serials with flow-balance kWh derivation; all others need calibration before showing energy. */
export function inverterNeedsKwhCalibration(deviceSn) {
  const sn = String(deviceSn ?? '').trim();
  if (!sn) return false;
  return !usesDeyeFlowBalance(sn);
}

/** Format energy kWh for display; masks numeric value when hidden. */
export function formatEnergyKwhText(value, fmt, unit, hidden) {
  const u = String(unit ?? 'kWh').trim() || 'kWh';
  if (value == null || value === '' || !Number.isFinite(Number(value))) {
    return `— ${u}`;
  }
  if (hidden) return `— ${u}`;
  return `${fmt.format(Number(value))} ${u}`;
}
