/** Build PDF with embedded JPEG pages (DCTDecode) and trigger browser download. */

function loadImageElement(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Image load failed'));
    img.src = url;
  });
}

async function imageUrlToJpegBytes(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error('Image fetch failed');
  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);
  try {
    const img = await loadImageElement(blobUrl);
    const width = img.naturalWidth || img.width;
    const height = img.naturalHeight || img.height;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, width, height);

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
    return { bytes, width, height };
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
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

function sanitizeFilenamePart(value) {
  return String(value || 'owner')
    .trim()
    .replace(/[^\w\u0400-\u04FF.-]+/g, '_')
    .slice(0, 48);
}

/** Download contract photo(s) as a single PDF (one page per photo). */
export async function downloadContractPhotosAsPdf(photoUrls, ownerName = 'owner') {
  const urls = (photoUrls || []).filter(Boolean);
  if (!urls.length || typeof window === 'undefined') return;

  const pages = [];
  for (const url of urls) {
    // eslint-disable-next-line no-await-in-loop
    pages.push(await imageUrlToJpegBytes(url));
  }

  const pdfBlob = buildPdfFromJpegPages(pages);
  triggerBlobDownload(pdfBlob, `distribution-contract-${sanitizeFilenamePart(ownerName)}.pdf`);
}
