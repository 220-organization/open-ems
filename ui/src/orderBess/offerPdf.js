/**
 * Client-side commercial-offer PDF (Ukrainian) via canvas → JPEG pages.
 * No extra npm deps — same pattern as marketplaceContractPdf.js.
 */

const PAGE_W = 1240;
const PAGE_H = 1754;
const MARGIN = 56;
const CONTENT_W = PAGE_W - MARGIN * 2;

function fmtMoney(n) {
  if (n == null || Number.isNaN(n)) return '—';
  return Number(n).toLocaleString('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function todayUk() {
  return new Date().toLocaleDateString('uk-UA');
}

function offerNumber(kw, kwh) {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const kwhR = Math.round(Number(kwh) || 0);
  return `KP-BESS-${kw || 0}-${kwhR}-${y}-${m}-${day}`;
}

function sanitizeFilenamePart(value) {
  return String(value || 'offer')
    .trim()
    .replace(/[^\w\u0400-\u04FF.-]+/g, '_')
    .slice(0, 64);
}

function wrapText(ctx, text, maxWidth) {
  const words = String(text || '').split(/\s+/).filter(Boolean);
  if (!words.length) return [''];
  const lines = [];
  let cur = words[0];
  for (let i = 1; i < words.length; i += 1) {
    const next = `${cur} ${words[i]}`;
    if (ctx.measureText(next).width <= maxWidth) {
      cur = next;
    } else {
      lines.push(cur);
      cur = words[i];
    }
  }
  lines.push(cur);
  return lines;
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function buildPdfFromJpegPages(pages) {
  const enc = new TextEncoder();
  const chunks = [];
  const objOffsets = [];
  let length = 0;

  const pushStr = str => {
    chunks.push(enc.encode(str));
    length += chunks[chunks.length - 1].length;
  };
  const pushBytes = bytes => {
    chunks.push(bytes);
    length += bytes.length;
  };
  const startObj = () => {
    objOffsets.push(length);
  };

  pushStr('%PDF-1.4\n');
  const pageRefs = [];
  const contentRefs = [];
  const imageRefs = [];
  let nextObj = 3;
  pages.forEach(() => {
    pageRefs.push(nextObj++);
    contentRefs.push(nextObj++);
    imageRefs.push(nextObj++);
  });

  startObj();
  pushStr('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n');
  startObj();
  pushStr(
    `2 0 obj\n<< /Type /Pages /Kids [${pageRefs.map(n => `${n} 0 R`).join(' ')}] /Count ${pages.length} >>\nendobj\n`
  );

  pages.forEach((page, index) => {
    const { bytes, width, height } = page;
    const contentStream = `q\n${width} 0 0 ${height} 0 0 cm\n/Im1 Do\nQ\n`;
    startObj();
    pushStr(
      `${pageRefs[index]} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] ` +
        `/Contents ${contentRefs[index]} 0 R /Resources << /XObject << /Im1 ${imageRefs[index]} 0 R >> >> >>\nendobj\n`
    );
    startObj();
    pushStr(
      `${contentRefs[index]} 0 obj\n<< /Length ${contentStream.length} >>\nstream\n${contentStream}endstream\nendobj\n`
    );
    startObj();
    pushStr(
      `${imageRefs[index]} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${width} /Height ${height} ` +
        `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${bytes.length} >>\nstream\n`
    );
    pushBytes(bytes);
    pushStr('\nendstream\nendobj\n');
  });

  const xrefOffset = length;
  pushStr(`xref\n0 ${objOffsets.length + 1}\n`);
  pushStr('0000000000 65535 f \n');
  objOffsets.forEach(offset => {
    pushStr(`${String(offset).padStart(10, '0')} 00000 n \n`);
  });
  pushStr('trailer\n');
  pushStr(`<< /Size ${objOffsets.length + 1} /Root 1 0 R >>\n`);
  pushStr('startxref\n');
  pushStr(`${xrefOffset}\n`);
  pushStr('%%EOF\n');
  return new Blob(chunks, { type: 'application/pdf' });
}

async function canvasToJpegPage(canvas) {
  const jpegBlob = await new Promise((resolve, reject) => {
    canvas.toBlob(
      result => {
        if (result) resolve(result);
        else reject(new Error('Canvas export failed'));
      },
      'image/jpeg',
      0.92
    );
  });
  const bytes = new Uint8Array(await jpegBlob.arrayBuffer());
  return { bytes, width: canvas.width, height: canvas.height };
}

function createPage() {
  const canvas = document.createElement('canvas');
  canvas.width = PAGE_W;
  canvas.height = PAGE_H;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, PAGE_W, PAGE_H);
  ctx.textBaseline = 'top';
  ctx.fillStyle = '#111827';
  return { canvas, ctx, y: MARGIN };
}

function drawFooter(ctx, pageIndex, pageCount) {
  ctx.fillStyle = '#6b7280';
  ctx.font = '18px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.fillText('Вирій ЕМС · 220-km.com · sales@220-km.com', MARGIN, PAGE_H - 44);
  const label = `${pageIndex + 1} / ${pageCount}`;
  const w = ctx.measureText(label).width;
  ctx.fillText(label, PAGE_W - MARGIN - w, PAGE_H - 44);
}

function canvasToPngBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      blob => {
        if (blob) resolve(blob);
        else reject(new Error('canvas.toBlob returned null'));
      },
      'image/png',
    );
  });
}

