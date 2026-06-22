/** Current page URL without hash — safe for sharing and QR encoding. */
export function pageShareUrlFromWindow() {
  if (typeof window === 'undefined') return '';
  try {
    return window.location.href.split('#')[0];
  } catch {
    return '';
  }
}
