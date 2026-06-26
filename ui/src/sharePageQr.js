/** Current page URL without hash — safe for sharing and QR encoding. */
export function pageShareUrlFromWindow(options = {}) {
  if (typeof window === 'undefined') return '';
  const { stripParams = [] } = options;
  try {
    const u = new URL(window.location.href.split('#')[0]);
    stripParams.forEach(key => u.searchParams.delete(key));
    return u.toString();
  } catch {
    return '';
  }
}
