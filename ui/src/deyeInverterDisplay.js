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
const EVPORT_RE = /evport\s*(\d+)/i;

/** Station number from label, e.g. ``"738"``, or null if no ``evport`` token. */
export function parseEvPortStationNumber(text) {
  const s = String(text ?? '').trim();
  if (!s) return null;
  const m = EVPORT_RE.exec(s);
  return m ? m[1].trim() : null;
}

/** Short label for inverter <select>: first segment of "Plant — Device", PIN-free. */
export function inverterSelectShortLabel(rawLabel, deviceSnFallback) {
  const raw = String(rawLabel || '').trim();
  if (!raw) return String(deviceSnFallback || '').trim();
  const parts = raw.split(' — ').map(p => stripInverterPinForDisplay(p.trim()));
  const first = parts.find(Boolean);
  return first || stripInverterPinForDisplay(raw) || String(deviceSnFallback || '').trim();
}
