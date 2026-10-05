/**
 * Slow-link detection for the boot splash and the in-app notice.
 * The same thresholds are inlined in public/index.html so they run before the bundle.
 */

export const SLOW_NOTICE_DELAY_MS = 8000;
export const SLOW_RTT_MS = 1500;
export const SLOW_DOWNLINK_MBPS = 0.4;

export function readConnection(nav) {
  if (!nav) return null;
  return nav.connection || nav.mozConnection || nav.webkitConnection || null;
}

/** Local webpack compiles are slow without a slow link. Production still uses the boot timer. */
export function shouldArmSlowNoticeTimer(hostname) {
  const host = String(hostname || '').toLowerCase();
  return host !== 'localhost' && host !== '127.0.0.1' && host !== '::1';
}

/**
 * @param {object | null | undefined} connection Network Information API snapshot
 * @param {boolean} [onLine]
 */
export function isSlowConnection(connection, onLine) {
  if (onLine === false) return true;
  if (!connection) return false;
  if (connection.saveData) return true;
  const type = connection.effectiveType;
  if (type === 'slow-2g' || type === '2g') return true;
  if (typeof connection.rtt === 'number' && connection.rtt >= SLOW_RTT_MS) return true;
  if (
    typeof connection.downlink === 'number' &&
    connection.downlink > 0 &&
    connection.downlink < SLOW_DOWNLINK_MBPS
  ) {
    return true;
  }
  return false;
}
