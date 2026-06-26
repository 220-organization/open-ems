import QRCode from 'qrcode';

const FINDER_SIZE = 7;

function isInFinder(row, col, count) {
  if (row < FINDER_SIZE && col < FINDER_SIZE) return true;
  if (row < FINDER_SIZE && col >= count - FINDER_SIZE) return true;
  if (row >= count - FINDER_SIZE && col < FINDER_SIZE) return true;
  return false;
}

function fillRoundedRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
  ctx.fill();
}

function drawFinderPattern(ctx, startRow, startCol, cell, margin, color, ringColor) {
  const x = margin + startCol * cell;
  const y = margin + startRow * cell;
  const outer = FINDER_SIZE * cell;
  const ringInset = cell;
  const pupilInset = cell * 2;
  const pupilSize = cell * 3;

  ctx.fillStyle = color;
  fillRoundedRect(ctx, x, y, outer, outer, cell * 1.1);

  ctx.fillStyle = ringColor;
  fillRoundedRect(ctx, x + ringInset, y + ringInset, outer - ringInset * 2, outer - ringInset * 2, cell * 0.85);

  ctx.fillStyle = color;
  fillRoundedRect(ctx, x + pupilInset, y + pupilInset, pupilSize, pupilSize, cell * 0.65);
}

/** Dot-style QR with rounded finder eyes — matches StartPage port sticker. */
export function renderPortStickerQrCanvas(text, size, options = {}) {
  const {
    margin = 2,
    color = '#111111',
    errorCorrectionLevel = 'M',
    background = '#ffffff',
    finderRingColor = '#ffffff',
  } = options;

  const payload = String(text || '').trim();
  if (!payload || typeof document === 'undefined') {
    throw new Error('QR render unavailable');
  }

  const qr = QRCode.create(payload, { errorCorrectionLevel });
  const modules = qr.modules;
  const count = modules.size;

  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Canvas unavailable');
  }

  if (background === 'transparent') {
    ctx.clearRect(0, 0, size, size);
  } else {
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, size, size);
  }

  const inner = size - margin * 2;
  const cell = inner / count;
  const dotRadius = cell * 0.42;

  const finders = [
    [0, 0],
    [0, count - FINDER_SIZE],
    [count - FINDER_SIZE, 0],
  ];
  finders.forEach(([row, col]) => drawFinderPattern(ctx, row, col, cell, margin, color, finderRingColor));

  ctx.fillStyle = color;
  for (let row = 0; row < count; row += 1) {
    for (let col = 0; col < count; col += 1) {
      if (!modules.get(row, col) || isInFinder(row, col, count)) continue;
      const x = margin + col * cell + cell / 2;
      const y = margin + row * cell + cell / 2;
      ctx.beginPath();
      ctx.arc(x, y, dotRadius, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  return canvas;
}

export function createPortStickerQrDataUrl(text, options = {}) {
  const canvas = renderPortStickerQrCanvas(text, options.size ?? 280, options);
  return canvas.toDataURL('image/png');
}
