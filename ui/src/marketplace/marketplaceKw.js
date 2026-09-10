export const KW_MIN = 7;
export const KW_MAX = 5000;
export const KW_STEP = 10;
export const KW_DEFAULT = KW_MIN;
/** Range input uses 0 = 7 kW, then 1 = 10 kW … 500 = 5000 kW. */
export const KW_SLIDER_MAX_INDEX = KW_MAX / KW_STEP;

/**
 * Snap to 7 kW, then 10 kW steps up to 5000 kW.
 */
export function snapKwValue(raw) {
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= KW_MIN) return KW_MIN;
  if (n >= KW_MAX) return KW_MAX;
  if (n < (KW_MIN + KW_STEP) / 2) return KW_MIN;
  const toStep = Math.round(n / KW_STEP) * KW_STEP;
  if (toStep < KW_STEP) return KW_MIN;
  return Math.min(KW_MAX, toStep);
}

export function kwFromSliderIndex(index) {
  const i = Number(index);
  if (!Number.isFinite(i) || i <= 0) return KW_MIN;
  return Math.min(KW_MAX, KW_STEP * i);
}

export function sliderIndexFromKw(raw) {
  const n = snapKwValue(raw);
  if (n <= KW_MIN) return 0;
  return n / KW_STEP;
}

/** Normalize stored values like "80+" or "7 kW" and render as "7 kW". */
export function formatKwLabel(kwAvailable) {
  const raw = String(kwAvailable || '').trim();
  if (!raw) return '—';
  const num = raw.replace(/\+$/, '').replace(/\s*kW$/i, '').trim();
  return `${num} kW`;
}

export function parseKwNumber(kwAvailable) {
  const raw = String(kwAvailable || '').trim();
  const num = Number(raw.replace(/\+$/, '').replace(/\s*kW$/i, '').trim());
  return Number.isFinite(num) && num > 0 ? num : KW_MIN;
}

export const MARKER_SIZE_MIN_PX = 36;
export const MARKER_SIZE_MAX_PX = 92;

/** Log scale so 7 kW vs 240 kW vs 5000 kW stay distinct on the map. */
export function markerSizePxForKw(kwAvailable) {
  const kw = Math.min(KW_MAX, Math.max(KW_MIN, parseKwNumber(kwAvailable)));
  const t = Math.log(kw / KW_MIN) / Math.log(KW_MAX / KW_MIN);
  return Math.round(MARKER_SIZE_MIN_PX + t * (MARKER_SIZE_MAX_PX - MARKER_SIZE_MIN_PX));
}

export function markerFontPxForKw(kwAvailable) {
  const size = markerSizePxForKw(kwAvailable);
  const t = (size - MARKER_SIZE_MIN_PX) / (MARKER_SIZE_MAX_PX - MARKER_SIZE_MIN_PX);
  return Math.round(8 + t * 6);
}
