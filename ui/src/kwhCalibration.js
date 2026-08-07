import { usesDeyeFlowBalance } from './deyeFlowBalanceSites';

/**
 * Deye serials with flow-balance kWh derivation are treated as calibrated.
 * All other Deye inverters show approximate (~) energy values — no modal gate.
 */
export function inverterNeedsKwhCalibration(deviceSn) {
  const sn = String(deviceSn ?? '').trim();
  if (!sn) return false;
  return !usesDeyeFlowBalance(sn);
}

/**
 * Format energy kWh for display.
 * When ``approximate`` is true, prefixes the value with ``~`` (tilde).
 */
export function formatEnergyKwhText(value, fmt, unit, approximate = false) {
  const u = String(unit ?? 'kWh').trim() || 'kWh';
  if (value == null || value === '' || !Number.isFinite(Number(value))) {
    return `— ${u}`;
  }
  const num = fmt.format(Number(value));
  return approximate ? `~ ${num} ${u}` : `${num} ${u}`;
}