/**
 * Render offer pages onto canvases (shared by PDF / PNG export).
 * @returns {Promise<{ num: string, pages: HTMLCanvasElement[] }>}
 */
async function renderOrderBessOfferCanvases(offer) {
  const {
    kw,
    kwh,
    lines = [],
    totalUsd,
    totalUah,
    fxRate,
    priceLabel,
  } = offer;

  const num = offerNumber(kw, kwh);
  const pagesCanvases = [];
  let page = createPage();
  pagesCanvases.push(page);

  const ensureSpace = needed => {
    if (page.y + needed < PAGE_H - 80) return;
    page = createPage();
    pagesCanvases.push(page);
  };

  const { ctx } = page;
  // Header
  ctx.fillStyle = '#0f766e';
  ctx.fillRect(0, 0, PAGE_W, 12);
  page.y = MARGIN;

  ctx.fillStyle = '#111827';
  ctx.font = 'bold 36px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.fillText('КОМЕРЦІЙНА ПРОПОЗИЦІЯ', MARGIN, page.y);
  page.y += 48;

  ctx.font = '22px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.fillStyle = '#374151';
  ctx.fillText(`Комплект: ${kw} кВт + ${kwh} кВт·год`, MARGIN, page.y);
  page.y += 36;

  const meta = [
    ['Постачальник', 'Вирій ЕМС • 220-km.com'],
    ['Контакт', 'sales@220-km.com'],
    ['Дата', todayUk()],
    ['Номер', num],
    ['Валюта', `USD (${priceLabel || 'USD'})`],
    ['Курс (орієнтовно)', `${fxRate} грн/$`],
  ];
  ctx.font = '20px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  meta.forEach(([k, v]) => {
    ctx.fillStyle = '#6b7280';
    ctx.fillText(k, MARGIN, page.y);
    ctx.fillStyle = '#111827';
    ctx.fillText(v, MARGIN + 220, page.y);
    page.y += 28;
  });
  page.y += 16;

  ctx.font = 'bold 26px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.fillStyle = '#111827';
  ctx.fillText('Склад комплекту', MARGIN, page.y);
  page.y += 40;

  // Table header
  const cols = {
    n: MARGIN,
    name: MARGIN + 40,
    art: MARGIN + 520,
    qty: MARGIN + 820,
    unit: MARGIN + 900,
    sum: MARGIN + 1060,
  };
  const nameW = cols.art - cols.name - 12;

  const drawTableHeader = () => {
    ensureSpace(40);
    page.ctx.fillStyle = '#f3f4f6';
    page.ctx.fillRect(MARGIN, page.y - 6, CONTENT_W, 34);
    page.ctx.fillStyle = '#374151';
    page.ctx.font = 'bold 16px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
    page.ctx.fillText('№', cols.n, page.y);
    page.ctx.fillText('Найменування', cols.name, page.y);
    page.ctx.fillText('Артикул', cols.art, page.y);
    page.ctx.fillText('К-сть', cols.qty, page.y);
    page.ctx.fillText('Ціна', cols.unit, page.y);
    page.ctx.fillText('Сума', cols.sum, page.y);
    page.y += 36;
  };

  drawTableHeader();

  lines.forEach((line, idx) => {
    page.ctx.font = '16px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
    const nameLines = wrapText(page.ctx, line.name || line.article || '', nameW);
    const noteLines = line.note
      ? wrapText(page.ctx, line.note, nameW).map(s => `(${s})`)
      : [];
    const allName = [...nameLines, ...noteLines];
    const rowH = Math.max(28, allName.length * 20 + 10);
    ensureSpace(rowH + 8);
    if (page.y <= MARGIN + 2) drawTableHeader();

    page.ctx.fillStyle = '#111827';
    page.ctx.font = '16px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
    page.ctx.fillText(String(idx + 1), cols.n, page.y);
    allName.forEach((nl, i) => {
      page.ctx.fillStyle = i < nameLines.length ? '#111827' : '#6b7280';
      page.ctx.fillText(nl, cols.name, page.y + i * 20);
    });
    page.ctx.fillStyle = '#111827';
    page.ctx.font = '15px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
    const artLines = wrapText(page.ctx, line.article || '', cols.qty - cols.art - 8);
    artLines.slice(0, 2).forEach((al, i) => {
      page.ctx.fillText(al, cols.art, page.y + i * 18);
    });
    page.ctx.fillText(String(line.qty ?? ''), cols.qty, page.y);
    page.ctx.fillText(fmtMoney(line.unit), cols.unit, page.y);
    page.ctx.fillText(fmtMoney(line.lineTotal), cols.sum, page.y);
    page.y += rowH;

    // light separator
    page.ctx.strokeStyle = '#e5e7eb';
    page.ctx.beginPath();
    page.ctx.moveTo(MARGIN, page.y - 4);
    page.ctx.lineTo(PAGE_W - MARGIN, page.y - 4);
    page.ctx.stroke();
  });

  page.y += 20;
  ensureSpace(100);
  page.ctx.font = 'bold 22px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  page.ctx.fillStyle = '#111827';
  page.ctx.fillText(`Разом: $${fmtMoney(totalUsd)} (${priceLabel || 'USD'})`, MARGIN, page.y);
  page.y += 32;
  page.ctx.font = '20px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  page.ctx.fillStyle = '#374151';
  page.ctx.fillText(`Орієнтовно: ${fmtMoney(totalUah)} грн (курс ${fxRate})`, MARGIN, page.y);
  page.y += 40;

  ensureSpace(200);
  page.ctx.font = 'bold 24px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  page.ctx.fillStyle = '#111827';
  page.ctx.fillText('Умови', MARGIN, page.y);
  page.y += 32;
  page.ctx.font = '18px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  page.ctx.fillStyle = '#374151';
  const terms = [
    'Ціни вказані в USD. Курс грн/$ — орієнтовний.',
    'Не включено: монтаж, ПНР, кабель AC/DC (окрім штатних зʼєднань), щитове обладнання, дозволи.',
    'Пропозиція дійсна 14 календарних днів, якщо не зазначено інше.',
    'Гарантія — згідно з умовами виробника / постачальника.',
  ];
  terms.forEach((term, i) => {
    const wrapped = wrapText(page.ctx, `${i + 1}. ${term}`, CONTENT_W);
    ensureSpace(wrapped.length * 24 + 8);
    wrapped.forEach(wl => {
      page.ctx.fillText(wl, MARGIN, page.y);
      page.y += 24;
    });
    page.y += 6;
  });

  page.y += 24;
  ensureSpace(80);
  page.ctx.font = '20px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  page.ctx.fillStyle = '#111827';
  page.ctx.fillText('З повагою,', MARGIN, page.y);
  page.y += 28;
  page.ctx.font = 'bold 20px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  page.ctx.fillText('Максим Павлов, СЕО • Вирій EMS / 220-km.com Ukraine', MARGIN, page.y);

  const pageCount = pagesCanvases.length;
  pagesCanvases.forEach((p, i) => drawFooter(p.ctx, i, pageCount));

  return { num, pages: pagesCanvases.map(p => p.canvas) };
}

