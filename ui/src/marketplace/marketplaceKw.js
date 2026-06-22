export const KW_OPTIONS = ['7', '22', '40', '60', '120', '240', '480'];

/** Normalize stored values like "80+" or "7 kW" and render as "7 kW". */
export function formatKwLabel(kwAvailable) {
  const raw = String(kwAvailable || '').trim();
  if (!raw) return '—';
  const num = raw.replace(/\+$/, '').replace(/\s*kW$/i, '').trim();
  return `${num} kW`;
}
