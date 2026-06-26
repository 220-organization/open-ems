import QRCode from 'qrcode';

/** Pixel width for canvas render — higher than CSS display size for sharp downscale. */
export function qrRenderPixelSize(displaySize) {
  const px = Math.max(32, Math.round(Number(displaySize) || 256));
  if (typeof window === 'undefined') {
    return px * 4;
  }
  const dpr = window.devicePixelRatio || 1;
  const scale = px <= 72 ? Math.max(4, Math.ceil(dpr * 2)) : Math.max(2, Math.ceil(dpr));
  return px * scale;
}

/** Standard square-module QR PNG data URL (browser only). */
export async function createRoundedQrDataUrl(text, options = {}) {
  const {
    size = 256,
    margin = 2,
    color = '#000000',
    background = '#ffffff',
    errorCorrectionLevel = 'M',
  } = options;

  const payload = String(text || '').trim();
  if (!payload || typeof document === 'undefined') return '';

  return QRCode.toDataURL(payload, {
    width: size,
    margin,
    color: { dark: color, light: background },
    errorCorrectionLevel,
  });
}
