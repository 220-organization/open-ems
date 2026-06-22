import QRCode from 'qrcode';

/** Rounded-dot QR PNG data URL with transparent background (browser only). */
export async function createRoundedQrDataUrl(text, options = {}) {
  const {
    size = 256,
    margin = 4,
    color = '#ffffff',
    errorCorrectionLevel = 'M',
  } = options;

  const payload = String(text || '').trim();
  if (!payload || typeof document === 'undefined') return '';

  const qr = QRCode.create(payload, { errorCorrectionLevel });
  const modules = qr.modules;
  const count = modules.size;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return '';

  ctx.clearRect(0, 0, size, size);
  const inner = size - margin * 2;
  const cell = inner / count;
  const radius = cell * 0.45;

  ctx.fillStyle = color;
  for (let row = 0; row < count; row += 1) {
    for (let col = 0; col < count; col += 1) {
      if (!modules.get(row, col)) continue;
      const x = margin + col * cell + cell / 2;
      const y = margin + row * cell + cell / 2;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  return canvas.toDataURL('image/png');
}
