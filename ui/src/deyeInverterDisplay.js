/**
 * Remove " pin<digits>" tokens from Deye plant/device names for UI (any position, not only trailing).
 * Server-side PIN verification still uses the raw name from Deye; this is display-only.
 */
const PIN_TOKEN_RE = /\bpin\d{1,12}\b/gi;

export function stripInverterPinForDisplay(text) {
  const s = String(text ?? '').trim();
  if (!s) return s;
  return s
    .replace(PIN_TOKEN_RE, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

/** Last ``pin<digits>`` token in the label (for write PIN when not yet cached). */
export function extractInverterPinFromLabel(text) {
  const s = String(text ?? '').trim();
  if (!s) return '';
  const re = /\bpin(\d{1,12})\b/gi;
  let last = '';
  let m;
  while ((m = re.exec(s)) !== null) {
    last = m[1];
  }
  return last;
}

/** Match ``evport<station>`` in plant/device names (same as backend EV port binding). */
const EVPORT_RE = /evport\s*(\d+)/gi;
/** Optional CSV list: ``evports634,635`` */
const EVPORTS_CSV_RE = /evports\s*([\d,\s]+)/i;

/** Deye device SN → EV port numbers when the cloud label has no ``evport`` token yet. */
const DEVICE_EV_PORTS = Object.freeze({
  '2503291038': ['634', '635'],
});

/** Station number from label, e.g. ``"738"``, or null if no ``evport`` token. */
export function parseEvPortStationNumber(text) {
  const nums = parseEvPortStationNumbers(text);
  return nums.length > 0 ? nums[0] : null;
}

/** All EV port station numbers from label tokens and optional device SN map. */
export function parseEvPortStationNumbers(text) {
  const s = String(text ?? '').trim();
  if (!s) return [];
  const numbers = new Set();
  const csv = EVPORTS_CSV_RE.exec(s);
  if (csv) {
    for (const part of csv[1].split(/[,\s]+/)) {
      const n = part.trim();
      if (n) numbers.add(n);
    }
  }
  let m;
  const re = new RegExp(EVPORT_RE.source, EVPORT_RE.flags);
  while ((m = re.exec(s)) !== null) {
    const n = String(m[1] || '').trim();
    if (n) numbers.add(n);
  }
  return [...numbers].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/** Label ``evport`` / ``evports`` tokens, else per-device map (e.g. Ярмаркова 11-З). */
export function evPortStationNumbersForInverter(deviceSn, label) {
  const fromLabel = parseEvPortStationNumbers(label);
  if (fromLabel.length > 0) return fromLabel;
  const sn = String(deviceSn ?? '').trim();
  const mapped = DEVICE_EV_PORTS[sn];
  return mapped ? [...mapped] : [];
}

/** Short label for inverter <select>: first segment of "Plant — Device", PIN-free. */
export function inverterSelectShortLabel(rawLabel, deviceSnFallback) {
  const raw = String(rawLabel || '').trim();
  if (!raw) return String(deviceSnFallback || '').trim();
  const parts = raw.split(' — ').map(p => stripInverterPinForDisplay(p.trim()));
  const first = parts.find(Boolean);
  return first || stripInverterPinForDisplay(raw) || String(deviceSnFallback || '').trim();
}
