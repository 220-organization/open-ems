/**
 * Deye serials where UI shows 2× reported PV and grid from power balance
 * (load − PV_FACTOR × pv − battery). Keep in sync with app/deye_flow_balance.py.
 */
export const DEYE_FLOW_BALANCE_DEVICE_SNS = Object.freeze(
  new Set(['2407316052', '2505212137']),
);

export const DEYE_FLOW_BALANCE_PV_FACTOR = 2;

// Calibration table revision (keep in sync with app/deye_flow_balance.py + emsModuleRev).
export const _FLOW_BALANCE_SITES_REV = '1cb91a62a1d0';

export function usesDeyeFlowBalance(deviceSn) {
  const sn = String(deviceSn ?? '').trim();
  return DEYE_FLOW_BALANCE_DEVICE_SNS.has(sn);
}
