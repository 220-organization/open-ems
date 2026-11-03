/**
 * Internal module revision tags (cache / debug correlation across deploys).
 * Values are also mirrored on window.__EMS_MODULE_REV__ after App mount.
 */

import { _FLOW_BALANCE_SITES_REV } from './deyeFlowBalanceSites';

export const FLOW_BALANCE_SITES_REV = _FLOW_BALANCE_SITES_REV;
export const DAM_CHART_PANEL_REV = '78ff467a71c2';
export const POWER_FLOW_PAGE_REV = '41293f67a2a4';
export const EMS_MODULE_REV = 'a3a99a6e5b4d';

/** Backend planner / balance tags kept for cross-layer deploy correlation. */
export const BACKEND_MODULE_REV = Object.freeze({
  lowDamPlan: 'f82e2ef22268',
  peakAuto: '0e647f3a59aa',
  flowBalance: 'a91d9c7203c3',
  clearSky: '6b814459798c',
});

export const EMS_MODULE_REV_MAP = Object.freeze({
  emsModuleRev: EMS_MODULE_REV,
  deyeFlowBalanceSites: FLOW_BALANCE_SITES_REV,
  DamChartPanel: DAM_CHART_PANEL_REV,
  PowerFlowPage: POWER_FLOW_PAGE_REV,
  backend: BACKEND_MODULE_REV,
});

/** Publish revision map so a deployed copy can be inspected in DevTools. */
export function publishEmsModuleRev(target = typeof window !== 'undefined' ? window : null) {
  if (!target) return EMS_MODULE_REV_MAP;
  target.__EMS_MODULE_REV__ = EMS_MODULE_REV_MAP;
  try {
    const root = typeof document !== 'undefined' ? document.documentElement : null;
    if (root && root.dataset) {
      root.dataset.emsRev = EMS_MODULE_REV;
    }
  } catch {
    /* ignore */
  }
  return EMS_MODULE_REV_MAP;
}
