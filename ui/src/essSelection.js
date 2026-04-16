/** ESS source prefix in Power flow inverter <select> (localStorage + URL). */

export const ESS_PREFIX_DEYE = 'deye:';
export const ESS_PREFIX_HUAWEI = 'huawei:';

export function normalizeEssSelectionValue(raw) {
  const s = String(raw || '').trim();
  if (!s) return '';
  if (s.startsWith(ESS_PREFIX_DEYE) || s.startsWith(ESS_PREFIX_HUAWEI)) return s;
  if (/^\d{6,32}$/.test(s)) return ESS_PREFIX_DEYE + s;
  return s;
}

export function parseEssSelection(value) {
  const s = normalizeEssSelectionValue(value);
  if (!s) return { provider: null, id: '' };
  if (s.startsWith(ESS_PREFIX_DEYE)) return { provider: 'deye', id: s.slice(ESS_PREFIX_DEYE.length) };
  if (s.startsWith(ESS_PREFIX_HUAWEI)) return { provider: 'huawei', id: s.slice(ESS_PREFIX_HUAWEI.length) };
  return { provider: null, id: '' };
}
