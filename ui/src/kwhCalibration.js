import { usesDeyeFlowBalance } from './deyeFlowBalanceSites';

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
