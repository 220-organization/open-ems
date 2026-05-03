import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import './dam-chart.css';
import { DEYE_FLOW_BALANCE_PV_FACTOR, usesDeyeFlowBalance } from './deyeFlowBalanceSites';
import HuaweiTotalsPanel from './HuaweiTotalsPanel';
import { OREE_DAM_CHART_URL } from './OreeDamChartModal';
import { useTheme } from './useTheme';

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  if (!base) return path;
  return `${base}${path}`;
}

/** Matches `dam-chart.css` — on small screens Y-axis labels are hidden; series stay toggleable via legend. */
const DAM_CHART_MOBILE_MAX_PX = 600;

function useDamChartMobileLayout() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(`(max-width: ${DAM_CHART_MOBILE_MAX_PX}px)`).matches
  );
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${DAM_CHART_MOBILE_MAX_PX}px)`);
    const onChange = () => setIsMobile(mq.matches);
    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return isMobile;
}

const DAM_INDEX_KEYS = ['DAY', 'NIGHT', 'PEAK', 'HPEAK', 'BASE'];

const ENTSOE_ZONE_OPTIONS = [
  { value: 'ES', label: 'Spain (ES)' },
  { value: 'PL', label: 'Poland (PL)' },
];

/** ENTSO-E zones on the Ukraine (OREE) chart — EUR/kWh (or UAH/kWh via NBU); includes UA bidding zone as alternative to OREE. */
const ENTSOE_OREE_OVERLAY_ZONES = ['ES', 'PL', 'UA_ENTSO'];

/**
 * OREE ENTSO-E overlay tokens in ``currency`` / ``damOverlay`` (comma-separated, case-insensitive).
 * SoC / grid frequency toggles use separate params: ``damSoc``, ``damHz`` (alias ``damFrequency`` on read).
 */
function parseDamOverlayCurrencyParam(raw) {
  const s = String(raw ?? '').trim();
  if (!s) return { es: false, pl: false, uaEntsoe: false };
  const tokens = s.split(/[,+]/).map(x => x.trim().toLowerCase()).filter(Boolean);
  const set = new Set(tokens);
  return {
    es: set.has('es'),
    pl: set.has('pl'),
    uaEntsoe: set.has('ua_entso') || set.has('ua_entsoe') || set.has('uaents'),
  };
}

function buildDamCurrencyQueryParam(overlay) {
  const parts = [];
  if (overlay.uaEntsoe) parts.push('ua_entso');
  if (overlay.es) parts.push('es');
  if (overlay.pl) parts.push('pl');
  return parts.join(',');
}

/** SoC line on DAM chart: default visible; ``damSoc=0`` hides. */
function parseDamSocVisibleFromSearchParams(searchParams) {
  const raw = searchParams.get('damSoc');
  if (raw == null || raw === '') return true;
  const s = String(raw).trim().toLowerCase();
  if (s === '0' || s === 'false' || s === 'off' || s === 'no') return false;
  return true;
}

/** Grid frequency line: default hidden; ``damHz=1`` or ``damFrequency=1`` shows. */
function parseDamHzVisibleFromSearchParams(searchParams) {
  const raw = searchParams.get('damHz') ?? searchParams.get('damFrequency');
  if (raw == null || raw === '') return false;
  const s = String(raw).trim().toLowerCase();
  if (s === '1' || s === 'true' || s === 'on' || s === 'yes') return true;
  return false;
}

function brusselsCalendarIso() {
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Europe/Brussels',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function maxTradeDayBrusselsIso() {
  return addCalendarDays(brusselsCalendarIso(), 1);
}

function clampTradeDayIsoForMarket(iso, market) {
  const cap = market === 'entsoe' ? maxTradeDayBrusselsIso() : maxTradeDayKyivIso();
  return iso > cap ? cap : iso;
}

/** Calendar “today” for DAM trade-day semantics (Kyiv for OREE, Brussels for ENTSO-E). */
function tradeCalendarTodayIso(market) {
  return market === 'entsoe' ? brusselsCalendarIso() : kyivCalendarIso();
}

/** X-axis `hour` bucket → compact tooltip clock (hour start of the slot). */
function formatDamBarTooltipClockHour(hour) {
  const h = Number(hour);
  if (!Number.isFinite(h)) return String(hour ?? '');
  const clamped = Math.min(Math.max(Math.round(h), 0), 24);
  return `${String(clamped).padStart(2, '0')}:00`;
}

function getHourlyDamPerKwhFromPayload(p) {
  if (!p?.ok) return null;
  if (Array.isArray(p.hourlyPriceDamEurPerKwh) && p.hourlyPriceDamEurPerKwh.length) {
    return p.hourlyPriceDamEurPerKwh;
  }
  if (Array.isArray(p.hourlyPriceDamUahPerKwh) && p.hourlyPriceDamUahPerKwh.length) {
    return p.hourlyPriceDamUahPerKwh;
  }
  return null;
}

/** DAM price in UAH/kWh for billing; primary ENTSO-E series is EUR/kWh until scaled by NBU rate. */
function hourlyDamPriceUahPerKwhFromRow(row, damMarket, eurUahRate) {
  if (row.damPriceKwh == null || !Number.isFinite(row.damPriceKwh)) return null;
  if (damMarket === 'oree') return row.damPriceKwh;
  if (eurUahRate != null && eurUahRate > 0) return row.damPriceKwh * eurUahRate;
  return null;
}

/**
 * Per calendar hour h (one row): import kWh from grid (gridKw > 0) and export kWh (gridKw < 0).
 * Same rule as landing ``arbitrageRevenueUah`` SQL: only hours with a DAM price contribute.
 *
 *   hour_net_UAH = +export_kWh × DAM_UAH/kWh − import_kWh × DAM_UAH/kWh
 *
 * Day arbitrage = Σ hour_net. Import/export lines still use volume-weighted averages from the same sums.
 */
function computeDamWeightedGridMoneyUah(rows, damMarket, eurUahRate) {
  let importKwh = 0;
  let exportKwh = 0;
  let importUah = 0;
  let exportUah = 0;
  let netArbitrageUah = 0;
  let anyHourWithDamAndGrid = false;
  for (const r of rows) {
    const g = r.gridKw;
    if (g == null || !Number.isFinite(g)) continue;
    const pUah = hourlyDamPriceUahPerKwhFromRow(r, damMarket, eurUahRate);
    if (pUah == null) continue;
    const impKwh = g > 0 ? g : 0;
    const expKwh = g < 0 ? -g : 0;
    if (impKwh <= 0 && expKwh <= 0) continue;
    anyHourWithDamAndGrid = true;
    importKwh += impKwh;
    exportKwh += expKwh;
    importUah += impKwh * pUah;
    exportUah += expKwh * pUah;
    netArbitrageUah += expKwh * pUah - impKwh * pUah;
  }
  return {
    importKwhWeighted: importKwh,
    exportKwhWeighted: exportKwh,
    importCostUah: importKwh > 0 ? importUah : null,
    exportValueUah: exportKwh > 0 ? exportUah : null,
    importAvgUahPerKwh: importKwh > 0 ? importUah / importKwh : null,
    exportAvgUahPerKwh: exportKwh > 0 ? exportUah / exportKwh : null,
    netArbitrageUah: anyHourWithDamAndGrid ? netArbitrageUah : null,
  };
}

function readDamChartParamsFromUrl() {
  const marketDefault = 'oree';
  const zoneDefault = 'ES';
  try {
    const u = new URLSearchParams(window.location.search);
    const m = u.get('market');
    const market = m === 'oree' || m === 'entsoe' ? m : marketDefault;
    const z = (u.get('zone') || zoneDefault).toUpperCase();
    const zone = ENTSOE_ZONE_OPTIONS.some(o => o.value === z) ? z : zoneDefault;
    const todayIso = tradeCalendarTodayIso(market);
    const dq = u.get('date');
    let date = dq && /^\d{4}-\d{2}-\d{2}$/.test(dq) ? dq : todayIso;
    // Stale bookmarks: never open a calendar day before “today” for this market.
    if (date < todayIso) date = todayIso;
    date = clampTradeDayIsoForMarket(date, market);
    const cur = u.get('currency') ?? u.get('damOverlay') ?? '';
    const priceOverlay = parseDamOverlayCurrencyParam(cur);
    const soc = parseDamSocVisibleFromSearchParams(u);
    const hz = parseDamHzVisibleFromSearchParams(u);
    const overlay = { ...priceOverlay, soc, hz };
    return { date, market, zone, overlay };
  } catch {
    return {
      date: clampTradeDayIsoForMarket(tradeCalendarTodayIso(marketDefault), marketDefault),
      market: marketDefault,
      zone: zoneDefault,
      overlay: { es: false, pl: false, uaEntsoe: false, soc: true, hz: false },
    };
  }
}

function getInitialDamChartState() {
  return readDamChartParamsFromUrl();
}

/**
 * Sync DAM date, market, ENTSO-E zone, overlay ``currency`` list, and Deye extras ``damSoc`` / ``damHz``
 * into the page URL (embedded + fullpage).
 */
function replaceUrlDamChartState(isoDate, market, zone, overlay) {
  try {
    const u = new URL(window.location.href);
    const todayIso = tradeCalendarTodayIso(market);
    if (isoDate === todayIso) u.searchParams.delete('date');
    else u.searchParams.set('date', isoDate);
    u.searchParams.set('market', market);
    u.searchParams.set('zone', zone);
    const c = buildDamCurrencyQueryParam(overlay);
    if (c) u.searchParams.set('currency', c);
    else u.searchParams.delete('currency');
    u.searchParams.delete('damOverlay');
    if (overlay.soc === false) u.searchParams.set('damSoc', '0');
    else u.searchParams.delete('damSoc');
    if (overlay.hz === true) {
      u.searchParams.set('damHz', '1');
      u.searchParams.delete('damFrequency');
    } else {
      u.searchParams.delete('damHz');
      u.searchParams.delete('damFrequency');
    }
    window.history.replaceState({}, '', u);
  } catch {
    /* ignore */
  }
}

const DAM_INDEX_BAR_COLORS = ['#22c55e', '#38bdf8', '#f59e0b', '#a78bfa', '#f472b6'];

function parseOreeDecimalLoose(s) {
  if (s == null || s === '') return null;
  const n = Number(String(s).replace(',', '.').trim());
  return Number.isFinite(n) ? n : null;
}

/** Pick first zone block (prefer IND) from OREE /damindexes JSON. */
function pickDamIndexesZone(raw) {
  if (!raw || typeof raw !== 'object') return null;
  if (raw.IND && typeof raw.IND === 'object') return raw.IND;
  const withDay = Object.keys(raw).find(k => raw[k]?.trade_day != null);
  return withDay ? raw[withDay] : null;
}

function buildDamIndexRows(oreeZoneBlock, t) {
  if (!oreeZoneBlock || typeof oreeZoneBlock !== 'object') return { tradeDay: '', rows: [] };
  const tradeDay = oreeZoneBlock.trade_day != null ? String(oreeZoneBlock.trade_day) : '';
  const rows = [];
  for (let i = 0; i < DAM_INDEX_KEYS.length; i += 1) {
    const k = DAM_INDEX_KEYS[i];
    const cell = oreeZoneBlock[k];
    const priceMwh = cell && typeof cell === 'object' ? parseOreeDecimalLoose(cell.price) : null;
    const percent = cell && typeof cell === 'object' ? parseOreeDecimalLoose(cell.percent) : null;
    if (priceMwh == null) continue;
    const priceUahKwh = priceMwh / 1000;
    rows.push({
      key: k,
      label: t(`damIndex${k}`),
      priceUahKwh,
      percent,
      color: DAM_INDEX_BAR_COLORS[i] ?? '#e879f9',
    });
  }
  return { tradeDay, rows };
}

/** Arithmetic mean of published OREE DAM index prices (UAH/kWh) for keys that have a value. */
function avgDamIndexUahKwhFromIndexesPayload(perm) {
  if (!perm?.ok || !perm.data) return null;
  const zone = pickDamIndexesZone(perm.data);
  if (!zone) return null;
  const nums = [];
  for (const k of DAM_INDEX_KEYS) {
    const cell = zone[k];
    const priceMwh = cell && typeof cell === 'object' ? parseOreeDecimalLoose(cell.price) : null;
    if (priceMwh == null) continue;
    nums.push(priceMwh / 1000);
  }
  if (!nums.length) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function kyivCalendarIso() {
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Europe/Kyiv',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function addCalendarDays(iso, deltaDays) {
  const [y, m, d] = iso.split('-').map(Number);
  const u = new Date(Date.UTC(y, m - 1, d + deltaDays));
  const yy = u.getUTCFullYear();
  const mm = String(u.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(u.getUTCDate()).padStart(2, '0');
  return `${yy}-${mm}-${dd}`;
}

/** Display trade day as DD.MM.YYYY from ISO yyyy-mm-dd. */
function formatTradeDayDdMmYyyy(iso) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso || '—';
  const [y, m, d] = iso.split('-');
  return `${d}.${m}.${y}`;
}

/** Last selectable DAM trade day: tomorrow in Europe/Kyiv (aligned with lazy OREE rules). */
function maxTradeDayKyivIso() {
  return addCalendarDays(kyivCalendarIso(), 1);
}

function readInverterFromSearchOnce() {
  try {
    const v = new URLSearchParams(window.location.search).get('inverter');
    return v && /^\d{6,32}$/.test(v.trim()) ? v.trim() : '';
  } catch {
    return '';
  }
}

/** Rounded-up “nice” positive bound for symmetric Y domains (avoids 7.142857-style auto ticks). */
function niceSymmetricCap(rawMax) {
  if (!Number.isFinite(rawMax) || rawMax <= 0) return 0.25;
  const x = Math.abs(rawMax);
  const pow10 = 10 ** Math.floor(Math.log10(x));
  const n = x / pow10;
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return nice * pow10;
}

/** Left Y-axis band width — same on DAM line chart and grid bar chart so hours align vertically. */
/** Wide enough for Y-axis labels (e.g. Gen/Cons, kWh) across synced DAM charts. */
const DAM_LEFT_Y_AXIS_WIDTH = 72;

/** Right SoC / placeholder axis width — bottom chart uses a hidden right axis with the same width so plot areas match. */
const DAM_RIGHT_Y_AXIS_WIDTH = 48;

/** Right grid-frequency (Hz) axis — extra width for 2-decimal locale + unit (e.g. 49,99 Гц). */
const DAM_HZ_Y_AXIS_WIDTH = 72;

/** Second left Y-axis width for ENTSO-E EUR overlay (Ukraine OREE mode). */
const DAM_ENTSOE_OVERLAY_AXIS_WIDTH = 52;

/** Hour index on X-axis (data uses 1–24): show even ticks only. */
const DAM_HOUR_X_TICKS = Object.freeze([2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24]);

/** Half-hour gutters on the X domain so hour-1 bars do not sit on the Y-axis (keep in sync across DAM charts). */
const DAM_X_AXIS_DOMAIN = Object.freeze([0.5, 24.5]);

/** Treat SoC as “full” for lost-PV heuristics (hourly % may be rounded). */
function isSocFullPercent(socPercent) {
  return socPercent != null && Number.isFinite(Number(socPercent)) && Number(socPercent) > 94;
}

function medianPositive(nums) {
  const s = nums.filter(x => Number.isFinite(x) && x > 0).sort((a, b) => a - b);
  if (!s.length) return null;
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** Fallback shape when /api/deye/clear-sky-hourly-shape is unavailable (no coords / offline). */
function syntheticMiddayClearSkyWeights24() {
  const w = new Array(24).fill(0);
  for (let i = 0; i < 24; i++) {
    const dist = Math.abs(i + 0.5 - 12.5);
    if (dist < 8) w[i] = Math.max(0, 1 - (dist / 8) ** 2);
  }
  return w;
}

/**
 * Lost PV after the first ~100% SoC hour: compare clear-sky-shaped forecast vs measured hourly kWh.
 *
 * Scale is calibrated from pre-full hours as median(pv_kwh / weight). Forecast hours are those with
 * full SoC; lost_kWh = max(0, predicted − actual) per hour. Income uses the same DAM kWh price as
 * the primary chart series for that hour.
 */
function computeLostSolarForecast(rows, clearSkyWeights) {
  if (!Array.isArray(rows) || rows.length !== 24) return null;
  let i0 = -1;
  for (let i = 0; i < 24; i++) {
    if (isSocFullPercent(rows[i]?.socPercent)) {
      i0 = i;
      break;
    }
  }
  if (i0 < 0) return null;
  let fullHours = 0;
  for (const r of rows) {
    if (isSocFullPercent(r?.socPercent)) fullHours += 1;
  }
  if (fullHours < 1) return null;

  const weights =
    clearSkyWeights != null && clearSkyWeights.length === 24
      ? clearSkyWeights.map(x => (Number.isFinite(Number(x)) ? Math.max(0, Number(x)) : 0))
      : syntheticMiddayClearSkyWeights24();

  const ratios = [];
  for (let i = 0; i < i0; i++) {
    const pv = rows[i]?.pvKwh;
    const ww = weights[i];
    if (pv != null && Number.isFinite(Number(pv)) && Number(pv) > 0 && ww > 1e-8) {
      ratios.push(Number(pv) / ww);
    }
  }
  let scale = medianPositive(ratios);
  if (scale == null) {
    const pv0 = rows[i0]?.pvKwh;
    const ww0 = weights[i0];
    if (pv0 != null && Number.isFinite(Number(pv0)) && Number(pv0) > 0 && ww0 > 1e-8) {
      scale = Number(pv0) / ww0;
    }
  }
  if (scale == null || !Number.isFinite(scale) || scale <= 0) return null;

  let totalKwh = 0;
  let totalMoney = 0;
  const hourMoney = new Array(24).fill(null);
  for (let i = i0; i < 24; i++) {
    if (!isSocFullPercent(rows[i]?.socPercent)) continue;
    const predicted = scale * weights[i];
    const pv = rows[i]?.pvKwh;
    const actual = pv != null && Number.isFinite(Number(pv)) && Number(pv) > 0 ? Number(pv) : 0;
    const diff = predicted - actual;
    if (diff > 0) {
      totalKwh += diff;
      const dam = rows[i]?.damPriceKwh;
      if (dam != null && Number.isFinite(Number(dam))) {
        const m = diff * Number(dam);
        totalMoney += m;
        hourMoney[i] = m;
      }
    }
  }
  return { totalKwh, totalMoney, hourMoney };
}

function formatDamLineTooltipItem(
  entry,
  t,
  fmtDamTooltip,
  fmtEur,
  fmt1,
  fmtHz,
  damUnitLabel,
  damLineSeriesName,
  damEntsoeOverlaySeriesNames,
  damMarket,
  entsoeZone,
  damEntsoeOverlaySeriesNameEs,
  damEntsoeOverlaySeriesNamePl,
  damEntsoeOverlaySeriesNameUaEntsoe,
  entsoeOverlayUahMode
) {
  const value = entry?.value;
  const name = entry?.name;
  const row = entry?.payload;
  if (value == null || value === '') return { display: '—', label: name };
  const entsoeTipLabel = () => t('damTooltipDamEntsoeLabel', { zone: entsoeZone });
  if (damEntsoeOverlaySeriesNames?.length && damEntsoeOverlaySeriesNames.includes(name)) {
    const n = Number(value);
    if (!Number.isFinite(n)) return { display: '—', label: t('damTooltipDamEntsoeLabel', { zone: name }) };
    if (entsoeOverlayUahMode && row) {
      let eurRaw = null;
      if (name === damEntsoeOverlaySeriesNameEs) eurRaw = row.damEntsoeEsEurKwh;
      else if (name === damEntsoeOverlaySeriesNamePl) eurRaw = row.damEntsoePlEurKwh;
      else if (name === damEntsoeOverlaySeriesNameUaEntsoe) eurRaw = row.damEntsoeUaEntsoeEurKwh;
      const eur = eurRaw != null && Number.isFinite(Number(eurRaw)) ? Number(eurRaw) : null;
      if (eur != null) {
        const isEs = name === damEntsoeOverlaySeriesNameEs;
        const isPl = name === damEntsoeOverlaySeriesNamePl;
        if (isEs || isPl) {
          return {
            display: `${fmtDamTooltip.format(n)} ${t('damTooltipDamUnit')}`,
            label: t('damTooltipDamEntsoeLabel', { zone: isPl ? 'PL' : 'ES' }),
          };
        }
        return {
          display: `${fmtEur.format(eur)} ${t('damTooltipDamUnitEur')} (${fmtDamTooltip.format(n)} ${t('damTooltipDamUnit')})`,
          label:
            name === damEntsoeOverlaySeriesNameUaEntsoe
              ? t('damSeriesDamUaEntsoe')
              : t('damTooltipDamEntsoeLabel', {
                  zone: name === damEntsoeOverlaySeriesNamePl ? 'PL' : 'ES',
                }),
        };
      }
    }
    return {
      display: `${fmtEur.format(n)} ${t('damTooltipDamUnitEur')}`,
      label: t('damTooltipDamEntsoeLabel', { zone: name }),
    };
  }
  if (name === damLineSeriesName) {
    const n = Number(value);
    const primaryLabel = damMarket === 'entsoe' ? entsoeTipLabel() : t('damTooltipDamUaLabel');
    if (!Number.isFinite(n)) return { display: '—', label: primaryLabel };
    const fmtPrimary = damMarket === 'entsoe' ? fmtEur : fmtDamTooltip;
    return {
      display: `${fmtPrimary.format(n)} ${damUnitLabel}`,
      label: primaryLabel,
    };
  }
  const socLabel = t('damSeriesSoc');
  if (name === socLabel) return { display: `${fmt1.format(value)} %`, label: socLabel };
  const hzLabel = t('damSeriesGridFreq');
  if (name === hzLabel) return { display: `${fmtHz.format(value)} Hz`, label: hzLabel };
  return { display: `${fmt1.format(value)}`, label: name };
}

function DamLineChartTooltip({
  active,
  payload,
  label,
  t,
  fmtDamTooltip,
  fmt1,
  fmtHz,
  fmtUah,
  fmtEur,
  damUnitLabel,
  lostSolarHourMoney,
  lostSolarCurrency,
  damLineSeriesName,
  damEntsoeOverlaySeriesNames,
  damMarket,
  entsoeZone,
  damEntsoeOverlaySeriesNameEs,
  damEntsoeOverlaySeriesNamePl,
  damEntsoeOverlaySeriesNameUaEntsoe,
  entsoeOverlayUahMode,
  isDark,
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  const tooltipContentStyle = isDark ? {
    background: 'rgba(24, 8, 32, 0.94)',
    border: '1px solid rgba(252, 1, 155, 0.35)',
    borderRadius: 10,
    color: '#fff',
    padding: '8px 12px',
  } : {
    background: 'rgba(255, 255, 255, 0.97)',
    border: '1px solid rgba(193, 0, 185, 0.28)',
    borderRadius: 10,
    color: '#1a0a1e',
    padding: '8px 12px',
  };
  const labelStyle = isDark ? { color: 'rgba(255, 248, 252, 0.95)' } : { color: 'rgba(20, 5, 30, 0.92)' };
  const itemStyle = isDark ? { color: 'rgba(255, 248, 252, 0.95)' } : { color: 'rgba(20, 5, 30, 0.88)' };
  const hi = label != null && lostSolarHourMoney?.length === 24 ? Number(label) - 1 : -1;
  const lostSolarIncomeAtHour = hi >= 0 && hi < 24 ? lostSolarHourMoney[hi] : null;
  const showLostSolar =
    lostSolarIncomeAtHour != null &&
    Number.isFinite(lostSolarIncomeAtHour) &&
    lostSolarIncomeAtHour > 0 &&
    isSocFullPercent(row?.socPercent);

  return (
    <div className="recharts-default-tooltip" style={tooltipContentStyle}>
      <p className="recharts-tooltip-label" style={labelStyle}>
        {formatDamBarTooltipClockHour(label)}
      </p>
      <ul className="recharts-tooltip-item-list" style={{ margin: '4px 0 0', padding: 0, listStyle: 'none' }}>
        {payload.map((entry, i) => {
          const { display, label: itemLabel } = formatDamLineTooltipItem(
            entry,
            t,
            fmtDamTooltip,
            fmtEur,
            fmt1,
            fmtHz,
            damUnitLabel,
            damLineSeriesName,
            damEntsoeOverlaySeriesNames,
            damMarket,
            entsoeZone,
            damEntsoeOverlaySeriesNameEs,
            damEntsoeOverlaySeriesNamePl,
            damEntsoeOverlaySeriesNameUaEntsoe,
            entsoeOverlayUahMode
          );
          return (
            <li key={i} className="recharts-tooltip-item" style={{ ...itemStyle, color: entry.color }}>
              <span className="recharts-tooltip-item-name">{itemLabel}</span>
              <span className="recharts-tooltip-item-separator">: </span>
              <span className="recharts-tooltip-item-value">{display}</span>
            </li>
          );
        })}
      </ul>
      {showLostSolar ? (
        <p style={{ ...itemStyle, marginTop: 8, marginBottom: 0, fontSize: 12 }}>
          {t('damTooltipLostSolarIncome')}:{' '}
          {lostSolarCurrency === 'eur'
            ? `${fmtEur.format(lostSolarIncomeAtHour)} ${t('roiValueEurUnit')}`
            : `${fmtUah.format(lostSolarIncomeAtHour)} ${t('roiValueUahUnit')}`}
        </p>
      ) : null}
    </div>
  );
}

function fiveSymmetricTicks(lo, hi) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo >= hi) return [0];
  const step = (hi - lo) / 4;
  return [lo, lo + step, lo + 2 * step, lo + 3 * step, hi];
}

/** Kyiv local hour 0–23 for `date`, using wall clock in Europe/Kyiv. */
function kyivHourIndexNowForDate(tradeDayIso) {
  try {
    const todayKyiv = kyivCalendarIso();
    if (tradeDayIso !== todayKyiv) return null;
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Kyiv',
      hour: 'numeric',
      hour12: false,
    }).formatToParts(new Date());
    const hp = parts.find(p => p.type === 'hour');
    if (!hp) return null;
    const h = parseInt(hp.value, 10);
    return Number.isFinite(h) ? h % 24 : null;
  } catch {
    return null;
  }
}

/**
 * @param {'embedded' | 'fullpage'} variant — fullpage: URL ?date= sync + top nav; embedded: bottom of Power flow only.
 * @param {string} [inverterSn] — Deye serial; when set, overlays mean SoC % per hour (from DB) on the chart.
 * @param {string} [huaweiStationCode] — FusionSolar plant code; grid/PV/load bars from DB (`/api/huawei/station-hourly`). Mutually exclusive with Deye bar data in practice.
 */
export default function DamChartPanel({
  t,
  getBcp47Locale,
  variant = 'embedded',
  chartHeight,
  locale,
  SUPPORTED,
  LOCALE_NAMES,
  onLangSelectChange,
  inverterSn: inverterSnProp,
  huaweiStationCode: huaweiStationCodeProp,
}) {
  const { theme, cycleTheme, isDark } = useTheme();

  // Chart color palette — adapts to resolved light/dark theme.
  const CHART = useMemo(() => isDark ? {
    axisText: 'rgba(255,248,252,0.75)',
    axisTextMuted: 'rgba(255,248,252,0.72)',
    axisTextAmber: 'rgba(251, 191, 36, 0.92)',
    axisTextBlue: 'rgba(147, 197, 253, 0.9)',
    axisTextHz: 'rgba(250, 204, 21, 0.92)',
    gridStroke: 'rgba(252, 1, 155, 0.12)',
    gridStrokeFaint: 'rgba(252, 1, 155, 0.08)',
    gridStrokeIndexes: 'rgba(252, 1, 155, 0.10)',
    refLineStroke: 'rgba(255,248,252,0.35)',
    circleBorder: 'rgba(255,255,255,0.45)',
    tooltipBg: 'rgba(24, 8, 32, 0.94)',
    tooltipBorder: '1px solid rgba(252, 1, 155, 0.35)',
    tooltipColor: '#fff',
    tooltipLabelColor: 'rgba(255, 248, 252, 0.95)',
    tooltipCursor: 'rgba(252, 1, 155, 0.06)',
    hzAxisLine: 'rgba(250, 204, 21, 0.35)',
    hzAxisLabel: 'rgba(250, 204, 21, 0.75)',
  } : {
    axisText: 'rgba(20,5,30,0.68)',
    axisTextMuted: 'rgba(20,5,30,0.58)',
    axisTextAmber: 'rgba(146, 70, 0, 0.88)',
    axisTextBlue: 'rgba(30, 90, 200, 0.88)',
    axisTextHz: 'rgba(133, 95, 0, 0.88)',
    gridStroke: 'rgba(193, 0, 185, 0.15)',
    gridStrokeFaint: 'rgba(193, 0, 185, 0.10)',
    gridStrokeIndexes: 'rgba(193, 0, 185, 0.12)',
    refLineStroke: 'rgba(20,5,30,0.22)',
    circleBorder: 'rgba(0,0,0,0.20)',
    tooltipBg: 'rgba(255, 255, 255, 0.97)',
    tooltipBorder: '1px solid rgba(193, 0, 185, 0.28)',
    tooltipColor: '#1a0a1e',
    tooltipLabelColor: 'rgba(20, 5, 30, 0.92)',
    tooltipCursor: 'rgba(193, 0, 185, 0.06)',
    hzAxisLine: 'rgba(133, 95, 0, 0.35)',
    hzAxisLabel: 'rgba(133, 95, 0, 0.70)',
  }, [isDark]);

  const barTooltipStyle = useMemo(() => ({
    background: CHART.tooltipBg,
    border: CHART.tooltipBorder,
    borderRadius: 10,
    color: CHART.tooltipColor,
    padding: '8px 12px',
  }), [CHART]);

  const [damUrlBootstrap] = useState(() => getInitialDamChartState());
  const [tradeDay, setTradeDay] = useState(damUrlBootstrap.date);
  const [damMarket, setDamMarket] = useState(damUrlBootstrap.market);
  const [entsoeZone, setEntsoeZone] = useState(damUrlBootstrap.zone);
  const [payload, setPayload] = useState(null);
  /** Per-zone ENTSO-E chart-day payloads when primary market is Ukraine (OREE); keys ES, PL. */
  const [entsoeOverlayByZone, setEntsoeOverlayByZone] = useState({});
  /** Line visibility toggled from the legend (UA/ENTSO-E primary, ES/PL overlay, SoC, Hz). */
  const [damSeriesVisible, setDamSeriesVisible] = useState({
    primary: true,
    es: damUrlBootstrap.overlay.es,
    pl: damUrlBootstrap.overlay.pl,
    uaEntsoe: damUrlBootstrap.overlay.uaEntsoe,
    soc: damUrlBootstrap.overlay.soc !== false,
    hz: damUrlBootstrap.overlay.hz === true,
  });
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);
  const [socPayload, setSocPayload] = useState(null);
  const [socError, setSocError] = useState('');
  const [socLoading, setSocLoading] = useState(false);
  /** Live grid power (W, Deye signed); used when hourly DB aggregates are missing. */
  const [liveGridPowerW, setLiveGridPowerW] = useState(null);
  const [liveLoadPowerW, setLiveLoadPowerW] = useState(null);
  const [livePvPowerW, setLivePvPowerW] = useState(null);
  const [liveBatteryPowerW, setLiveBatteryPowerW] = useState(null);
  const [indexesPayload, setIndexesPayload] = useState(null);
  const [indexesLoading, setIndexesLoading] = useState(true);
  const [indexesError, setIndexesError] = useState('');
  const [indexesYesterdayPayload, setIndexesYesterdayPayload] = useState(null);
  const [indexesYesterdayLoading, setIndexesYesterdayLoading] = useState(false);
  const [urlInverterOnce] = useState(readInverterFromSearchOnce);
  /** NBU UAH per 1 EUR — scales ENTSO-E EUR/kWh onto the same axis as Ukraine DAM (UAH/kWh). */
  const [eurUahRate, setEurUahRate] = useState(null);
  const [eurUahRateLabel, setEurUahRateLabel] = useState(null);
  const [huaweiHourly, setHuaweiHourly] = useState(null);
  const [huaweiSnapshotBusy, setHuaweiSnapshotBusy] = useState(false);
  /** 24 clear-sky weights from server (plant GPS); improves lost-solar kWh after SoC ~100%. */
  const [clearSkyWeights, setClearSkyWeights] = useState(null);
  const tradeDayLineInputRef = useRef(null);
  const tradeDayGridInputRef = useRef(null);
  const tradeDayPvInputRef = useRef(null);

  const effectiveInverterSn = (
    (inverterSnProp && String(inverterSnProp).trim()) ||
    (variant === 'fullpage' ? urlInverterOnce : '')
  ).trim();
  const effectiveHuaweiStation = (huaweiStationCodeProp && String(huaweiStationCodeProp).trim()) || '';
  const showEnergyBars = Boolean(effectiveInverterSn || effectiveHuaweiStation);
  const showDeyeExtras = Boolean(effectiveInverterSn && !effectiveHuaweiStation);

  const damChartMobile = useDamChartMobileLayout();

  const h = chartHeight ?? (variant === 'embedded' ? 300 : 420);
  const gridBarH = 148;

  const bcp47 = getBcp47Locale();
  const fmt1 = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 1,
      }),
    [bcp47]
  );

  const fmtDamTooltip = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 3,
        maximumFractionDigits: 3,
      }),
    [bcp47]
  );

  const fmtGridKwTick = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }),
    [bcp47]
  );

  const fmtKwhTick = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }),
    [bcp47]
  );

  const fmtHz = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }),
    [bcp47]
  );

  const fmtPct = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        maximumFractionDigits: 1,
        minimumFractionDigits: 1,
        signDisplay: 'exceptZero',
      }),
    [bcp47]
  );

  const fmtUah = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 3,
        maximumFractionDigits: 3,
      }),
    [bcp47]
  );

  const fmtEur = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }),
    [bcp47]
  );

  const damUnitLabel = damMarket === 'entsoe' ? t('damTooltipDamUnitEur') : t('damTooltipDamUnit');

  const damLineSeriesName = useMemo(
    () => (damMarket === 'oree' ? t('damSeriesDamUa') : t('damSeriesDamEntsoe', { zone: entsoeZone })),
    [damMarket, entsoeZone, t]
  );

  const damEntsoeOverlaySeriesNameEs = useMemo(() => t('damSeriesDamEntsoe', { zone: 'ES' }), [t]);
  const damEntsoeOverlaySeriesNamePl = useMemo(() => t('damSeriesDamEntsoe', { zone: 'PL' }), [t]);
  const damEntsoeOverlaySeriesNameUaEntsoe = useMemo(() => t('damSeriesDamUaEntsoe'), [t]);

  const showEntsoeOverlayAxis = useMemo(() => {
    if (damMarket !== 'oree') return false;
    return ENTSOE_OREE_OVERLAY_ZONES.some(z => {
      const p = entsoeOverlayByZone[z];
      return p && p.entsoeConfigured !== false;
    });
  }, [damMarket, entsoeOverlayByZone]);

  const showEntsoeEurAxis = useMemo(
    () =>
      showEntsoeOverlayAxis &&
      (damSeriesVisible.es || damSeriesVisible.pl || damSeriesVisible.uaEntsoe) &&
      !(eurUahRate > 0),
    [showEntsoeOverlayAxis, damSeriesVisible.es, damSeriesVisible.pl, damSeriesVisible.uaEntsoe, eurUahRate]
  );

  useEffect(() => {
    let cancelled = false;
    setEurUahRate(null);
    setEurUahRateLabel(null);
    (async () => {
      try {
        const r = await fetch(apiUrl(`/api/fx/eur-uah?date=${encodeURIComponent(tradeDay)}`), {
          cache: 'no-store',
        });
        const d = await r.json();
        if (cancelled) return;
        if (d?.ok && d.rate != null && Number.isFinite(Number(d.rate))) {
          setEurUahRate(Number(d.rate));
          setEurUahRateLabel(d.exchangedate || d.nbu_query_date || tradeDay);
        }
      } catch {
        if (!cancelled) {
          setEurUahRate(null);
          setEurUahRateLabel(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tradeDay]);

  useEffect(() => {
    if (damMarket !== 'oree') {
      setDamSeriesVisible(v => ({ ...v, es: false, pl: false, uaEntsoe: false }));
    }
  }, [damMarket]);

  /** DAM index chart values are UAH/kWh (API stores UAH/MWh). */
  const fmtIndexKwh = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 3,
        maximumFractionDigits: 3,
      }),
    [bcp47]
  );

  const maxTradeDay = damMarket === 'entsoe' ? maxTradeDayBrusselsIso() : maxTradeDayKyivIso();
  /** Calendar “today” for the active market zone — used only to disable the redundant Today jump. */
  const calendarTodayIso = tradeCalendarTodayIso(damMarket);

  useEffect(() => {
    if (tradeDay > maxTradeDay) setTradeDay(maxTradeDay);
  }, [tradeDay, maxTradeDay]);

  useEffect(() => {
    replaceUrlDamChartState(tradeDay, damMarket, entsoeZone, {
      es: damSeriesVisible.es,
      pl: damSeriesVisible.pl,
      uaEntsoe: damSeriesVisible.uaEntsoe,
      soc: damSeriesVisible.soc,
      hz: damSeriesVisible.hz,
    });
  }, [
    tradeDay,
    damMarket,
    entsoeZone,
    damSeriesVisible.es,
    damSeriesVisible.pl,
    damSeriesVisible.uaEntsoe,
    damSeriesVisible.soc,
    damSeriesVisible.hz,
  ]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    setEntsoeOverlayByZone({});
    try {
      const q = new URLSearchParams({ date: tradeDay });
      if (damMarket === 'entsoe') {
        q.set('zone', entsoeZone);
        const r = await fetch(apiUrl(`/api/dam/entsoe/chart-day?${q}`), { cache: 'no-store' });
        if (!r.ok) throw new Error((await r.text()) || r.statusText);
        const data = await r.json();
        setPayload(data);
        return;
      }
      const qOree = new URLSearchParams({ date: tradeDay });
      const qBatch = new URLSearchParams({
        date: tradeDay,
        zones: ENTSOE_OREE_OVERLAY_ZONES.join(','),
      });
      const [rOree, rBatch] = await Promise.all([
        fetch(apiUrl(`/api/dam/chart-day?${qOree}`), { cache: 'no-store' }),
        fetch(apiUrl(`/api/dam/entsoe/chart-day-zones?${qBatch}`), { cache: 'no-store' }),
      ]);
      if (!rOree.ok) throw new Error((await rOree.text()) || rOree.statusText);
      const oreeData = await rOree.json();
      setPayload(oreeData);
      let byZone = {};
      if (rBatch.ok) {
        const batch = await rBatch.json();
        if (batch?.ok && batch.zones) {
          for (const z of ENTSOE_OREE_OVERLAY_ZONES) {
            const zd = batch.zones[z];
            if (zd) {
              byZone[z] = {
                ok: true,
                entsoeConfigured: batch.entsoeConfigured,
                hourlyPriceDamEurPerKwh: zd.hourlyPriceDamEurPerKwh,
              };
            }
          }
        }
      }
      if (Object.keys(byZone).length === 0) {
        const qEnt = z => new URLSearchParams({ date: tradeDay, zone: z });
        const rEnts = await Promise.all(
          ENTSOE_OREE_OVERLAY_ZONES.map(z =>
            fetch(apiUrl(`/api/dam/entsoe/chart-day?${qEnt(z)}`), { cache: 'no-store' })
          )
        );
        for (let i = 0; i < ENTSOE_OREE_OVERLAY_ZONES.length; i++) {
          const z = ENTSOE_OREE_OVERLAY_ZONES[i];
          if (rEnts[i].ok) {
            byZone[z] = await rEnts[i].json();
          }
        }
      }
      setEntsoeOverlayByZone(byZone);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
      setPayload(null);
      setEntsoeOverlayByZone({});
    } finally {
      setLoading(false);
    }
  }, [tradeDay, damMarket, entsoeZone]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (damMarket !== 'oree') {
      setIndexesPayload(null);
      setIndexesLoading(false);
      setIndexesError('');
      return undefined;
    }
    let cancelled = false;
    (async () => {
      setIndexesLoading(true);
      setIndexesError('');
      try {
        const q = new URLSearchParams({ date: tradeDay });
        const r = await fetch(apiUrl(`/api/dam/damindexes?${q}`), { cache: 'no-store' });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        setIndexesPayload(data);
        if (!r.ok || !data.ok) {
          if (data.configured === false) setIndexesError('');
          else {
            const detail = data.detail || r.statusText || 'damindexes';
            const noRows =
              typeof detail === 'string' && /no dam index data for this date/i.test(detail);
            setIndexesError(noRows ? '' : detail);
          }
        }
      } catch (e) {
        if (!cancelled) {
          setIndexesPayload(null);
          setIndexesError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setIndexesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tradeDay, damMarket]);

  useEffect(() => {
    if (damMarket !== 'oree') {
      setIndexesYesterdayPayload(null);
      setIndexesYesterdayLoading(false);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      setIndexesYesterdayLoading(true);
      setIndexesYesterdayPayload(null);
      const prevDay = addCalendarDays(tradeDay, -1);
      try {
        const q = new URLSearchParams({ date: prevDay });
        const r = await fetch(apiUrl(`/api/dam/damindexes?${q}`), { cache: 'no-store' });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (r.ok && data.ok) setIndexesYesterdayPayload(data);
        else setIndexesYesterdayPayload(null);
      } catch {
        if (!cancelled) setIndexesYesterdayPayload(null);
      } finally {
        if (!cancelled) setIndexesYesterdayLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tradeDay, damMarket]);

  useEffect(() => {
    if (!effectiveInverterSn || effectiveHuaweiStation) {
      setSocPayload(null);
      setSocError('');
      setSocLoading(false);
      return undefined;
    }
    let cancelled = false;
    const loadSoc = async () => {
      setSocLoading(true);
      setSocError('');
      try {
        const q = new URLSearchParams({ deviceSn: effectiveInverterSn, date: tradeDay });
        const r = await fetch(apiUrl(`/api/deye/soc-history-day?${q}`), { cache: 'no-store' });
        if (!r.ok) throw new Error((await r.text()) || r.statusText);
        const data = await r.json();
        if (cancelled) return;
        setSocPayload(data);
      } catch (e) {
        if (!cancelled) setSocError(e instanceof Error ? e.message : String(e));
        if (!cancelled) setSocPayload(null);
      } finally {
        if (!cancelled) setSocLoading(false);
      }
    };
    loadSoc();
    return () => {
      cancelled = true;
    };
  }, [tradeDay, effectiveInverterSn, effectiveHuaweiStation]);

  useEffect(() => {
    if (!effectiveInverterSn || effectiveHuaweiStation) {
      setClearSkyWeights(null);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      try {
        const q = new URLSearchParams({ deviceSn: effectiveInverterSn, date: tradeDay });
        const r = await fetch(apiUrl(`/api/deye/clear-sky-hourly-shape?${q}`), { cache: 'no-store' });
        const j = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (j?.ok && Array.isArray(j.hourlyWeights) && j.hourlyWeights.length === 24) {
          setClearSkyWeights(j.hourlyWeights.map(x => (Number.isFinite(Number(x)) ? Number(x) : 0)));
        } else {
          setClearSkyWeights(null);
        }
      } catch {
        if (!cancelled) setClearSkyWeights(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tradeDay, effectiveInverterSn, effectiveHuaweiStation]);

  useEffect(() => {
    if (!effectiveInverterSn || effectiveHuaweiStation) {
      setLiveGridPowerW(null);
      setLiveLoadPowerW(null);
      setLivePvPowerW(null);
      setLiveBatteryPowerW(null);
      return undefined;
    }
    let cancelled = false;
    const loadLive = async () => {
      try {
        const r = await fetch(apiUrl(`/api/deye/ess-power?deviceSn=${encodeURIComponent(effectiveInverterSn)}`), {
          cache: 'no-store',
        });
        const d = await r.json();
        if (cancelled || !d?.ok || d?.configured === false) {
          if (!cancelled) {
            setLiveGridPowerW(null);
            setLiveLoadPowerW(null);
            setLivePvPowerW(null);
            setLiveBatteryPowerW(null);
          }
          return;
        }
        const g = d.gridPowerW;
        const l = d.loadPowerW;
        const pv = d.pvPowerW;
        const bat = d.batteryPowerW;
        if (!cancelled) {
          setLiveGridPowerW(g != null && Number.isFinite(Number(g)) ? Number(g) : null);
          setLiveLoadPowerW(l != null && Number.isFinite(Number(l)) ? Number(l) : null);
          setLivePvPowerW(pv != null && Number.isFinite(Number(pv)) ? Number(pv) : null);
          setLiveBatteryPowerW(bat != null && Number.isFinite(Number(bat)) ? Number(bat) : null);
        }
      } catch {
        if (!cancelled) {
          setLiveGridPowerW(null);
          setLiveLoadPowerW(null);
          setLivePvPowerW(null);
          setLiveBatteryPowerW(null);
        }
      }
    };
    loadLive();
    const id = setInterval(loadLive, 25_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [effectiveInverterSn, effectiveHuaweiStation]);

  useEffect(() => {
    if (!effectiveHuaweiStation) {
      setHuaweiHourly(null);
      return undefined;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const q = new URLSearchParams({ stationCodes: effectiveHuaweiStation, date: tradeDay });
        const r = await fetch(apiUrl(`/api/huawei/station-hourly?${q}`), { cache: 'no-store' });
        const j = await r.json().catch(() => ({}));
        if (!cancelled) setHuaweiHourly(j);
      } catch {
        if (!cancelled) setHuaweiHourly(null);
      }
    };
    void load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [effectiveHuaweiStation, tradeDay]);

  const runHuaweiPowerSnapshot = useCallback(async () => {
    if (!effectiveHuaweiStation) return;
    setHuaweiSnapshotBusy(true);
    try {
      const r = await fetch(apiUrl('/api/huawei/power-snapshot'), {
        method: 'POST',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      const j = await r.json().catch(() => ({}));
      if (j?.ok) {
        const q = new URLSearchParams({ stationCodes: effectiveHuaweiStation, date: tradeDay });
        const r2 = await fetch(apiUrl(`/api/huawei/station-hourly?${q}`), { cache: 'no-store' });
        const j2 = await r2.json().catch(() => ({}));
        setHuaweiHourly(j2);
      }
    } catch {
      /* keep previous hourly state */
    } finally {
      setHuaweiSnapshotBusy(false);
    }
  }, [effectiveHuaweiStation, tradeDay]);

  const rows = useMemo(() => {
    const damArr = getHourlyDamPerKwhFromPayload(payload);
    if (!payload?.ok || !Array.isArray(damArr)) return [];
    const dam = damArr;
    const esPayload = damMarket === 'oree' ? entsoeOverlayByZone.ES : null;
    const plPayload = damMarket === 'oree' ? entsoeOverlayByZone.PL : null;
    const uaEntsoPayload = damMarket === 'oree' ? entsoeOverlayByZone.UA_ENTSO : null;
    const entsoeEsEurArr =
      esPayload?.ok && Array.isArray(esPayload.hourlyPriceDamEurPerKwh) ? esPayload.hourlyPriceDamEurPerKwh : null;
    const entsoePlEurArr =
      plPayload?.ok && Array.isArray(plPayload.hourlyPriceDamEurPerKwh) ? plPayload.hourlyPriceDamEurPerKwh : null;
    const entsoeUaEntsoeEurArr =
      uaEntsoPayload?.ok && Array.isArray(uaEntsoPayload.hourlyPriceDamEurPerKwh)
        ? uaEntsoPayload.hourlyPriceDamEurPerKwh
        : null;
    const fx = eurUahRate;
    const socArr =
      socPayload?.ok && socPayload?.configured && Array.isArray(socPayload.hourlySocPercent)
        ? socPayload.hourlySocPercent
        : null;
    const gridArr =
      socPayload?.ok && socPayload?.configured && Array.isArray(socPayload.hourlyGridPowerW)
        ? socPayload.hourlyGridPowerW
        : null;
    const freqArr =
      socPayload?.ok && socPayload?.configured && Array.isArray(socPayload.hourlyGridFrequencyHz)
        ? socPayload.hourlyGridFrequencyHz
        : null;
    const pvKwhArr =
      socPayload?.ok && socPayload?.configured && Array.isArray(socPayload.hourlyPvKwh) ? socPayload.hourlyPvKwh : null;
    const loadKwhArr =
      socPayload?.ok && socPayload?.configured && Array.isArray(socPayload.hourlyLoadKwh)
        ? socPayload.hourlyLoadKwh
        : null;
    const out = Array.from({ length: 24 }, (_, i) => {
      let socPercent = null;
      if (socArr && socArr[i] != null && Number.isFinite(Number(socArr[i]))) {
        socPercent = Number(socArr[i]);
      }
      let gridKw = null;
      if (gridArr && gridArr[i] != null && Number.isFinite(Number(gridArr[i]))) {
        gridKw = Number(gridArr[i]) / 1000;
      }
      let gridFreqHz = null;
      if (freqArr && freqArr[i] != null && Number.isFinite(Number(freqArr[i]))) {
        gridFreqHz = Number(freqArr[i]);
      }
      let pvKwh = null;
      if (pvKwhArr && pvKwhArr[i] != null && Number.isFinite(Number(pvKwhArr[i]))) {
        pvKwh = Number(pvKwhArr[i]);
      }
      let consKwhNeg = null;
      if (loadKwhArr && loadKwhArr[i] != null && Number.isFinite(Number(loadKwhArr[i]))) {
        consKwhNeg = -Math.abs(Number(loadKwhArr[i]));
      }
      return {
        hour: i + 1,
        damPriceKwh: dam[i] != null && Number.isFinite(Number(dam[i])) ? Number(dam[i]) : null,
        damEntsoeEsEurKwh:
          entsoeEsEurArr && entsoeEsEurArr[i] != null && Number.isFinite(Number(entsoeEsEurArr[i]))
            ? Number(entsoeEsEurArr[i])
            : null,
        damEntsoePlEurKwh:
          entsoePlEurArr && entsoePlEurArr[i] != null && Number.isFinite(Number(entsoePlEurArr[i]))
            ? Number(entsoePlEurArr[i])
            : null,
        damEntsoeEsUahKwh:
          fx != null &&
          fx > 0 &&
          entsoeEsEurArr &&
          entsoeEsEurArr[i] != null &&
          Number.isFinite(Number(entsoeEsEurArr[i]))
            ? Number(entsoeEsEurArr[i]) * fx
            : null,
        damEntsoePlUahKwh:
          fx != null &&
          fx > 0 &&
          entsoePlEurArr &&
          entsoePlEurArr[i] != null &&
          Number.isFinite(Number(entsoePlEurArr[i]))
            ? Number(entsoePlEurArr[i]) * fx
            : null,
        damEntsoeUaEntsoeEurKwh:
          entsoeUaEntsoeEurArr && entsoeUaEntsoeEurArr[i] != null && Number.isFinite(Number(entsoeUaEntsoeEurArr[i]))
            ? Number(entsoeUaEntsoeEurArr[i])
            : null,
        damEntsoeUaEntsoeUahKwh:
          fx != null &&
          fx > 0 &&
          entsoeUaEntsoeEurArr &&
          entsoeUaEntsoeEurArr[i] != null &&
          Number.isFinite(Number(entsoeUaEntsoeEurArr[i]))
            ? Number(entsoeUaEntsoeEurArr[i]) * fx
            : null,
        socPercent,
        gridKw,
        gridFreqHz,
        gridKwLive: false,
        gridKwFromLoad: false,
        pvKwh,
        consKwhNeg,
        pvLoadLive: false,
      };
    });

    if (effectiveHuaweiStation && huaweiHourly?.ok && Array.isArray(huaweiHourly.hours)) {
      const byHour = new Map(huaweiHourly.hours.map(h => [Number(h.hour), h]));
      for (let i = 0; i < 24; i++) {
        const hr = byHour.get(i + 1);
        if (!hr) continue;
        const slot = out[i];
        const gImp = hr.gridImportKwh;
        const gExp = hr.gridExportKwh;
        let gridKw = null;
        const hasImp = gImp != null && Number.isFinite(Number(gImp)) && Number(gImp) !== 0;
        const hasExp = gExp != null && Number.isFinite(Number(gExp)) && Number(gExp) !== 0;
        if (hasImp || hasExp) {
          gridKw = Number(gImp || 0) + Number(gExp || 0);
        }
        let pvKwh = null;
        if (hr.generationKwh != null && Number.isFinite(Number(hr.generationKwh)) && Number(hr.generationKwh) !== 0) {
          pvKwh = Number(hr.generationKwh);
        }
        let consKwhNeg = null;
        if (
          hr.consumptionKwh != null &&
          Number.isFinite(Number(hr.consumptionKwh)) &&
          Number(hr.consumptionKwh) !== 0
        ) {
          consKwhNeg = Number(hr.consumptionKwh);
        }
        out[i] = {
          ...slot,
          gridKw,
          pvKwh,
          consKwhNeg,
          gridKwLive: false,
          gridKwFromLoad: false,
          pvLoadLive: false,
        };
      }
    }

    if (!effectiveHuaweiStation) {
      const liveGridKw =
        liveGridPowerW != null && Number.isFinite(Number(liveGridPowerW)) ? Number(liveGridPowerW) / 1000 : null;
      const liveLoadKw =
        liveLoadPowerW != null && Number.isFinite(Number(liveLoadPowerW)) ? Number(liveLoadPowerW) / 1000 : null;
      const hi = kyivHourIndexNowForDate(tradeDay);
      if (hi != null) {
        const hasAnyGrid = out.some(r => r.gridKw != null && Number.isFinite(r.gridKw));
        const slot = out[hi];
        const slotEmpty = slot.gridKw == null || !Number.isFinite(slot.gridKw);
        let fallbackKw = liveGridKw;
        let fallbackFromLoad = false;
        if (fallbackKw != null && Math.abs(fallbackKw) < 0.2 && liveLoadKw != null && liveLoadKw > 0) {
          fallbackKw = liveLoadKw;
          fallbackFromLoad = true;
        }
        if (fallbackKw != null && (slotEmpty || !hasAnyGrid)) {
          out[hi] = { ...slot, gridKw: fallbackKw, gridKwLive: true, gridKwFromLoad: fallbackFromLoad };
        }
      }
      if (
        usesDeyeFlowBalance(effectiveInverterSn) &&
        hi != null &&
        liveLoadPowerW != null &&
        livePvPowerW != null &&
        liveBatteryPowerW != null &&
        Number.isFinite(Number(liveLoadPowerW)) &&
        Number.isFinite(Number(livePvPowerW)) &&
        Number.isFinite(Number(liveBatteryPowerW))
      ) {
        const balW =
          Number(liveLoadPowerW) - DEYE_FLOW_BALANCE_PV_FACTOR * Number(livePvPowerW) - Number(liveBatteryPowerW);
        const slot = out[hi];
        out[hi] = {
          ...slot,
          gridKw: balW / 1000,
          gridKwLive: true,
          gridKwFromLoad: false,
        };
      }
      if (hi != null && effectiveInverterSn) {
        const hasAnyPv = out.some(r => r.pvKwh != null && Number.isFinite(r.pvKwh));
        const hasAnyLoad = out.some(r => r.consKwhNeg != null && Number.isFinite(r.consKwhNeg));
        const slot = out[hi];
        let pvK = slot.pvKwh;
        let cNeg = slot.consKwhNeg;
        if (livePvPowerW != null && Number.isFinite(Number(livePvPowerW)) && (pvK == null || !hasAnyPv)) {
          const raw = Number(livePvPowerW);
          const eff = usesDeyeFlowBalance(effectiveInverterSn) ? raw * DEYE_FLOW_BALANCE_PV_FACTOR : raw;
          pvK = eff / 1000;
        }
        if (liveLoadPowerW != null && Number.isFinite(Number(liveLoadPowerW)) && (cNeg == null || !hasAnyLoad)) {
          cNeg = -Math.abs(Number(liveLoadPowerW)) / 1000;
        }
        if (pvK !== slot.pvKwh || cNeg !== slot.consKwhNeg) {
          out[hi] = {
            ...slot,
            pvKwh: pvK ?? slot.pvKwh,
            consKwhNeg: cNeg ?? slot.consKwhNeg,
            pvLoadLive: true,
          };
        }
      }
    }
    return out;
  }, [
    payload,
    damMarket,
    entsoeOverlayByZone,
    socPayload,
    tradeDay,
    liveGridPowerW,
    liveLoadPowerW,
    livePvPowerW,
    liveBatteryPowerW,
    effectiveInverterSn,
    effectiveHuaweiStation,
    huaweiHourly,
    eurUahRate,
  ]);

  const lostSolarForecast = useMemo(() => computeLostSolarForecast(rows, clearSkyWeights), [rows, clearSkyWeights]);

  const gridDomain = useMemo(() => {
    const vals = rows.map(r => r.gridKw).filter(v => v != null && Number.isFinite(v));
    if (!vals.length) return [-0.25, 0.25];
    const raw = Math.max(...vals.map(v => Math.abs(v)), 0.25);
    const cap = niceSymmetricCap(raw);
    return [-cap, cap];
  }, [rows]);

  const gridYTicks = useMemo(() => fiveSymmetricTicks(gridDomain[0], gridDomain[1]), [gridDomain]);

  const pvLoadDomain = useMemo(() => {
    const vals = [];
    for (const r of rows) {
      if (r.pvKwh != null && Number.isFinite(r.pvKwh)) vals.push(r.pvKwh);
      if (r.consKwhNeg != null && Number.isFinite(r.consKwhNeg)) vals.push(Math.abs(r.consKwhNeg));
    }
    if (!vals.length) return [-0.25, 0.25];
    const raw = Math.max(...vals, 0.25);
    const cap = niceSymmetricCap(raw);
    return [-cap, cap];
  }, [rows]);

  const pvLoadYTicks = useMemo(() => fiveSymmetricTicks(pvLoadDomain[0], pvLoadDomain[1]), [pvLoadDomain]);

  /** Approximate kWh for the selected Kyiv calendar day from hourly series (kW·h for grid; kWh per hour for PV/load). */
  const damDayEnergyTotals = useMemo(() => {
    if (!rows.length) {
      return {
        importKwh: null,
        exportKwh: null,
        generationKwh: null,
        consumptionKwh: null,
        lostSolarKwh: null,
      };
    }
    let importKwh = 0;
    let exportKwh = 0;
    let generationKwh = 0;
    let consumptionKwh = 0;
    let anyImport = false;
    let anyExport = false;
    let anyGen = false;
    let anyCons = false;
    for (const r of rows) {
      const g = r.gridKw;
      if (g != null && Number.isFinite(g)) {
        if (g > 0) {
          importKwh += g;
          anyImport = true;
        } else if (g < 0) {
          exportKwh += -g;
          anyExport = true;
        }
      }
      const pv = r.pvKwh;
      if (pv != null && Number.isFinite(pv)) {
        generationKwh += Math.max(0, pv);
        anyGen = true;
      }
      const c = r.consKwhNeg;
      if (c != null && Number.isFinite(c)) {
        consumptionKwh += Math.abs(c);
        anyCons = true;
      }
    }
    const lostSolarKwh =
      lostSolarForecast != null && Number.isFinite(lostSolarForecast.totalKwh) ? lostSolarForecast.totalKwh : null;
    return {
      importKwh: anyImport ? importKwh : null,
      exportKwh: anyExport ? exportKwh : null,
      generationKwh: anyGen ? generationKwh : null,
      consumptionKwh: anyCons ? consumptionKwh : null,
      lostSolarKwh,
    };
  }, [rows, lostSolarForecast]);

  const damGridWeightedMoneyUah = useMemo(() => {
    if (!(effectiveInverterSn || effectiveHuaweiStation) || !rows.length) return null;
    return computeDamWeightedGridMoneyUah(rows, damMarket, eurUahRate);
  }, [rows, damMarket, eurUahRate, effectiveInverterSn, effectiveHuaweiStation]);

  const damGridMoneyPartialNote = useMemo(() => {
    if (!damGridWeightedMoneyUah) return false;
    const imp =
      damDayEnergyTotals.importKwh != null &&
      damDayEnergyTotals.importKwh - damGridWeightedMoneyUah.importKwhWeighted > 0.05;
    const exp =
      damDayEnergyTotals.exportKwh != null &&
      damDayEnergyTotals.exportKwh - damGridWeightedMoneyUah.exportKwhWeighted > 0.05;
    return Boolean(imp || exp);
  }, [damGridWeightedMoneyUah, damDayEnergyTotals.importKwh, damDayEnergyTotals.exportKwh]);

  /** Σ_h (+export_kWh×DAM − import_kWh×DAM); same hour logic as landing-totals ``arbitrageRevenueUah``. */
  const damArbitrageRevenueDisplay = useMemo(() => {
    const hasGridActivity = damDayEnergyTotals.importKwh != null || damDayEnergyTotals.exportKwh != null;
    if (!damGridWeightedMoneyUah) {
      return { value: null, showDamUnavailable: Boolean(hasGridActivity) };
    }
    const net = damGridWeightedMoneyUah.netArbitrageUah;
    if (net == null) {
      return { value: null, showDamUnavailable: Boolean(hasGridActivity) };
    }
    return { value: net, showDamUnavailable: false };
  }, [damGridWeightedMoneyUah, damDayEnergyTotals.importKwh, damDayEnergyTotals.exportKwh]);

  /** Hide grid arbitrage line when there was no grid export energy this Kyiv day (import-only is not arbitrage UX here). */
  const showDamGridArbitrageRow = useMemo(() => {
    const ex = damDayEnergyTotals.exportKwh;
    return ex != null && Number.isFinite(ex) && ex > 1e-9;
  }, [damDayEnergyTotals.exportKwh]);

  const hzDomain = useMemo(() => {
    const vals = rows.map(r => r.gridFreqHz).filter(v => v != null && Number.isFinite(v));
    if (!vals.length) return [49.5, 50.5];
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const span = hi - lo;
    const pad = span < 0.02 ? 0.08 : Math.max(0.04, span * 0.25);
    return [lo - pad, hi + pad];
  }, [rows]);

  const lineChartRightMargin = useMemo(() => {
    if (damChartMobile) return 8;
    if (!showDeyeExtras) return 16;
    const { soc, hz } = damSeriesVisible;
    if (soc && hz) return DAM_RIGHT_Y_AXIS_WIDTH + DAM_HZ_Y_AXIS_WIDTH + 28;
    if (soc) return 52;
    if (hz) return DAM_HZ_Y_AXIS_WIDTH + 28;
    return 16;
  }, [showDeyeExtras, damSeriesVisible, damChartMobile]);

  /** Same horizontal gutters + matched right-axis bands so LineChart and ComposedChart X domains align. */
  const damLineChartMargin = useMemo(
    () =>
      damChartMobile
        ? { top: 4, right: lineChartRightMargin, left: 8, bottom: 4 }
        : {
            top: 8,
            right: lineChartRightMargin,
            left: showEntsoeEurAxis ? 4 : 8,
            bottom: 10,
          },
    [damChartMobile, lineChartRightMargin, showEntsoeEurAxis]
  );

  const damComposedChartMargin = useMemo(
    () =>
      damChartMobile
        ? { top: 4, right: lineChartRightMargin, left: 8, bottom: 8 }
        : {
            top: 6,
            right: lineChartRightMargin,
            left: 8,
            bottom: 28,
          },
    [damChartMobile, lineChartRightMargin]
  );

  const onDateInput = e => {
    const v = e.target.value;
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) setTradeDay(clampTradeDayIsoForMarket(v, damMarket));
  };

  const goPrev = () => setTradeDay(d => addCalendarDays(d, -1));
  const goNext = () =>
    setTradeDay(d => {
      const next = addCalendarDays(d, 1);
      const cap = damMarket === 'entsoe' ? maxTradeDayBrusselsIso() : maxTradeDayKyivIso();
      return next > cap ? cap : next;
    });
  const goToday = () =>
    setTradeDay(damMarket === 'entsoe' ? brusselsCalendarIso() : kyivCalendarIso());

  const openTradeDayPicker = useCallback(inputRef => {
    const el = inputRef?.current;
    if (!el) return;
    if (typeof el.showPicker === 'function') {
      try {
        el.showPicker();
        return;
      } catch {
        /* fall through */
      }
    }
    el.click();
  }, []);

  const showEmbeddedHeadDateBar = variant !== 'fullpage' && !showEnergyBars;

  const hasChart = Boolean(payload?.ok) && rows.length === 24;
  const hasAnyDamPrice = useMemo(
    () => rows.some(r => r.damPriceKwh != null && Number.isFinite(Number(r.damPriceKwh))),
    [rows]
  );

  const damIndexChart = useMemo(() => {
    if (!indexesPayload?.ok || !indexesPayload?.data) return { tradeDay: '', rows: [] };
    const zone = pickDamIndexesZone(indexesPayload.data);
    if (!zone) return { tradeDay: '', rows: [] };
    return buildDamIndexRows(zone, t);
  }, [indexesPayload, t]);

  const damIndexesVsYesterdayPct = useMemo(() => {
    if (indexesLoading || indexesYesterdayLoading) return null;
    const cur = avgDamIndexUahKwhFromIndexesPayload(indexesPayload);
    const prev = avgDamIndexUahKwhFromIndexesPayload(indexesYesterdayPayload);
    if (cur == null || prev == null || prev === 0) return null;
    return ((cur - prev) / prev) * 100;
  }, [indexesPayload, indexesYesterdayPayload, indexesLoading, indexesYesterdayLoading]);

  const marketControls = (
    <div className="dam-market-toolbar" role="group" aria-label={t('damMarketLabel')}>
      <select
        className="pf-lang-select dam-market-select"
        aria-label={t('damMarketLabel')}
        value={damMarket}
        onChange={e => {
          const m = e.target.value;
          setDamMarket(m);
          setTradeDay(d => clampTradeDayIsoForMarket(d, m));
        }}
      >
        <option value="entsoe">{t('damMarketEntsoe')}</option>
        <option value="oree">{t('damMarketOree')}</option>
      </select>
      {damMarket === 'entsoe' ? (
        <select
          className="pf-lang-select dam-market-select"
          aria-label={t('damEntsoeZoneLabel')}
          value={entsoeZone}
          onChange={e => setEntsoeZone(e.target.value)}
        >
          {ENTSOE_ZONE_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ) : null}
    </div>
  );

  const dateBar = (
    <div className="dam-date-bar" role="group" aria-label={t('damDateLabel')}>
      <button type="button" className="dam-date-btn" onClick={goPrev} aria-label={t('damPrevDay')}>
        ‹
      </button>
      <input
        className="dam-date-input"
        type="date"
        value={tradeDay}
        max={maxTradeDay}
        onChange={onDateInput}
        aria-label={t('damDateLabel')}
      />
      <button
        type="button"
        className="dam-date-btn"
        onClick={goNext}
        disabled={tradeDay >= maxTradeDay}
        aria-label={t('damNextDay')}
      >
        ›
      </button>
      <button
        type="button"
        className="dam-date-btn dam-date-btn--today"
        onClick={goToday}
        disabled={tradeDay === calendarTodayIso}
        aria-label={t('damToday')}
      >
        {t('damToday')}
      </button>
    </div>
  );

  const renderSectionDateBar = (inputRef, idSuffix, classNameExtra = '') => (
    <div
      className={`dam-date-bar dam-date-bar--section${classNameExtra ? ` ${classNameExtra}` : ''}`.trim()}
      role="group"
      aria-label={t('damDateLabel')}
    >
      <button type="button" className="dam-date-btn" onClick={goPrev} aria-label={t('damPrevDay')}>
        ‹
      </button>
      <div className="dam-date-field">
        <span className="dam-date-field__text">{formatTradeDayDdMmYyyy(tradeDay)}</span>
        <button
          type="button"
          className="dam-date-field__calendar"
          onClick={() => openTradeDayPicker(inputRef)}
          aria-label={t('damOpenDatePickerAria')}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path
              fill="currentColor"
              d="M19 4h-1V2h-2v2H8V2H6v2H5c-1.11 0-1.99.9-1.99 2L3 20c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 16H5V10h14v10zM5 8V6h14v2H5zm2 4h5v5H7v-5z"
            />
          </svg>
        </button>
        <input
          ref={inputRef}
          id={`dam-section-trade-day-${variant}-${idSuffix}`}
          className="dam-date-field__native"
          type="date"
          tabIndex={-1}
          value={tradeDay}
          max={maxTradeDay}
          onChange={onDateInput}
          aria-hidden="true"
        />
      </div>
      <button
        type="button"
        className="dam-date-btn"
        onClick={goNext}
        disabled={tradeDay >= maxTradeDay}
        aria-label={t('damNextDay')}
      >
        ›
      </button>
      <button
        type="button"
        className="dam-date-btn dam-date-btn--today"
        onClick={goToday}
        disabled={tradeDay === calendarTodayIso}
        aria-label={t('damToday')}
      >
        {t('damToday')}
      </button>
    </div>
  );

  const logoSrc = `${process.env.PUBLIC_URL || ''}/static/220-km-logo.svg`;

  return (
    <>
      {variant === 'fullpage' ? (
        <div
          className={`dam-page-loader${loading ? ' dam-page-loader--visible' : ''}`}
          aria-hidden={!loading}
          role="status"
          aria-label={loading ? t('damLoading') : undefined}
        >
          <img
            className="dam-page-loader__logo"
            src={logoSrc}
            alt=""
            width={96}
            height={96}
            decoding="async"
          />
        </div>
      ) : null}
      {variant === 'fullpage' ? (
        <header className="pf-header dam-header">
          <div className="dam-header-left">
            <a className="pf-nav-link" href="/power-flow">
              {t('damNavToPowerFlow')}
            </a>
          </div>
          {marketControls}
          {showEnergyBars ? null : dateBar}
          <select
            id="dam-lang"
            className="pf-lang-select"
            aria-label={t('langSelectAria')}
            value={locale}
            onChange={onLangSelectChange}
          >
            {SUPPORTED.map(code => (
              <option key={code} value={code}>
                {LOCALE_NAMES[code] || code}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="pf-theme-btn"
            onClick={cycleTheme}
            aria-label={theme === 'dark' ? 'Switch to system theme' : theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
            title={theme === 'dark' ? 'Dark theme (click for system)' : theme === 'light' ? 'Light theme (click for dark)' : 'System theme (click for light)'}
          >
            {theme === 'dark' ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z" />
              </svg>
            ) : theme === 'light' ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="5" />
                <line x1="12" y1="1" x2="12" y2="3" />
                <line x1="12" y1="21" x2="12" y2="23" />
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                <line x1="1" y1="12" x2="3" y2="12" />
                <line x1="21" y1="12" x2="23" y2="12" />
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                <line x1="8" y1="21" x2="16" y2="21" />
                <line x1="12" y1="17" x2="12" y2="21" />
              </svg>
            )}
          </button>
        </header>
      ) : (
        <div className="dam-embedded-head">
          <div className="dam-embedded-head-main">
            <h2 className="dam-title dam-title-embedded">{t('damChartHeading')}</h2>
          </div>
          {showEmbeddedHeadDateBar ? dateBar : null}
        </div>
      )}

      {damMarket === 'oree' && !payload?.oreeConfigured ? (
        <div className="dam-banner dam-banner-warn" role="status">
          {t('damOreeNotConfigured')}
        </div>
      ) : null}

      {damMarket === 'entsoe' && !payload?.entsoeConfigured ? (
        <div className="dam-banner dam-banner-warn" role="status">
          {t('damEntsoeNotConfigured')}
        </div>
      ) : null}

      {damMarket === 'oree' && payload?.syncTriggered ? (
        <div className="dam-banner dam-banner-info" role="status">
          {t('damSyncNote')}
        </div>
      ) : null}

      {damMarket === 'oree' && payload?.lazyOree?.exhausted && !hasAnyDamPrice ? (
        <div className="dam-banner dam-banner-warn" role="status">
          {t('damLazyOreeExhausted')}
        </div>
      ) : null}

      {showDeyeExtras && socError ? (
        <div className="dam-banner dam-banner-warn" role="status">
          {t('damSocHistoryError')}: {socError}
        </div>
      ) : null}

      {effectiveHuaweiStation && huaweiHourly?.ok && huaweiHourly.empty ? (
        <div className="dam-banner dam-banner-info dam-banner--with-action" role="status">
          <span className="dam-banner__message">{t('damHuaweiDbSamplesHint')}</span>
          <button
            type="button"
            className="dam-banner__btn"
            onClick={() => void runHuaweiPowerSnapshot()}
            disabled={huaweiSnapshotBusy}
          >
            {huaweiSnapshotBusy ? t('damHuaweiUpdateNowBusy') : t('damHuaweiUpdateNow')}
          </button>
        </div>
      ) : null}

      <div className={variant === 'fullpage' ? 'dam-chart-card' : 'dam-chart-card dam-chart-card-embedded'}>
        {variant === 'fullpage' ? (
          <div className="dam-title-with-compare">
            <h1 className="dam-title">{t('damChartHeading')}</h1>
          </div>
        ) : null}

        {loadError ? (
          <p className="dam-error" role="alert">
            {t('damError')}: {loadError}
          </p>
        ) : null}

        {loading && !hasChart && variant !== 'fullpage' ? (
          <p className="dam-loading">{t('damLoading')}</p>
        ) : null}

        {showDeyeExtras && socLoading && !loading && hasChart ? (
          <p className="dam-loading dam-soc-loading">{t('damSocLoading')}</p>
        ) : null}

        {!loading && hasChart ? (
          <>
            {showEnergyBars ? renderSectionDateBar(tradeDayLineInputRef, 'line', 'dam-date-bar--above-chart') : null}
            <div
              className="dam-recharts-wrap dam-recharts-wrap--line-stack"
              style={{ minHeight: `calc(${h}px + 42px)` }}
            >
              <ResponsiveContainer width="100%" height={h}>
                <LineChart data={rows} syncId="dam-day" margin={damLineChartMargin} isAnimationActive={false}>
                  <CartesianGrid stroke={CHART.gridStroke} strokeDasharray="3 3" />
                  <XAxis
                    dataKey="hour"
                    type="number"
                    domain={DAM_X_AXIS_DOMAIN}
                    ticks={DAM_HOUR_X_TICKS}
                    allowDecimals={false}
                    padding={{ left: 0, right: 0 }}
                    tick={{ fill: CHART.axisText, fontSize: 11 }}
                    tickLine={false}
                    hide={damChartMobile}
                  />
                  {showEntsoeEurAxis ? (
                    <YAxis
                      yAxisId="entsoeEur"
                      orientation="left"
                      width={DAM_ENTSOE_OVERLAY_AXIS_WIDTH}
                      hide={damChartMobile}
                      tick={{ fill: CHART.axisTextAmber, fontSize: 11 }}
                      tickLine={false}
                      tickFormatter={v => fmtEur.format(v)}
                      axisLine={{ stroke: CHART.axisTextAmber }}
                      label={{
                        value: t('damTariffAxisEntsoeOverlay'),
                        angle: -90,
                        position: 'insideLeft',
                        offset: 8,
                        style: { fill: CHART.axisTextAmber, fontSize: 10, textAnchor: 'end' },
                      }}
                    />
                  ) : null}
                  {damSeriesVisible.primary ? (
                    <YAxis
                      yAxisId="dam"
                      width={DAM_LEFT_Y_AXIS_WIDTH}
                      hide={damChartMobile}
                      tick={{ fill: CHART.axisText, fontSize: 11 }}
                      tickLine={false}
                      tickFormatter={v => (damMarket === 'entsoe' ? fmtEur.format(v) : fmtDamTooltip.format(v))}
                      axisLine={{ stroke: 'rgba(252, 1, 155, 0.25)' }}
                      label={{
                        value: damMarket === 'entsoe' ? t('damTariffAxisEur') : t('damTariffAxis'),
                        angle: -90,
                        position: 'insideLeft',
                        offset: 10,
                        style: { fill: 'rgba(255,248,252,0.55)', fontSize: 11, textAnchor: 'end' },
                      }}
                    />
                  ) : null}
                  {showDeyeExtras && damSeriesVisible.soc ? (
                    <YAxis
                      yAxisId="soc"
                      orientation="right"
                      domain={[0, 100]}
                      width={DAM_RIGHT_Y_AXIS_WIDTH}
                      hide={damChartMobile}
                      tick={{ fill: CHART.axisTextBlue, fontSize: 11 }}
                      tickLine={false}
                      tickFormatter={v => fmt1.format(v)}
                      axisLine={{ stroke: CHART.axisTextBlue }}
                      label={{
                        value: t('damSocAxis'),
                        angle: 90,
                        position: 'insideRight',
                        offset: 10,
                        style: { fill: CHART.axisTextBlue, fontSize: 11, textAnchor: 'end' },
                      }}
                    />
                  ) : null}
                  {showDeyeExtras && damSeriesVisible.hz ? (
                    <YAxis
                      yAxisId="hz"
                      orientation="right"
                      domain={hzDomain}
                      width={DAM_HZ_Y_AXIS_WIDTH}
                      hide={damChartMobile}
                      tick={{
                        fill: CHART.axisTextHz,
                        fontSize: 11,
                        dx: 6,
                      }}
                      tickLine={false}
                      tickFormatter={v => fmtHz.format(v)}
                      axisLine={{ stroke: CHART.hzAxisLine }}
                      label={{
                        value: t('damGridFreqAxis'),
                        angle: 90,
                        position: 'insideRight',
                        offset: 14,
                        style: { fill: CHART.hzAxisLabel, fontSize: 11, textAnchor: 'end' },
                      }}
                    />
                  ) : null}
                  <Tooltip
                    content={tooltipProps => (
                      <DamLineChartTooltip
                        {...tooltipProps}
                        t={t}
                        fmtDamTooltip={fmtDamTooltip}
                        fmt1={fmt1}
                        fmtHz={fmtHz}
                        fmtUah={fmtUah}
                        fmtEur={fmtEur}
                        damUnitLabel={damUnitLabel}
                        lostSolarHourMoney={lostSolarForecast?.hourMoney ?? null}
                        lostSolarCurrency={damMarket === 'entsoe' ? 'eur' : 'uah'}
                        damLineSeriesName={damLineSeriesName}
                        damEntsoeOverlaySeriesNames={
                          showEntsoeOverlayAxis
                            ? [
                                ...(damSeriesVisible.uaEntsoe ? [damEntsoeOverlaySeriesNameUaEntsoe] : []),
                                ...(damSeriesVisible.es ? [damEntsoeOverlaySeriesNameEs] : []),
                                ...(damSeriesVisible.pl ? [damEntsoeOverlaySeriesNamePl] : []),
                              ]
                            : []
                        }
                        damMarket={damMarket}
                        entsoeZone={entsoeZone}
                        damEntsoeOverlaySeriesNameEs={damEntsoeOverlaySeriesNameEs}
                        damEntsoeOverlaySeriesNamePl={damEntsoeOverlaySeriesNamePl}
                        damEntsoeOverlaySeriesNameUaEntsoe={damEntsoeOverlaySeriesNameUaEntsoe}
                        entsoeOverlayUahMode={eurUahRate > 0}
                        isDark={isDark}
                      />
                    )}
                  />
                  {damSeriesVisible.primary ? (
                    <Line
                      yAxisId="dam"
                      type="monotone"
                      dataKey="damPriceKwh"
                      name={damLineSeriesName}
                      stroke="#22c55e"
                      strokeWidth={2.2}
                      dot={{ r: 2.5, fill: '#22c55e' }}
                      connectNulls
                      isAnimationActive={false}
                    />
                  ) : null}
                  {showEntsoeOverlayAxis && damSeriesVisible.uaEntsoe ? (
                    <Line
                      yAxisId={eurUahRate > 0 ? 'dam' : 'entsoeEur'}
                      type="monotone"
                      dataKey={eurUahRate > 0 ? 'damEntsoeUaEntsoeUahKwh' : 'damEntsoeUaEntsoeEurKwh'}
                      name={damEntsoeOverlaySeriesNameUaEntsoe}
                      stroke="#22d3ee"
                      strokeWidth={2}
                      strokeDasharray="4 3"
                      dot={{ r: 2, fill: '#22d3ee' }}
                      connectNulls
                      isAnimationActive={false}
                    />
                  ) : null}
                  {showEntsoeOverlayAxis && damSeriesVisible.es ? (
                    <Line
                      yAxisId={eurUahRate > 0 ? 'dam' : 'entsoeEur'}
                      type="monotone"
                      dataKey={eurUahRate > 0 ? 'damEntsoeEsUahKwh' : 'damEntsoeEsEurKwh'}
                      name={damEntsoeOverlaySeriesNameEs}
                      stroke="#f59e0b"
                      strokeWidth={2}
                      strokeDasharray="5 4"
                      dot={{ r: 2, fill: '#f59e0b' }}
                      connectNulls
                      isAnimationActive={false}
                    />
                  ) : null}
                  {showEntsoeOverlayAxis && damSeriesVisible.pl ? (
                    <Line
                      yAxisId={eurUahRate > 0 ? 'dam' : 'entsoeEur'}
                      type="monotone"
                      dataKey={eurUahRate > 0 ? 'damEntsoePlUahKwh' : 'damEntsoePlEurKwh'}
                      name={damEntsoeOverlaySeriesNamePl}
                      stroke="#c084fc"
                      strokeWidth={2}
                      strokeDasharray="6 5"
                      dot={{ r: 2, fill: '#c084fc' }}
                      connectNulls
                      isAnimationActive={false}
                    />
                  ) : null}
                  {showDeyeExtras && damSeriesVisible.soc ? (
                    <Line
                      yAxisId="soc"
                      type="monotone"
                      dataKey="socPercent"
                      name={t('damSeriesSoc')}
                      stroke="#60a5fa"
                      strokeWidth={2}
                      dot={{ r: 2.2, fill: '#60a5fa' }}
                      connectNulls
                      isAnimationActive={false}
                    />
                  ) : null}
                  {showDeyeExtras && damSeriesVisible.hz ? (
                    <Line
                      yAxisId="hz"
                      type="monotone"
                      dataKey="gridFreqHz"
                      name={t('damSeriesGridFreq')}
                      stroke="#facc15"
                      strokeWidth={1.85}
                      dot={{ r: 2, fill: '#facc15' }}
                      connectNulls
                      isAnimationActive={false}
                    />
                  ) : null}
                </LineChart>
              </ResponsiveContainer>
              <ul className="dam-line-legend" aria-label={t('damChartHeading')}>
                <li>
                  <span
                    className="dam-line-legend-item dam-line-legend-item--on dam-line-legend-item--primary-locked"
                    aria-label={damLineSeriesName}
                    title={damLineSeriesName}
                  >
                    <i className="dam-line-legend-swatch dam-line-legend-swatch--primary" aria-hidden />
                    {damLineSeriesName}
                  </span>
                </li>
                {showEntsoeOverlayAxis ? (
                  <li>
                    <button
                      type="button"
                      className={`dam-line-legend-item dam-line-legend-item--toggle ${
                        damSeriesVisible.uaEntsoe ? 'dam-line-legend-item--on' : 'dam-line-legend-item--off'
                      }`}
                      aria-pressed={damSeriesVisible.uaEntsoe}
                      aria-label={t('damLegendAriaToggleUaEntsoe')}
                      onClick={() => setDamSeriesVisible(v => ({ ...v, uaEntsoe: !v.uaEntsoe }))}
                    >
                      <i
                        className={`dam-line-legend-swatch dam-line-legend-swatch--ua-entso ${
                          damSeriesVisible.uaEntsoe ? '' : 'dam-line-legend-swatch--muted'
                        }`}
                        aria-hidden
                      />
                      {damEntsoeOverlaySeriesNameUaEntsoe}
                    </button>
                  </li>
                ) : null}
                {showEntsoeOverlayAxis ? (
                  <li>
                    <button
                      type="button"
                      className={`dam-line-legend-item dam-line-legend-item--toggle ${
                        damSeriesVisible.es ? 'dam-line-legend-item--on' : 'dam-line-legend-item--off'
                      }`}
                      aria-pressed={damSeriesVisible.es}
                      aria-label={t('damLegendAriaToggleEntsoe', { zone: 'ES' })}
                      onClick={() => setDamSeriesVisible(v => ({ ...v, es: !v.es }))}
                    >
                      <i
                        className={`dam-line-legend-swatch dam-line-legend-swatch--es ${
                          damSeriesVisible.es ? '' : 'dam-line-legend-swatch--muted'
                        }`}
                        aria-hidden
                      />
                      {damEntsoeOverlaySeriesNameEs}
                    </button>
                  </li>
                ) : null}
                {showEntsoeOverlayAxis ? (
                  <li>
                    <button
                      type="button"
                      className={`dam-line-legend-item dam-line-legend-item--toggle ${
                        damSeriesVisible.pl ? 'dam-line-legend-item--on' : 'dam-line-legend-item--off'
                      }`}
                      aria-pressed={damSeriesVisible.pl}
                      aria-label={t('damLegendAriaToggleEntsoe', { zone: 'PL' })}
                      onClick={() => setDamSeriesVisible(v => ({ ...v, pl: !v.pl }))}
                    >
                      <i
                        className={`dam-line-legend-swatch dam-line-legend-swatch--pl ${
                          damSeriesVisible.pl ? '' : 'dam-line-legend-swatch--muted'
                        }`}
                        aria-hidden
                      />
                      {damEntsoeOverlaySeriesNamePl}
                    </button>
                  </li>
                ) : null}
                {showDeyeExtras ? (
                  <li>
                    <button
                      type="button"
                      className={`dam-line-legend-item dam-line-legend-item--toggle ${
                        damSeriesVisible.soc ? 'dam-line-legend-item--on' : 'dam-line-legend-item--off'
                      }`}
                      aria-pressed={damSeriesVisible.soc}
                      aria-label={t('damLegendAriaToggleLine', { label: t('damSeriesSoc') })}
                      onClick={() => setDamSeriesVisible(v => ({ ...v, soc: !v.soc }))}
                    >
                      <i
                        className={`dam-line-legend-swatch dam-line-legend-swatch--soc ${
                          damSeriesVisible.soc ? '' : 'dam-line-legend-swatch--muted'
                        }`}
                        aria-hidden
                      />
                      {t('damSeriesSoc')}
                    </button>
                  </li>
                ) : null}
                {showDeyeExtras ? (
                  <li>
                    <button
                      type="button"
                      className={`dam-line-legend-item dam-line-legend-item--toggle ${
                        damSeriesVisible.hz ? 'dam-line-legend-item--on' : 'dam-line-legend-item--off'
                      }`}
                      aria-pressed={damSeriesVisible.hz}
                      aria-label={t('damLegendAriaToggleLine', { label: t('damSeriesGridFreq') })}
                      onClick={() => setDamSeriesVisible(v => ({ ...v, hz: !v.hz }))}
                    >
                      <i
                        className={`dam-line-legend-swatch dam-line-legend-swatch--hz ${
                          damSeriesVisible.hz ? '' : 'dam-line-legend-swatch--muted'
                        }`}
                        aria-hidden
                      />
                      {t('damSeriesGridFreq')}
                    </button>
                  </li>
                ) : null}
              </ul>
              {eurUahRate > 0 && eurUahRateLabel && showEntsoeOverlayAxis ? (
                <p className="dam-line-entsoe-uah-footnote" role="note">
                  {t('damEntsoeEurUahFootnote', {
                    date: String(eurUahRateLabel),
                    rate: fmtDamTooltip.format(eurUahRate),
                  })}
                </p>
              ) : null}
            </div>
          </>
        ) : null}

        {!loading && hasChart && showEnergyBars ? (
          <div className="dam-grid-bars-wrap">
            <p className="dam-grid-bars-caption">{t('damGridBarsCaption')}</p>
            <ul className="dam-day-energy-totals dam-day-energy-totals--grid" aria-label={t('damEnergyTotalsGridAria')}>
              <li className="dam-day-energy-totals__item">
                <span className="dam-day-energy-totals__swatch" style={{ background: '#f59e0b' }} aria-hidden />
                <div className="dam-day-energy-totals__stack">
                  <span className="dam-day-energy-totals__text">
                    {t('damEnergyTotalImport')}:{` `}
                    <span className="dam-day-energy-totals__value">
                      {damDayEnergyTotals.importKwh != null
                        ? `${fmt1.format(damDayEnergyTotals.importKwh)} ${t('damEnergyKwhUnit')}`
                        : '—'}
                    </span>
                  </span>
                  {damDayEnergyTotals.importKwh != null && damGridWeightedMoneyUah?.importCostUah != null ? (
                    <span className="dam-day-energy-totals__dam-sub">
                      {t('damEnergyGridImportDamLine', {
                        uah: fmtUah.format(damGridWeightedMoneyUah.importCostUah),
                        avg: fmtUah.format(damGridWeightedMoneyUah.importAvgUahPerKwh),
                      })}
                    </span>
                  ) : null}
                  {damDayEnergyTotals.importKwh != null &&
                  damGridWeightedMoneyUah &&
                  damGridWeightedMoneyUah.importCostUah == null ? (
                    <span className="dam-day-energy-totals__dam-sub">{t('damEnergyDamUahUnavailable')}</span>
                  ) : null}
                </div>
              </li>
              <li className="dam-day-energy-totals__item">
                <span className="dam-day-energy-totals__swatch" style={{ background: '#38bdf8' }} aria-hidden />
                <div className="dam-day-energy-totals__stack">
                  <span className="dam-day-energy-totals__text">
                    {t('damEnergyTotalExport')}:{` `}
                    <span className="dam-day-energy-totals__value">
                      {damDayEnergyTotals.exportKwh != null
                        ? `${fmt1.format(damDayEnergyTotals.exportKwh)} ${t('damEnergyKwhUnit')}`
                        : '—'}
                    </span>
                  </span>
                  {damDayEnergyTotals.exportKwh != null && damGridWeightedMoneyUah?.exportValueUah != null ? (
                    <span className="dam-day-energy-totals__dam-sub">
                      {t('damEnergyGridExportDamLine', {
                        uah: fmtUah.format(damGridWeightedMoneyUah.exportValueUah),
                        avg: fmtUah.format(damGridWeightedMoneyUah.exportAvgUahPerKwh),
                      })}
                    </span>
                  ) : null}
                  {damDayEnergyTotals.exportKwh != null &&
                  damGridWeightedMoneyUah &&
                  damGridWeightedMoneyUah.exportValueUah == null ? (
                    <span className="dam-day-energy-totals__dam-sub">{t('damEnergyDamUahUnavailable')}</span>
                  ) : null}
                </div>
              </li>
              {showDamGridArbitrageRow ? (
                <li className="dam-day-energy-totals__item">
                  <span className="dam-day-energy-totals__swatch" style={{ background: '#4ade80' }} aria-hidden />
                  <div className="dam-day-energy-totals__stack">
                    <span className="dam-day-energy-totals__text">
                      {t('damEnergyArbitrageRevenue')}:{` `}
                      <span className="dam-day-energy-totals__value">
                        {damArbitrageRevenueDisplay.value != null
                          ? `${fmtUah.format(damArbitrageRevenueDisplay.value)} ${t('roiValueUahUnit')}`
                          : '—'}
                      </span>
                    </span>
                    {damArbitrageRevenueDisplay.showDamUnavailable ? (
                      <span className="dam-day-energy-totals__dam-sub">{t('damEnergyDamUahUnavailable')}</span>
                    ) : null}
                    {damArbitrageRevenueDisplay.value != null ? (
                      <span className="dam-day-energy-totals__dam-sub">{t('damEnergyArbitrageRevenueSub')}</span>
                    ) : null}
                  </div>
                </li>
              ) : null}
            </ul>
            {damGridMoneyPartialNote ? (
              <p className="dam-grid-dam-money-footnote" role="note">
                {t('damEnergyDamPartialHoursNote')}
              </p>
            ) : null}
            {renderSectionDateBar(tradeDayGridInputRef, 'grid', 'dam-date-bar--above-chart')}
            <ResponsiveContainer width="100%" height={gridBarH}>
              <ComposedChart data={rows} syncId="dam-day" margin={damComposedChartMargin} isAnimationActive={false}>
                <CartesianGrid stroke={CHART.gridStrokeFaint} strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="hour"
                  type="number"
                  domain={DAM_X_AXIS_DOMAIN}
                  ticks={DAM_HOUR_X_TICKS}
                  allowDecimals={false}
                  padding={{ left: 0, right: 0 }}
                  tick={{ fill: CHART.axisText, fontSize: 11 }}
                  tickLine={false}
                  hide={damChartMobile}
                  label={{
                    value: t('damHourAxis'),
                    position: 'insideBottom',
                    offset: -10,
                    fill: 'rgba(255,248,252,0.55)',
                    fontSize: 11,
                  }}
                />
                <YAxis
                  domain={gridDomain}
                  ticks={gridYTicks}
                  width={DAM_LEFT_Y_AXIS_WIDTH}
                  hide={damChartMobile}
                  tick={{ fill: CHART.axisTextMuted, fontSize: 10 }}
                  tickLine={false}
                  tickFormatter={v => fmtGridKwTick.format(v)}
                  label={{
                    value: t('damGridPowerAxis'),
                    angle: -90,
                    position: 'insideLeft',
                    offset: 10,
                    style: { fill: 'rgba(255,248,252,0.55)', fontSize: 10, textAnchor: 'end' },
                  }}
                />
                {/* Match LineChart right Y-axis band widths so Cartesian X width is identical. */}
                {!damChartMobile && showDeyeExtras && damSeriesVisible.soc ? (
                  <YAxis
                    yAxisId="sync-right-margin"
                    orientation="right"
                    domain={[0, 100]}
                    width={DAM_RIGHT_Y_AXIS_WIDTH}
                    tick={false}
                    tickLine={false}
                    axisLine={false}
                  />
                ) : null}
                {!damChartMobile && showDeyeExtras && damSeriesVisible.hz ? (
                  <YAxis
                    yAxisId="sync-hz-margin"
                    orientation="right"
                    domain={[0, 1]}
                    width={DAM_HZ_Y_AXIS_WIDTH}
                    tick={false}
                    tickLine={false}
                    axisLine={false}
                  />
                ) : null}
                <ReferenceLine y={0} stroke={CHART.refLineStroke} strokeDasharray="4 4" />
                <Tooltip
                  wrapperStyle={{ outline: 'none' }}
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    const raw = payload[0]?.value;
                    const unit = t('damEnergyKwhUnit');
                    let valueLine = '—';
                    if (raw != null && raw !== '') {
                      const kw = Number(raw);
                      if (Number.isFinite(kw)) {
                        valueLine =
                          kw < 0
                            ? `- ${fmt1.format(Math.abs(kw))} ${unit}`
                            : `${fmt1.format(kw)} ${unit}`;
                      }
                    }
                    return (
                      <div className="recharts-default-tooltip" style={barTooltipStyle}>
                        <p
                          className="recharts-tooltip-label"
                          style={{ color: CHART.tooltipLabelColor, margin: 0 }}
                        >
                          {formatDamBarTooltipClockHour(label)}
                        </p>
                        <p
                          className="recharts-tooltip-item"
                          style={{ color: CHART.tooltipLabelColor, margin: '4px 0 0' }}
                        >
                          {valueLine}
                        </p>
                      </div>
                    );
                  }}
                />
                <Bar
                  dataKey="gridKw"
                  name={t('damSeriesGrid')}
                  maxBarSize={26}
                  minPointSize={8}
                  isAnimationActive={false}
                >
                  {rows.map((e, i) => (
                    <Cell
                      key={`grid-${i}`}
                      fill={
                        e.gridKw == null || !Number.isFinite(e.gridKw)
                          ? 'rgba(90, 90, 110, 0.2)'
                          : e.gridKw >= 0
                            ? '#f59e0b'
                            : '#38bdf8'
                      }
                    />
                  ))}
                </Bar>
                <Scatter
                  dataKey="gridKw"
                  tooltipType="none"
                  legendType="none"
                  isAnimationActive={false}
                  shape={dotProps => {
                    const { cx, cy, payload } = dotProps;
                    const v = payload?.gridKw;
                    if (v == null || !Number.isFinite(v) || cx == null || cy == null) return null;
                    const fill = v >= 0 ? '#f59e0b' : '#38bdf8';
                    return (
                      <circle cx={cx} cy={cy} r={5.5} fill={fill} stroke={CHART.circleBorder} strokeWidth={1.2} />
                    );
                  }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        ) : null}

        {!loading && hasChart && showEnergyBars ? (
          <div className="dam-pv-load-bars-wrap">
            <p className="dam-grid-bars-caption">{t('damPvLoadBarsCaption')}</p>
            <ul
              className="dam-day-energy-totals dam-day-energy-totals--pv-load"
              aria-label={t('damEnergyTotalsPvLoadAria')}
            >
              <li className="dam-day-energy-totals__item">
                <span className="dam-day-energy-totals__swatch" style={{ background: '#22c55e' }} aria-hidden />
                <span className="dam-day-energy-totals__text">
                  {t('damEnergyTotalGeneration')}:{` `}
                  <span className="dam-day-energy-totals__value">
                    {damDayEnergyTotals.generationKwh != null
                      ? `${fmt1.format(damDayEnergyTotals.generationKwh)} ${t('damEnergyKwhUnit')}`
                      : '—'}
                  </span>
                </span>
              </li>
              <li className="dam-day-energy-totals__item">
                <span className="dam-day-energy-totals__swatch" style={{ background: '#fb923c' }} aria-hidden />
                <span className="dam-day-energy-totals__text">
                  {t('damEnergyTotalConsumption')}:{` `}
                  <span className="dam-day-energy-totals__value">
                    {damDayEnergyTotals.consumptionKwh != null
                      ? `${fmt1.format(damDayEnergyTotals.consumptionKwh)} ${t('damEnergyKwhUnit')}`
                      : '—'}
                  </span>
                </span>
              </li>
              <li className="dam-day-energy-totals__item">
                <span className="dam-day-energy-totals__swatch" style={{ background: '#facc15' }} aria-hidden />
                <span className="dam-day-energy-totals__text">
                  {t('damEnergyTotalLostSolar')}:{` `}
                  <span className="dam-day-energy-totals__value">
                    {damDayEnergyTotals.lostSolarKwh != null
                      ? `${fmt1.format(damDayEnergyTotals.lostSolarKwh)} ${t('damEnergyKwhUnit')}`
                      : '—'}
                  </span>
                </span>
              </li>
            </ul>
            {renderSectionDateBar(tradeDayPvInputRef, 'pv', 'dam-date-bar--above-chart')}
            <ResponsiveContainer width="100%" height={gridBarH}>
              <ComposedChart data={rows} syncId="dam-day" margin={damComposedChartMargin} isAnimationActive={false}>
                <CartesianGrid stroke={CHART.gridStrokeFaint} strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="hour"
                  type="number"
                  domain={DAM_X_AXIS_DOMAIN}
                  ticks={DAM_HOUR_X_TICKS}
                  allowDecimals={false}
                  padding={{ left: 0, right: 0 }}
                  tick={{ fill: CHART.axisText, fontSize: 11 }}
                  tickLine={false}
                  hide={damChartMobile}
                  label={{
                    value: t('damHourAxis'),
                    position: 'insideBottom',
                    offset: -10,
                    fill: 'rgba(255,248,252,0.55)',
                    fontSize: 11,
                  }}
                />
                <YAxis
                  domain={pvLoadDomain}
                  ticks={pvLoadYTicks}
                  width={DAM_LEFT_Y_AXIS_WIDTH}
                  hide={damChartMobile}
                  tick={{ fill: CHART.axisTextMuted, fontSize: 10 }}
                  tickLine={false}
                  tickFormatter={v => fmtKwhTick.format(v)}
                  label={{
                    value: t('damPvLoadEnergyAxis'),
                    angle: -90,
                    position: 'insideLeft',
                    offset: 10,
                    style: { fill: 'rgba(255,248,252,0.55)', fontSize: 10, textAnchor: 'end' },
                  }}
                />
                {!damChartMobile && showDeyeExtras && damSeriesVisible.soc ? (
                  <YAxis
                    yAxisId="sync-right-margin"
                    orientation="right"
                    domain={[0, 100]}
                    width={DAM_RIGHT_Y_AXIS_WIDTH}
                    tick={false}
                    tickLine={false}
                    axisLine={false}
                  />
                ) : null}
                {!damChartMobile && showDeyeExtras && damSeriesVisible.hz ? (
                  <YAxis
                    yAxisId="sync-hz-margin"
                    orientation="right"
                    domain={[0, 1]}
                    width={DAM_HZ_Y_AXIS_WIDTH}
                    tick={false}
                    tickLine={false}
                    axisLine={false}
                  />
                ) : null}
                <ReferenceLine y={0} stroke={CHART.refLineStroke} strokeDasharray="4 4" />
                <Tooltip
                  wrapperStyle={{ outline: 'none' }}
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    const row = payload[0]?.payload;
                    const unit = t('damEnergyKwhUnit');
                    const genVal =
                      row?.pvKwh != null && row.pvKwh !== '' && Number.isFinite(Number(row.pvKwh))
                        ? `${fmt1.format(Number(row.pvKwh))} ${unit}`
                        : '—';
                    const consRaw = row?.consKwhNeg;
                    const consVal =
                      consRaw != null &&
                      consRaw !== '' &&
                      Number.isFinite(Number(consRaw)) &&
                      Number.isFinite(Math.abs(Number(consRaw)))
                        ? `${fmt1.format(Math.abs(Number(consRaw)))} ${unit}`
                        : '—';
                    const genLine = `${t('damPvLoadTooltipGen')}: ${genVal}`;
                    const consLine = `${t('damPvLoadTooltipCons')}: ${consVal}`;
                    return (
                      <div className="recharts-default-tooltip" style={barTooltipStyle}>
                        <p
                          className="recharts-tooltip-label"
                          style={{ color: CHART.tooltipLabelColor, margin: 0 }}
                        >
                          {formatDamBarTooltipClockHour(label)}
                        </p>
                        <p
                          className="recharts-tooltip-item"
                          style={{ color: CHART.tooltipLabelColor, margin: '4px 0 0' }}
                        >
                          {genLine}
                        </p>
                        <p
                          className="recharts-tooltip-item"
                          style={{ color: CHART.tooltipLabelColor, margin: '2px 0 0' }}
                        >
                          {consLine}
                        </p>
                      </div>
                    );
                  }}
                />
                <Bar
                  dataKey="pvKwh"
                  name={t('damSeriesPvKwh')}
                  maxBarSize={22}
                  minPointSize={6}
                  isAnimationActive={false}
                >
                  {rows.map((e, i) => (
                    <Cell
                      key={`pv-${i}`}
                      fill={e.pvKwh == null || !Number.isFinite(e.pvKwh) ? 'rgba(90, 90, 110, 0.2)' : '#22c55e'}
                    />
                  ))}
                </Bar>
                <Bar
                  dataKey="consKwhNeg"
                  name={t('damSeriesLoadKwh')}
                  maxBarSize={22}
                  minPointSize={6}
                  isAnimationActive={false}
                >
                  {rows.map((e, i) => (
                    <Cell
                      key={`load-${i}`}
                      fill={
                        e.consKwhNeg == null || !Number.isFinite(e.consKwhNeg) ? 'rgba(90, 90, 110, 0.2)' : '#fb923c'
                      }
                    />
                  ))}
                </Bar>
                <Scatter
                  dataKey="pvKwh"
                  tooltipType="none"
                  legendType="none"
                  isAnimationActive={false}
                  shape={dotProps => {
                    const { cx, cy, payload } = dotProps;
                    const v = payload?.pvKwh;
                    if (v == null || !Number.isFinite(v) || cx == null || cy == null) return null;
                    return (
                      <circle cx={cx} cy={cy} r={5} fill="#22c55e" stroke={CHART.circleBorder} strokeWidth={1.2} />
                    );
                  }}
                />
                <Scatter
                  dataKey="consKwhNeg"
                  tooltipType="none"
                  legendType="none"
                  isAnimationActive={false}
                  shape={dotProps => {
                    const { cx, cy, payload } = dotProps;
                    const v = payload?.consKwhNeg;
                    if (v == null || !Number.isFinite(v) || cx == null || cy == null) return null;
                    return (
                      <circle cx={cx} cy={cy} r={5} fill="#fb923c" stroke={CHART.circleBorder} strokeWidth={1.2} />
                    );
                  }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        ) : null}

        {damMarket === 'oree' ? (
          <details className="dam-oree-market-details">
            <summary className="dam-oree-market-summary">
              <span className="dam-oree-market-summary-label">{t('damOreeWebsiteLink')}</span>
            </summary>
            <div className="dam-oree-market-details-body">
              {!indexesPayload || indexesPayload.configured !== false ? (
                <div className="dam-indexes-wrap dam-indexes-wrap--in-oree-details">
                  <h3 className="dam-indexes-title">{t('damIndexesTitle')}</h3>
                  {damIndexChart.tradeDay ? (
                    <div className="dam-indexes-head-meta">
                      <p className="dam-indexes-trade-day">
                        {t('damIndexesTradeDay')}: {damIndexChart.tradeDay}
                      </p>
                      {damIndexesVsYesterdayPct != null ? (
                        <p
                          className="dam-indexes-vs-yesterday"
                          aria-label={t('damIndexesVsYesterdayAria', {
                            pct: fmtPct.format(damIndexesVsYesterdayPct),
                          })}
                        >
                          <span
                            className={
                              damIndexesVsYesterdayPct >= 0
                                ? 'dam-indexes-vs-yesterday-pct dam-indexes-vs-yesterday-pct--up'
                                : 'dam-indexes-vs-yesterday-pct dam-indexes-vs-yesterday-pct--down'
                            }
                          >
                            {fmtPct.format(damIndexesVsYesterdayPct)}%
                          </span>
                          <span className="dam-indexes-vs-yesterday-suffix"> {t('damIndexesVsYesterday')}</span>
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                  {indexesLoading ? <p className="dam-loading dam-indexes-loading">{t('damIndexesLoading')}</p> : null}
                  {indexesError ? (
                    <p className="dam-error dam-indexes-error" role="alert">
                      {t('damIndexesError')}: {indexesError}
                    </p>
                  ) : null}
                  {!indexesLoading && !indexesError && damIndexChart.rows.length > 0 ? (
                    <div className="dam-indexes-chart">
                      <ResponsiveContainer width="100%" height={240}>
                        <BarChart
                          data={damIndexChart.rows}
                          margin={{ top: 8, right: 10, left: 52, bottom: 8 }}
                          aria-label={t('damIndexesTitle')}
                        >
                          <CartesianGrid stroke={CHART.gridStrokeIndexes} strokeDasharray="3 3" vertical={false} />
                          <XAxis
                            dataKey="label"
                            tick={{ fill: CHART.axisText, fontSize: 11 }}
                            tickLine={false}
                            axisLine={{ stroke: 'rgba(252, 1, 155, 0.25)' }}
                          />
                          <YAxis
                            width={72}
                            tick={{ fill: CHART.axisText, fontSize: 11 }}
                            tickLine={false}
                            axisLine={{ stroke: 'rgba(252, 1, 155, 0.25)' }}
                            tickFormatter={v => fmtIndexKwh.format(v)}
                            label={{
                              value: t('damIndexesAxis'),
                              angle: -90,
                              position: 'left',
                              offset: 2,
                              dx: -44,
                              style: {
                                fill: 'rgba(255,248,252,0.88)',
                                fontSize: 11,
                                textAnchor: 'middle',
                              },
                            }}
                          />
                          <Tooltip
                            cursor={{ fill: CHART.tooltipCursor }}
                            wrapperClassName="dam-indexes-tooltip-wrap"
                            contentStyle={{
                              background: CHART.tooltipBg,
                              border: CHART.tooltipBorder,
                              borderRadius: 10,
                              color: CHART.tooltipColor,
                            }}
                            labelStyle={{ color: CHART.tooltipLabelColor, fontWeight: 600 }}
                            itemStyle={{ color: CHART.tooltipColor }}
                            formatter={(value, _name, item) => {
                              const row = item?.payload;
                              const pct =
                                row?.percent != null && Number.isFinite(row.percent)
                                  ? ` (${fmtPct.format(row.percent)}%)`
                                  : '';
                              return [
                                `${fmtIndexKwh.format(value)} ${t('damTooltipDamUnit')}${pct}`,
                                t('damIndexesTooltipPrice'),
                              ];
                            }}
                            labelFormatter={label => label}
                          />
                          <Bar
                            dataKey="priceUahKwh"
                            name={t('damIndexesTooltipPrice')}
                            radius={[8, 8, 0, 0]}
                            maxBarSize={56}
                          >
                            {damIndexChart.rows.map(e => (
                              <Cell key={`ix-${e.key}`} fill={e.color} fillOpacity={0.92} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : null}
                </div>
              ) : null}
              <section className="dam-oree-embed dam-oree-embed--in-details" aria-labelledby="dam-oree-embed-title">
                <div className="dam-oree-embed-header dam-oree-embed-header--link-only">
                  <h3 id="dam-oree-embed-title" className="dam-oree-embed-title">
                    <a
                      className="dam-oree-embed-external"
                      href={OREE_DAM_CHART_URL}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={t('damOreeWebsiteAria')}
                    >
                      {t('damOreeWebsiteLink')}
                    </a>
                  </h3>
                </div>
              </section>
            </div>
          </details>
        ) : null}

        {effectiveHuaweiStation ? (
          <HuaweiTotalsPanel
            stationCode={effectiveHuaweiStation}
            tradeDay={tradeDay}
            apiUrl={apiUrl}
            t={t}
            getBcp47Locale={getBcp47Locale}
          />
        ) : null}
      </div>
    </>
  );
}
