import { VYRIY_EMS_LOGO_SRC } from './vyriyEmsLogo';

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
