/** Current page URL without hash — safe for sharing and QR encoding. */
export function pageShareUrlFromWindow() {
  if (typeof window === 'undefined') return '';
  try {
    return window.location.href.split('#')[0];
  } catch {
    return '';
  }
}

/** Public QR image API used by share modal and inline page QR. */
export function qrImageUrl(url, size = 256, margin = 8, bgcolor = 'ffffff') {
  const data = encodeURIComponent(String(url || '').trim());
  if (!data) return '';
  const px = Math.max(64, Math.min(512, Number(size) || 256));
  const m = Math.max(0, Math.min(24, Number(margin) || 0));
  const bg = String(bgcolor).replace(/^#/, '').trim() || 'ffffff';
  return `https://api.qrserver.com/v1/create-qr-code/?size=${px}x${px}&margin=${m}&bgcolor=${encodeURIComponent(bg)}&color=000000&data=${data}`;
}
