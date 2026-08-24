/** SPA route ids for Open EMS UI (pathname-based, no react-router). */
export const OPEN_EMS_ROUTES = {
  power: '/',
  landing: '/about',
  evTv: '/ev-tv',
  marketplace: '/marketplace',
  orderBess: '/order-bess',
  rdnConsultation: '/rdn-consultation',
};

const LEGACY_POWER_PATH = '/power-flow';
const LEGACY_DAM_PATH = '/dam-chart';

/** Redirect legacy `/dam-chart` bookmarks to demo (`/`), keeping query string for chart state. */
export function redirectLegacyDamChartPath() {
  try {
    const p = (window.location.pathname || '/').replace(/\/$/, '') || '/';
    if (p !== LEGACY_DAM_PATH) return false;
    const u = new URL(window.location.href);
    u.pathname = OPEN_EMS_ROUTES.power;
    window.history.replaceState({}, '', u);
    return true;
  } catch {
    return false;
  }
}

export function normalizeOpenEmsPathname(pathname) {
  const p = (pathname || '/').replace(/\/$/, '') || '/';
  if (p === OPEN_EMS_ROUTES.landing) return OPEN_EMS_ROUTES.landing;
  if (p === OPEN_EMS_ROUTES.evTv) return OPEN_EMS_ROUTES.evTv;
  if (p === OPEN_EMS_ROUTES.marketplace) return OPEN_EMS_ROUTES.marketplace;
  if (p === OPEN_EMS_ROUTES.orderBess) return OPEN_EMS_ROUTES.orderBess;
  if (p === OPEN_EMS_ROUTES.rdnConsultation) return OPEN_EMS_ROUTES.rdnConsultation;
  if (p === OPEN_EMS_ROUTES.power || p === LEGACY_POWER_PATH || p === LEGACY_DAM_PATH) {
    return OPEN_EMS_ROUTES.power;
  }
  return OPEN_EMS_ROUTES.power;
}

export function resolveOpenEmsPage(pathname) {
  const path = normalizeOpenEmsPathname(pathname);
  if (path === OPEN_EMS_ROUTES.landing) return 'landing';
  if (path === OPEN_EMS_ROUTES.evTv) return 'evTv';
  if (path === OPEN_EMS_ROUTES.marketplace) return 'marketplace';
  if (path === OPEN_EMS_ROUTES.orderBess) return 'orderBess';
  if (path === OPEN_EMS_ROUTES.rdnConsultation) return 'rdnConsultation';
  return 'power';
}
