/**
 * Strip trailing " pin<digits>" from Deye plant/device names for UI (matches server deye_inverter_pin).
 */
const PIN_SUFFIX_RE = /\s+pin(\d{1,12})\s*$/i;

export function stripInverterPinForDisplay(text) {
  const s = String(text ?? '').trim();
  if (!s) return s;
  return s.replace(PIN_SUFFIX_RE, '').trimEnd();
}

/** Short label for inverter <select>: first segment of "Plant — Device", PIN-free. */
export function inverterSelectShortLabel(rawLabel, deviceSnFallback) {
  const raw = String(rawLabel || '').trim();
  if (!raw) return String(deviceSnFallback || '').trim();
  const parts = raw.split(' — ').map(p => stripInverterPinForDisplay(p.trim()));
  const first = parts.find(Boolean);
  return first || stripInverterPinForDisplay(raw) || String(deviceSnFallback || '').trim();
}
