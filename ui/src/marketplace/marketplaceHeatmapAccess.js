const HEATMAP_UNLOCK_STORAGE_KEY = 'marketplaceHeatmapZoomUnlock';
const KYIV_TIME_ZONE = 'Europe/Kyiv';

function kyivCalendarDay(date = new Date()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: KYIV_TIME_ZONE }).format(date);
}

function readUnlockRecord() {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(HEATMAP_UNLOCK_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed;
  } catch {
    return null;
  }
}

export function isHeatmapZoomUnlocked() {
  const record = readUnlockRecord();
  if (!record?.day || !record?.paymentId) return false;
  return record.day === kyivCalendarDay();
}

export function storeHeatmapZoomUnlock(paymentId) {
  if (!paymentId || typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      HEATMAP_UNLOCK_STORAGE_KEY,
      JSON.stringify({ day: kyivCalendarDay(), paymentId: String(paymentId) })
    );
  } catch {
    /* ignore quota / private mode */
  }
}

/** Dev-only unlock when backend test payment is unavailable (localhost UI). */
export function storeHeatmapZoomUnlockLocalDev() {
  if (typeof window === 'undefined') return;
  const { hostname } = window.location;
  if (hostname !== 'localhost' && hostname !== '127.0.0.1') return;
  storeHeatmapZoomUnlock('local-dev');
}

export function isMarketplaceUiLocalDev() {
  if (typeof window === 'undefined') return false;
  const { hostname } = window.location;
  return hostname === 'localhost' || hostname === '127.0.0.1';
}
