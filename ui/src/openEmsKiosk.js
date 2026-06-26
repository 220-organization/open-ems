/** Query param for full-screen white kiosk (QR only), like B2B `graphView=1`. */
export const OPEN_EMS_KIOSK_PARAM = 'kiosk';

export function isOpenEmsKioskSearch(search) {
  try {
    const raw = typeof search === 'string' ? search : '';
    const v = new URLSearchParams(raw.startsWith('?') ? raw.slice(1) : raw).get(OPEN_EMS_KIOSK_PARAM);
    return v === '1' || v === 'true';
  } catch {
    return false;
  }
}

export function isOpenEmsKioskUrl(href = '') {
  try {
    const u = new URL(href || (typeof window !== 'undefined' ? window.location.href : 'http://localhost/'));
    return isOpenEmsKioskSearch(u.search);
  } catch {
    return false;
  }
}

/** Remove kiosk flag from URL (exit kiosk without losing market/zone/inverter state). */
export function openEmsUrlWithoutKiosk(href) {
  try {
    const u = new URL(href || (typeof window !== 'undefined' ? window.location.href : 'http://localhost/'));
    u.searchParams.delete(OPEN_EMS_KIOSK_PARAM);
    return u.toString();
  } catch {
    return href || '';
  }
}

/** Add kiosk=1 to URL (preserves market, zone, inverter, etc.). */
export function openEmsUrlWithKiosk(href) {
  try {
    const u = new URL(href || (typeof window !== 'undefined' ? window.location.href : 'http://localhost/'));
    u.searchParams.set(OPEN_EMS_KIOSK_PARAM, '1');
    return u.toString();
  } catch {
    return href || '';
  }
}
