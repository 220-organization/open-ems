/** ESS source prefix in Power flow inverter <select> (localStorage + URL). */

export const ESS_PREFIX_DEYE = 'deye:';
export const ESS_PREFIX_HUAWEI = 'huawei:';
export const ESS_PREFIX_DC_EV = 'dc-ev:';
export const ESS_PREFIX_AC_EV = 'ac-ev:';

const EV_PORT_PREFIXES = [ESS_PREFIX_DEYE, ESS_PREFIX_HUAWEI, ESS_PREFIX_DC_EV, ESS_PREFIX_AC_EV];

export function normalizeEssSelectionValue(raw) {
  const s = String(raw || '').trim();
  if (!s) return '';
  if (EV_PORT_PREFIXES.some(prefix => s.startsWith(prefix))) return s;
  if (/^\d{6,32}$/.test(s)) return ESS_PREFIX_DEYE + s;
  return s;
}

export function parseEssSelection(value) {
  const s = normalizeEssSelectionValue(value);
  if (!s) return { provider: null, id: '' };
  if (s.startsWith(ESS_PREFIX_DEYE)) return { provider: 'deye', id: s.slice(ESS_PREFIX_DEYE.length) };
  if (s.startsWith(ESS_PREFIX_HUAWEI)) return { provider: 'huawei', id: s.slice(ESS_PREFIX_HUAWEI.length) };
  if (s.startsWith(ESS_PREFIX_DC_EV)) return { provider: 'dc-ev', id: s.slice(ESS_PREFIX_DC_EV.length) };
  if (s.startsWith(ESS_PREFIX_AC_EV)) return { provider: 'ac-ev', id: s.slice(ESS_PREFIX_AC_EV.length) };
  return { provider: null, id: '' };
}

/** acdc query for GET /api/b2b/ev-ports-power when an EV port aggregate source is selected. */
export function evPortsAcdcFromProvider(provider) {
  if (provider === 'dc-ev') return 'dc';
  if (provider === 'ac-ev') return 'ac';
  return null;
}