function stitchCanvasesVertically(canvases) {
  const width = Math.max(...canvases.map(c => c.width));
  const height = canvases.reduce((s, c) => s + c.height, 0);
  const out = document.createElement('canvas');
  out.width = width;
  out.height = height;
  const ctx = out.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);
  let y = 0;
  canvases.forEach(c => {
    ctx.drawImage(c, 0, y);
    y += c.height;
  });
  return out;
}

/**
 * @param {object} offer
 * @param {number} offer.kw
 * @param {number} offer.kwh
 * @param {Array<{name, article, code, qty, unit, lineTotal, note, availability}>} offer.lines
 * @param {number|null} offer.totalUsd
 * @param {number|null} offer.totalUah
 * @param {number} offer.fxRate
 * @param {string} offer.priceLabel — e.g. "USD з ПДВ"
 * @param {string} offer.businessType — fop|vat|cash
 */
export async function downloadOrderBessOfferPdf(offer) {
  if (typeof window === 'undefined') return;

  const { num, pages } = await renderOrderBessOfferCanvases(offer);
  const jpegPages = [];
  for (const canvas of pages) {
    // eslint-disable-next-line no-await-in-loop
    jpegPages.push(await canvasToJpegPage(canvas));
  }

  const pdfBlob = buildPdfFromJpegPages(jpegPages);
  triggerBlobDownload(pdfBlob, `${sanitizeFilenamePart(num)}.pdf`);
}

/** Same commercial offer as PNG (pages stacked vertically when multi-page). */
export async function downloadOrderBessOfferPng(offer) {
  if (typeof window === 'undefined') return;

  const { num, pages } = await renderOrderBessOfferCanvases(offer);
  const canvas = pages.length === 1 ? pages[0] : stitchCanvasesVertically(pages);
  const blob = await canvasToPngBlob(canvas);
  triggerBlobDownload(blob, `${sanitizeFilenamePart(num)}.png`);
}
