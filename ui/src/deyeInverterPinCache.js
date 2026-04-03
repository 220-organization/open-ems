/**
 * Remember inverter write PIN in localStorage for 24h per deviceSn (browser-only; XSS-sensitive).
 */

const STORAGE_KEY = 'pf-deye-inverter-pin-cache';
const TTL_MS = 24 * 60 * 60 * 1000;

function loadAll() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const all = JSON.parse(raw);
    return all && typeof all === 'object' ? all : {};
  } catch {
    return {};
  }
}

function saveAll(all) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
  } catch {
    /* ignore quota / private mode */
  }
}

/** Non-empty PIN string if cached and not expired; otherwise ''. */
export function readCachedInverterPin(deviceSn) {
  const sn = String(deviceSn || '').trim();
  if (!sn) return '';
  const all = loadAll();
  const row = all[sn];
  if (!row || typeof row.pin !== 'string' || typeof row.exp !== 'number') return '';
  if (Date.now() > row.exp) {
    delete all[sn];
    saveAll(all);
    return '';
  }
  return row.pin;
}

/** Store PIN; refreshes 24h window from now. */
export function rememberInverterPin(deviceSn, pin) {
  const sn = String(deviceSn || '').trim();
  const p = String(pin || '').trim();
  if (!sn || !p) return;
  const all = loadAll();
  all[sn] = { pin: p, exp: Date.now() + TTL_MS };
  saveAll(all);
}

export function clearInverterPinCache(deviceSn) {
  const sn = String(deviceSn || '').trim();
  if (!sn) return;
  const all = loadAll();
  if (!(sn in all)) return;
  delete all[sn];
  saveAll(all);
}
