import { VYRIY_EMS_LOGO_SRC } from './vyriyEmsLogo';
import { notifyOpenEmsSearchChange } from './sharePageQr';

const staticBase = `${process.env.PUBLIC_URL || ''}/static/partners`;

/** Hub carousel: Open EMS + EV charging partners (3 s per slide). */
export const HUB_PARTNER_PROMOTIONS = [
  {
    id: 'vyriy',
    name: 'Open EMS',
    url: 'https://220-km.com',
    logoSrc: VYRIY_EMS_LOGO_SRC,
    hubLabelKey: 'hubLabel',
  },
  {
    id: 'dtek-kem',
    name: 'ДТЕК Київські електромережі',
    url: 'https://www.dtek-kem.com.ua/ua',
    logoSrc: `${staticBase}/dtek-kem.svg`,
    logoWide: true,
  },
  {
    id: 'ecu',
    name: 'ЕКУ — агрегована група',
    url: 'https://ecu.gov.ua/power/aggregated_group',
    logoSrc: `${staticBase}/ecu.svg`,
    logoWide: true,
  },
  {
    id: 'gridlab',
    name: 'GridLab EMS',
    url: 'https://gridlab.com.ua/uk',
    logoSrc: `${staticBase}/gridlab.png`,
    logoWide: true,
  },
  {
    id: 'eva',
    name: 'EVA Chargers',
    url: 'https://www.evachargers.com/uk',
    logoSrc: `${staticBase}/eva.svg`,
  },
  {
    id: 'evboost',
    name: 'EVBOOST',
    url: 'https://www.evboost.com.ua/',
    logoSrc: `${staticBase}/evboost.ico`,
  },
  {
    id: 'toka',
    name: 'TOKA',
    url: 'https://toka.energy/',
    logoSrc: `${staticBase}/toka.png`,
    logoWide: true,
  },
  {
    id: 'icar',
    name: 'iCAR',
    url: 'https://icar.ua/',
    logoSrc: `${staticBase}/icar-512.jpg`,
  },
  {
    id: 'octa',
    name: 'Octa Energy',
    url: 'https://www.octa.energy/ru/',
    logoSrc: `${staticBase}/octa.png`,
  },
  {
    id: 'eltis',
    name: 'Eltis-Master',
    url: 'https://eltis-master.com.ua/',
    logoSrc: `${staticBase}/eltis.png`,
  },
  {
    id: 'eds',
    name: 'EDS Chargers',
    url: 'https://eds-chargers.com/',
    logoSrc: `${staticBase}/eds.svg`,
  },
  {
    id: 'biom',
    name: 'BIOM',
    url: 'https://biom.ua/',
    logoSrc: `${staticBase}/biom.svg`,
  },
  {
    id: 'evua',
    name: 'EV UA',
    url: 'https://evua.site/',
    logoSrc: `${staticBase}/evua.png`,
  },
  {
    id: 'ugv',
    name: 'UGV Chargers',
    url: 'https://ugv.ua/ru/',
    logoSrc: `${staticBase}/ugv.ico`,
  },
  {
    id: 'nd',
    name: 'ND Group',
    url: 'https://nd-group.net/',
    logoSrc: `${staticBase}/nd.png`,
  },
  {
    id: 'etg',
    name: 'ETG.UA',
    url: 'https://etg.ua/en/contacts',
    logoSrc: `${staticBase}/etg.svg`,
  },
  {
    id: 'eport',
    name: 'E-Port',
    url: 'https://e-port.energy/',
    logoSrc: `${staticBase}/eport.png`,
    logoWide: true,
  },
];

export const HUB_PARTNER_FLIP_MS = 3000;

/** Query key that pins the hub logo in shareable URLs (`?logo=dtek-kem`). */
export const HUB_LOGO_QUERY_PARAM = 'logo';

export function hubPartnerIndexById(id) {
  const key = String(id || '').trim();
  if (!key) return -1;
  return HUB_PARTNER_PROMOTIONS.findIndex(p => p.id === key);
}

export function readPinnedHubLogoIndexFromUrl(search) {
  try {
    const raw = search ?? (typeof window !== 'undefined' ? window.location.search : '');
    const q = raw.startsWith('?') ? raw.slice(1) : raw;
    return hubPartnerIndexById(new URLSearchParams(q).get(HUB_LOGO_QUERY_PARAM));
  } catch {
    return -1;
  }
}

/**
 * Pin or unpin hub logo in the current URL (replaceState) so share/QR keep the same partner.
 * @param {string | null | undefined} partnerId
 */
export function replaceUrlHubLogo(partnerId) {
  if (typeof window === 'undefined') return;
  try {
    const u = new URL(window.location.href);
    const id = String(partnerId || '').trim();
    if (id && hubPartnerIndexById(id) >= 0) u.searchParams.set(HUB_LOGO_QUERY_PARAM, id);
    else u.searchParams.delete(HUB_LOGO_QUERY_PARAM);
    window.history.replaceState({}, '', u);
    notifyOpenEmsSearchChange();
  } catch {
    /* ignore */
  }
}
