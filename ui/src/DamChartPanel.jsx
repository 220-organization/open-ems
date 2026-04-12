import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { OREE_DAM_CHART_URL } from './OreeDamChartModal';

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

function getInitialDamChartState(variant) {
  const marketDefault = 'oree';
  const zoneDefault = 'ES';
  if (variant !== 'fullpage') {
    return {
      date: clampTradeDayIsoForMarket(kyivCalendarIso(), marketDefault),
      market: marketDefault,
      zone: zoneDefault,
    };
  }
  try {
    const u = new URLSearchParams(window.location.search);
    const m = u.get('market');
    const market = m === 'oree' || m === 'entsoe' ? m : marketDefault;
    const z = (u.get('zone') || zoneDefault).toUpperCase();
    const zone = ENTSOE_ZONE_OPTIONS.some(o => o.value === z) ? z : zoneDefault;
    const dq = u.get('date');
    let date = dq && /^\d{4}-\d{2}-\d{2}$/.test(dq) ? dq : kyivCalendarIso();
    date = clampTradeDayIsoForMarket(date, market);
    return { date, market, zone };
  } catch {
    return {
      date: clampTradeDayIsoForMarket(kyivCalendarIso(), marketDefault),
      market: marketDefault,
      zone: zoneDefault,
    };
  }
}

function replaceUrlDamState(isoDate, market, zone) {
  try {
    const u = new URL(window.location.href);
    u.searchParams.set('date', isoDate);
    u.searchParams.set('market', market);
    u.searchParams.set('zone', zone);
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

/** Last selectable DAM trade day: tomorrow in Europe/Kyiv (aligned with lazy OREE rules). */
function maxTradeDayKyivIso() {
  return addCalendarDays(kyivCalendarIso(), 1);
}

function isoFromUtcDate(d) {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function monthStartIso(iso) {
  const [y, m] = iso.split('-').map(Number);
  return `${y}-${String(m).padStart(2, '0')}-01`;
}

/** Inclusive list of calendar ISO dates from start to end (string order matches chronology). */
function listDaysInclusive(startIso, endIso) {
  const out = [];
  let cur = startIso;
  while (cur <= endIso) {
    out.push(cur);
    cur = addCalendarDays(cur, 1);
  }
  return out;
}

function prevMonthRangeIso(tradeDayIso) {
  const [y, m] = tradeDayIso.split('-').map(Number);
  const monthIdx = m - 1;
  const end = new Date(Date.UTC(y, monthIdx, 0));
  const start = new Date(Date.UTC(y, monthIdx - 1, 1));
  return listDaysInclusive(isoFromUtcDate(start), isoFromUtcDate(end));
}

function avgDamFromHourly(hourly) {
  if (!Array.isArray(hourly)) return null;
  const nums = hourly.filter(x => x != null && Number.isFinite(Number(x))).map(Number);
  if (!nums.length) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function combinedAvgFromPayloads(payloads) {
  const all = [];
  for (const p of payloads) {
    const h = getHourlyDamPerKwhFromPayload(p);
    if (!Array.isArray(h)) continue;
    for (const x of h) {
      if (x != null && Number.isFinite(Number(x))) all.push(Number(x));
    }
  }
  if (!all.length) return null;
  return all.reduce((a, b) => a + b, 0) / all.length;
}

const DAM_COMPARE_DAY = 'day';
const DAM_COMPARE_MONTH = 'month';

function computeNeededCompareDates(tradeDay, mode) {
  if (mode === DAM_COMPARE_DAY) {
    return [addCalendarDays(tradeDay, -1)];
  }
  if (mode === DAM_COMPARE_MONTH) {
    const mtd = listDaysInclusive(monthStartIso(tradeDay), tradeDay);
    const prev = prevMonthRangeIso(tradeDay);
    const set = new Set([...mtd.filter(d => d !== tradeDay), ...prev]);
    return [...set];
  }
  return [];
}

function basePriceUahMwhFromDamindexesPayload(perm) {
  if (!perm?.ok || !perm.data) return null;
  const z = pickDamIndexesZone(perm.data);
  const cell = z?.BASE;
  if (!cell || typeof cell !== 'object') return null;
  return parseOreeDecimalLoose(cell.price);
}

function combinedAvgBaseFromIndexPayloads(payloads) {
  const nums = [];
  for (const p of payloads) {
    const v = basePriceUahMwhFromDamindexesPayload(p);
    if (v != null && Number.isFinite(v)) nums.push(v);
  }
  if (!nums.length) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
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
  return socPercent != null && Number.isFinite(Number(socPercent)) && Number(socPercent) >= 99.5;
}

/**
 * When the battery is full for 2+ hours, estimate solar income not captured into the pack
 * as sum(pv_kwh * DAM_uah_kwh) over those hours (DAM = “mining” opportunity rate per kWh).
 */
function computeLostSolarIncomeFromFullBatteryUah(rows) {
  if (!Array.isArray(rows) || !rows.length) return null;
  const fullHours = rows.filter(r => isSocFullPercent(r.socPercent)).length;
  if (fullHours < 2) return null;
  let uah = 0;
  for (const r of rows) {
    if (!isSocFullPercent(r.socPercent)) continue;
    const pv = r.pvKwh;
    if (pv == null || !Number.isFinite(Number(pv)) || Number(pv) <= 0) continue;
    const dam = r.damPriceKwh;
    const rate = dam != null && Number.isFinite(Number(dam)) ? Number(dam) : 0;
    uah += Number(pv) * rate;
  }
  return uah;
}

/** Sum of PV kWh during full-SoC hours when the day has 2+ full hours (same gate as lost income). */
function computeLostSolarKwhFromFullBattery(rows) {
  if (!Array.isArray(rows) || !rows.length) return null;
  const fullHours = rows.filter(r => isSocFullPercent(r.socPercent)).length;
  if (fullHours < 2) return null;
  let kwh = 0;
  let any = false;
  for (const r of rows) {
    if (!isSocFullPercent(r.socPercent)) continue;
    const pv = r.pvKwh;
    if (pv == null || !Number.isFinite(Number(pv)) || Number(pv) <= 0) continue;
    kwh += Number(pv);
    any = true;
  }
  return any ? kwh : 0;
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
  lostSolarIncomeMoney,
  lostSolarCurrency,
  damLineSeriesName,
  damEntsoeOverlaySeriesNames,
  damMarket,
  entsoeZone,
  damEntsoeOverlaySeriesNameEs,
  damEntsoeOverlaySeriesNamePl,
  damEntsoeOverlaySeriesNameUaEntsoe,
  entsoeOverlayUahMode,
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  const tooltipContentStyle = {
    background: 'rgba(24, 8, 32, 0.94)',
    border: '1px solid rgba(252, 1, 155, 0.35)',
    borderRadius: 10,
    color: '#fff',
    padding: '8px 12px',
  };
  const labelStyle = { color: 'rgba(255, 248, 252, 0.95)' };
  const itemStyle = { color: 'rgba(255, 248, 252, 0.95)' };
  const showLostSolar =
    lostSolarIncomeMoney != null && Number.isFinite(lostSolarIncomeMoney) && isSocFullPercent(row?.socPercent);

  return (
    <div className="recharts-default-tooltip" style={tooltipContentStyle}>
      <p className="recharts-tooltip-label" style={labelStyle}>
        {`${t('damHourTooltip')} ${label}`}
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
            ? `${fmtEur.format(lostSolarIncomeMoney)} ${t('roiValueEurUnit')}`
            : `${fmtUah.format(lostSolarIncomeMoney)} ${t('roiValueUahUnit')}`}
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
}) {
  const [tradeDay, setTradeDay] = useState(() => getInitialDamChartState(variant).date);
  const [damMarket, setDamMarket] = useState(() => getInitialDamChartState(variant).market);
  const [entsoeZone, setEntsoeZone] = useState(() => getInitialDamChartState(variant).zone);
  const [payload, setPayload] = useState(null);
  /** Per-zone ENTSO-E chart-day payloads when primary market is Ukraine (OREE); keys ES, PL. */
  const [entsoeOverlayByZone, setEntsoeOverlayByZone] = useState({});
  /** Line visibility toggled from the legend (UA/ENTSO-E primary, ES/PL overlay, SoC, Hz). */
  const [damSeriesVisible, setDamSeriesVisible] = useState({
    primary: true,
    es: false,
    pl: false,
    uaEntsoe: false,
    soc: true,
    hz: false,
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
  const [damCompareMode, setDamCompareMode] = useState(DAM_COMPARE_DAY);
  const [extraByDate, setExtraByDate] = useState({});
  const [compareLoading, setCompareLoading] = useState(false);
  const [indexesPayload, setIndexesPayload] = useState(null);
  const [indexesLoading, setIndexesLoading] = useState(true);
  const [indexesError, setIndexesError] = useState('');
  const [baseIndexCompareMode, setBaseIndexCompareMode] = useState(DAM_COMPARE_DAY);
  const [baseIndexExtraByDate, setBaseIndexExtraByDate] = useState({});
  const [baseIndexCompareLoading, setBaseIndexCompareLoading] = useState(false);
  const [urlInverterOnce] = useState(readInverterFromSearchOnce);
  /** NBU UAH per 1 EUR — scales ENTSO-E EUR/kWh onto the same axis as Ukraine DAM (UAH/kWh). */
  const [eurUahRate, setEurUahRate] = useState(null);
  const [eurUahRateLabel, setEurUahRateLabel] = useState(null);

  const effectiveInverterSn = (
    (inverterSnProp && String(inverterSnProp).trim()) ||
    (variant === 'fullpage' ? urlInverterOnce : '')
  ).trim();

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
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
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
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
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
        minimumFractionDigits: 2,
        maximumFractionDigits: 3,
      }),
    [bcp47]
  );

  const maxTradeDay = damMarket === 'entsoe' ? maxTradeDayBrusselsIso() : maxTradeDayKyivIso();

  useEffect(() => {
    if (tradeDay > maxTradeDay) setTradeDay(maxTradeDay);
  }, [tradeDay, maxTradeDay]);

  useEffect(() => {
    if (variant !== 'fullpage') return;
    replaceUrlDamState(tradeDay, damMarket, entsoeZone);
  }, [tradeDay, damMarket, entsoeZone, variant]);

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
          else setIndexesError(data.detail || r.statusText || 'damindexes');
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
    let cancelled = false;
    const need = computeNeededCompareDates(tradeDay, damCompareMode);
    const needFetch = need.filter(d => d !== tradeDay);
    if (needFetch.length === 0) {
      setExtraByDate({});
      setCompareLoading(false);
      return () => {
        cancelled = true;
      };
    }
    setCompareLoading(true);
    setExtraByDate({});
    (async () => {
      const entries = await Promise.all(
        needFetch.map(async iso => {
          try {
            const q = new URLSearchParams({ date: iso });
            if (damMarket === 'entsoe') q.set('zone', entsoeZone);
            const url =
              damMarket === 'entsoe' ? apiUrl(`/api/dam/entsoe/chart-day?${q}`) : apiUrl(`/api/dam/chart-day?${q}`);
            const r = await fetch(url, { cache: 'no-store' });
            if (!r.ok) return [iso, null];
            const data = await r.json();
            return [iso, data];
          } catch {
            return [iso, null];
          }
        })
      );
      if (cancelled) return;
      const next = {};
      for (const [iso, data] of entries) {
        if (data?.ok) next[iso] = data;
      }
      setExtraByDate(next);
      setCompareLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [tradeDay, damCompareMode, damMarket, entsoeZone]);

  useEffect(() => {
    if (damMarket !== 'oree') {
      setBaseIndexExtraByDate({});
      setBaseIndexCompareLoading(false);
      return undefined;
    }
    let cancelled = false;
    const need = computeNeededCompareDates(tradeDay, baseIndexCompareMode);
    const needFetch = need.filter(d => d !== tradeDay);
    if (needFetch.length === 0) {
      setBaseIndexExtraByDate({});
      setBaseIndexCompareLoading(false);
      return () => {
        cancelled = true;
      };
    }
    setBaseIndexCompareLoading(true);
    setBaseIndexExtraByDate({});
    (async () => {
      const entries = await Promise.all(
        needFetch.map(async iso => {
          try {
            const q = new URLSearchParams({ date: iso });
            const r = await fetch(apiUrl(`/api/dam/damindexes?${q}`), { cache: 'no-store' });
            if (!r.ok) return [iso, null];
            const data = await r.json();
            return [iso, data];
          } catch {
            return [iso, null];
          }
        })
      );
      if (cancelled) return;
      const next = {};
      for (const [iso, data] of entries) {
        if (data?.ok) next[iso] = data;
      }
      setBaseIndexExtraByDate(next);
      setBaseIndexCompareLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [tradeDay, baseIndexCompareMode, damMarket]);

  useEffect(() => {
    if (!effectiveInverterSn) {
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
  }, [tradeDay, effectiveInverterSn]);

  useEffect(() => {
    if (!effectiveInverterSn) {
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
  }, [effectiveInverterSn]);

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
    eurUahRate,
  ]);

  const lostSolarIncomeMoney = useMemo(() => computeLostSolarIncomeFromFullBatteryUah(rows), [rows]);

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
    const lostSolarKwh = computeLostSolarKwhFromFullBattery(rows);
    return {
      importKwh: anyImport ? importKwh : null,
      exportKwh: anyExport ? exportKwh : null,
      generationKwh: anyGen ? generationKwh : null,
      consumptionKwh: anyCons ? consumptionKwh : null,
      lostSolarKwh,
    };
  }, [rows]);

  const damGridWeightedMoneyUah = useMemo(() => {
    if (!effectiveInverterSn || !rows.length) return null;
    return computeDamWeightedGridMoneyUah(rows, damMarket, eurUahRate);
  }, [rows, damMarket, eurUahRate, effectiveInverterSn]);

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
    const hasGridActivity =
      damDayEnergyTotals.importKwh != null || damDayEnergyTotals.exportKwh != null;
    if (!damGridWeightedMoneyUah) {
      return { value: null, showDamUnavailable: Boolean(hasGridActivity) };
    }
    const net = damGridWeightedMoneyUah.netArbitrageUah;
    if (net == null) {
      return { value: null, showDamUnavailable: Boolean(hasGridActivity) };
    }
    return { value: net, showDamUnavailable: false };
  }, [damGridWeightedMoneyUah, damDayEnergyTotals.importKwh, damDayEnergyTotals.exportKwh]);

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
    if (!effectiveInverterSn) return 16;
    const { soc, hz } = damSeriesVisible;
    if (soc && hz) return DAM_RIGHT_Y_AXIS_WIDTH + DAM_HZ_Y_AXIS_WIDTH + 28;
    if (soc) return 52;
    if (hz) return DAM_HZ_Y_AXIS_WIDTH + 28;
    return 16;
  }, [effectiveInverterSn, damSeriesVisible, damChartMobile]);

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

  const hasChart = Boolean(payload?.ok) && rows.length === 24;
  const hasAnyDamPrice = useMemo(
    () => rows.some(r => r.damPriceKwh != null && Number.isFinite(Number(r.damPriceKwh))),
    [rows]
  );

  const damTrendPct = useMemo(() => {
    const dam = getHourlyDamPerKwhFromPayload(payload);
    if (!payload?.ok || !Array.isArray(dam)) return null;
    if (compareLoading) return null;

    if (damCompareMode === DAM_COMPARE_DAY) {
      const prev = extraByDate[addCalendarDays(tradeDay, -1)];
      const prevH = getHourlyDamPerKwhFromPayload(prev);
      const a = avgDamFromHourly(dam);
      const b = avgDamFromHourly(prevH);
      if (a == null || b == null || b === 0) return null;
      return ((a - b) / b) * 100;
    }

    if (damCompareMode === DAM_COMPARE_MONTH) {
      const mtd = listDaysInclusive(monthStartIso(tradeDay), tradeDay);
      const prevRange = prevMonthRangeIso(tradeDay);
      const mtdPayloads = mtd.map(d => (d === tradeDay ? payload : extraByDate[d]));
      const prevPayloads = prevRange.map(d => extraByDate[d]);
      if (mtdPayloads.some(p => !p?.ok)) return null;
      if (prevPayloads.some(p => !p?.ok)) return null;
      const a = combinedAvgFromPayloads(mtdPayloads);
      const b = combinedAvgFromPayloads(prevPayloads);
      if (a == null || b == null || b === 0) return null;
      return ((a - b) / b) * 100;
    }

    return null;
  }, [payload, extraByDate, tradeDay, damCompareMode, compareLoading]);

  const damIndexChart = useMemo(() => {
    if (!indexesPayload?.ok || !indexesPayload?.data) return { tradeDay: '', rows: [] };
    const zone = pickDamIndexesZone(indexesPayload.data);
    if (!zone) return { tradeDay: '', rows: [] };
    return buildDamIndexRows(zone, t);
  }, [indexesPayload, t]);

  const baseIndexTrendPct = useMemo(() => {
    if (!indexesPayload?.ok || !indexesPayload.data) return null;
    if (baseIndexCompareLoading || indexesLoading) return null;

    if (baseIndexCompareMode === DAM_COMPARE_DAY) {
      const a = basePriceUahMwhFromDamindexesPayload(indexesPayload);
      const b = basePriceUahMwhFromDamindexesPayload(baseIndexExtraByDate[addCalendarDays(tradeDay, -1)]);
      if (a == null || b == null || b === 0) return null;
      return ((a - b) / b) * 100;
    }

    if (baseIndexCompareMode === DAM_COMPARE_MONTH) {
      const mtd = listDaysInclusive(monthStartIso(tradeDay), tradeDay);
      const prevRange = prevMonthRangeIso(tradeDay);
      const mtdPayloads = mtd.map(d => (d === tradeDay ? indexesPayload : baseIndexExtraByDate[d]));
      const prevPayloads = prevRange.map(d => baseIndexExtraByDate[d]);
      if (mtdPayloads.some(p => !p?.ok)) return null;
      if (prevPayloads.some(p => !p?.ok)) return null;
      const a = combinedAvgBaseFromIndexPayloads(mtdPayloads);
      const b = combinedAvgBaseFromIndexPayloads(prevPayloads);
      if (a == null || b == null || b === 0) return null;
      return ((a - b) / b) * 100;
    }

    return null;
  }, [indexesPayload, baseIndexExtraByDate, tradeDay, baseIndexCompareMode, baseIndexCompareLoading, indexesLoading]);

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
    </div>
  );

  const damCompareControls = (
    <div className="dam-compare-row">
      <select
        id={`dam-compare-mode-${variant}`}
        className="pf-lang-select dam-compare-select"
        aria-label={t('damCompareSelectAria')}
        value={damCompareMode}
        onChange={e => setDamCompareMode(e.target.value)}
      >
        <option value={DAM_COMPARE_DAY}>{t('damCompareOptionDay')}</option>
        <option value={DAM_COMPARE_MONTH}>{t('damCompareOptionMonth')}</option>
      </select>
      <div className="dam-trend-line" aria-live="polite">
        {compareLoading || loading ? (
          <span className="dam-trend-line--muted">…</span>
        ) : damTrendPct == null ? (
          <span className="dam-trend-line--muted">—</span>
        ) : (
          <span className={damTrendPct >= 0 ? 'dam-trend-line--up' : 'dam-trend-line--down'}>
            {fmtPct.format(damTrendPct)}%
          </span>
        )}
      </div>
    </div>
  );

  return (
    <>
      {variant === 'fullpage' ? (
        <header className="pf-header dam-header">
          <div className="dam-header-left">
            <a className="pf-nav-link" href="/power-flow">
              {t('damNavToPowerFlow')}
            </a>
          </div>
          {marketControls}
          {dateBar}
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
        </header>
      ) : (
        <div className="dam-embedded-head">
          <div className="dam-embedded-head-main">
            <h2 className="dam-title dam-title-embedded">{t('damChartHeading')}</h2>
            {damCompareControls}
          </div>
          {dateBar}
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

      {effectiveInverterSn && socError ? (
        <div className="dam-banner dam-banner-warn" role="status">
          {t('damSocHistoryError')}: {socError}
        </div>
      ) : null}

      <div className={variant === 'fullpage' ? 'dam-chart-card' : 'dam-chart-card dam-chart-card-embedded'}>
        {variant === 'fullpage' ? (
          <div className="dam-title-with-compare">
            <h1 className="dam-title">{t('damChartHeading')}</h1>
            {damCompareControls}
          </div>
        ) : null}

        {loadError ? (
          <p className="dam-error" role="alert">
            {t('damError')}: {loadError}
          </p>
        ) : null}

        {loading && !hasChart ? <p className="dam-loading">{t('damLoading')}</p> : null}

        {effectiveInverterSn && socLoading && !loading && hasChart ? (
          <p className="dam-loading dam-soc-loading">{t('damSocLoading')}</p>
        ) : null}

        {!loading && hasChart ? (
          <div className="dam-recharts-wrap dam-recharts-wrap--line-stack" style={{ minHeight: `calc(${h}px + 42px)` }}>
            <ResponsiveContainer width="100%" height={h}>
              <LineChart data={rows} syncId="dam-day" margin={damLineChartMargin} isAnimationActive={false}>
                <CartesianGrid stroke="rgba(252, 1, 155, 0.12)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="hour"
                  type="number"
                  domain={DAM_X_AXIS_DOMAIN}
                  ticks={DAM_HOUR_X_TICKS}
                  allowDecimals={false}
                  padding={{ left: 0, right: 0 }}
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                  tickLine={false}
                  hide={damChartMobile}
                />
                {showEntsoeEurAxis ? (
                  <YAxis
                    yAxisId="entsoeEur"
                    orientation="left"
                    width={DAM_ENTSOE_OVERLAY_AXIS_WIDTH}
                    hide={damChartMobile}
                    tick={{ fill: 'rgba(251, 191, 36, 0.92)', fontSize: 11 }}
                    tickLine={false}
                    tickFormatter={v => fmtEur.format(v)}
                    axisLine={{ stroke: 'rgba(251, 191, 36, 0.35)' }}
                    label={{
                      value: t('damTariffAxisEntsoeOverlay'),
                      angle: -90,
                      position: 'insideLeft',
                      offset: 8,
                      style: { fill: 'rgba(251, 191, 36, 0.7)', fontSize: 10, textAnchor: 'end' },
                    }}
                  />
                ) : null}
                {damSeriesVisible.primary ? (
                  <YAxis
                    yAxisId="dam"
                    width={DAM_LEFT_Y_AXIS_WIDTH}
                    hide={damChartMobile}
                    tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                    tickLine={false}
                    tickFormatter={v => (damMarket === 'entsoe' ? fmtEur.format(v) : fmt1.format(v))}
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
                {effectiveInverterSn && damSeriesVisible.soc ? (
                  <YAxis
                    yAxisId="soc"
                    orientation="right"
                    domain={[0, 100]}
                    width={DAM_RIGHT_Y_AXIS_WIDTH}
                    hide={damChartMobile}
                    tick={{ fill: 'rgba(147, 197, 253, 0.9)', fontSize: 11 }}
                    tickLine={false}
                    tickFormatter={v => fmt1.format(v)}
                    axisLine={{ stroke: 'rgba(96, 165, 250, 0.35)' }}
                    label={{
                      value: t('damSocAxis'),
                      angle: 90,
                      position: 'insideRight',
                      offset: 10,
                      style: { fill: 'rgba(147, 197, 253, 0.7)', fontSize: 11, textAnchor: 'end' },
                    }}
                  />
                ) : null}
                {effectiveInverterSn && damSeriesVisible.hz ? (
                  <YAxis
                    yAxisId="hz"
                    orientation="right"
                    domain={hzDomain}
                    width={DAM_HZ_Y_AXIS_WIDTH}
                    hide={damChartMobile}
                    tick={{
                      fill: 'rgba(250, 204, 21, 0.92)',
                      fontSize: 11,
                      dx: 6,
                    }}
                    tickLine={false}
                    tickFormatter={v => fmtHz.format(v)}
                    axisLine={{ stroke: 'rgba(250, 204, 21, 0.35)' }}
                    label={{
                      value: t('damGridFreqAxis'),
                      angle: 90,
                      position: 'insideRight',
                      offset: 14,
                      style: { fill: 'rgba(250, 204, 21, 0.75)', fontSize: 11, textAnchor: 'end' },
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
                      lostSolarIncomeMoney={lostSolarIncomeMoney}
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
                {effectiveInverterSn && damSeriesVisible.soc ? (
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
                {effectiveInverterSn && damSeriesVisible.hz ? (
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
                <button
                  type="button"
                  className={`dam-line-legend-item dam-line-legend-item--toggle ${
                    damSeriesVisible.primary ? 'dam-line-legend-item--on' : 'dam-line-legend-item--off'
                  }`}
                  aria-pressed={damSeriesVisible.primary}
                  aria-label={t('damLegendAriaToggleLine', { label: damLineSeriesName })}
                  onClick={() => setDamSeriesVisible(v => ({ ...v, primary: !v.primary }))}
                >
                  <i
                    className={`dam-line-legend-swatch dam-line-legend-swatch--primary ${
                      damSeriesVisible.primary ? '' : 'dam-line-legend-swatch--muted'
                    }`}
                    aria-hidden
                  />
                  {damLineSeriesName}
                </button>
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
              {effectiveInverterSn ? (
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
              {effectiveInverterSn ? (
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
        ) : null}

        {!loading && hasChart && effectiveInverterSn ? (
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
            </ul>
            {damGridMoneyPartialNote ? (
              <p className="dam-grid-dam-money-footnote" role="note">
                {t('damEnergyDamPartialHoursNote')}
              </p>
            ) : null}
            <ResponsiveContainer width="100%" height={gridBarH}>
              <ComposedChart data={rows} syncId="dam-day" margin={damComposedChartMargin} isAnimationActive={false}>
                <CartesianGrid stroke="rgba(252, 1, 155, 0.08)" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="hour"
                  type="number"
                  domain={DAM_X_AXIS_DOMAIN}
                  ticks={DAM_HOUR_X_TICKS}
                  allowDecimals={false}
                  padding={{ left: 0, right: 0 }}
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
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
                  tick={{ fill: 'rgba(255,248,252,0.72)', fontSize: 10 }}
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
                {!damChartMobile && damSeriesVisible.soc ? (
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
                {!damChartMobile && damSeriesVisible.hz ? (
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
                <ReferenceLine y={0} stroke="rgba(255,248,252,0.35)" strokeDasharray="4 4" />
                <Tooltip
                  separator=": "
                  contentStyle={{
                    background: 'rgba(24, 8, 32, 0.94)',
                    border: '1px solid rgba(252, 1, 155, 0.35)',
                    borderRadius: 10,
                    color: '#fff',
                  }}
                  labelStyle={{ color: 'rgba(255, 248, 252, 0.95)' }}
                  itemStyle={{ color: 'rgba(255, 248, 252, 0.95)' }}
                  formatter={(value, name, item) => {
                    if (value == null || value === '') return ['—', name];
                    const kw = Number(value);
                    const tag = kw > 0 ? t('damGridImportTag') : kw < 0 ? t('damGridExportTag') : '';
                    const gridPayload = item?.payload ?? item;
                    const live = gridPayload?.gridKwLive ? ` — ${t('damGridLiveTag')}` : '';
                    const fromLoad = gridPayload?.gridKwFromLoad ? ` (${t('damGridFromLoadTag')})` : '';
                    const unit = t('damEnergyKwhUnit');
                    const s = tag ? `${fmt1.format(kw)} ${unit} (${tag})` : `${fmt1.format(kw)} ${unit}`;
                    const gridLabel = t('damSeriesGrid');
                    return [`${s}${fromLoad}${live}`, gridLabel];
                  }}
                  labelFormatter={hour => `${t('damHourTooltip')} ${hour}`}
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
                      <circle cx={cx} cy={cy} r={5.5} fill={fill} stroke="rgba(255,255,255,0.45)" strokeWidth={1.2} />
                    );
                  }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        ) : null}

        {!loading && hasChart && effectiveInverterSn ? (
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
            <ResponsiveContainer width="100%" height={gridBarH}>
              <ComposedChart data={rows} syncId="dam-day" margin={damComposedChartMargin} isAnimationActive={false}>
                <CartesianGrid stroke="rgba(252, 1, 155, 0.08)" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="hour"
                  type="number"
                  domain={DAM_X_AXIS_DOMAIN}
                  ticks={DAM_HOUR_X_TICKS}
                  allowDecimals={false}
                  padding={{ left: 0, right: 0 }}
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
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
                  tick={{ fill: 'rgba(255,248,252,0.72)', fontSize: 10 }}
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
                {!damChartMobile && damSeriesVisible.soc ? (
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
                {!damChartMobile && damSeriesVisible.hz ? (
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
                <ReferenceLine y={0} stroke="rgba(255,248,252,0.35)" strokeDasharray="4 4" />
                <Tooltip
                  separator=": "
                  contentStyle={{
                    background: 'rgba(24, 8, 32, 0.94)',
                    border: '1px solid rgba(252, 1, 155, 0.35)',
                    borderRadius: 10,
                    color: '#fff',
                  }}
                  labelStyle={{ color: 'rgba(255, 248, 252, 0.95)' }}
                  itemStyle={{ color: 'rgba(255, 248, 252, 0.95)' }}
                  formatter={(value, name, item) => {
                    if (value == null || value === '') return ['—', name];
                    const num = Number(value);
                    const payload = item?.payload ?? item;
                    const live = payload?.pvLoadLive ? ` — ${t('damPvLoadLiveTag')}` : '';
                    if (name === t('damSeriesPvKwh')) {
                      return [`${fmt1.format(num)} kWh${live}`, name];
                    }
                    if (name === t('damSeriesLoadKwh')) {
                      const mag = Number.isFinite(num) ? Math.abs(num) : null;
                      return [mag != null ? `${fmt1.format(mag)} kWh${live}` : '—', name];
                    }
                    return [`${fmt1.format(num)}`, name];
                  }}
                  labelFormatter={hour => `${t('damHourTooltip')} ${hour}`}
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
                      <circle cx={cx} cy={cy} r={5} fill="#22c55e" stroke="rgba(255,255,255,0.45)" strokeWidth={1.2} />
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
                      <circle cx={cx} cy={cy} r={5} fill="#fb923c" stroke="rgba(255,255,255,0.45)" strokeWidth={1.2} />
                    );
                  }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        ) : null}

        {damMarket === 'oree' && (!indexesPayload || indexesPayload.configured !== false) ? (
          <div className="dam-indexes-wrap">
            <h3 className="dam-indexes-title">{t('damIndexesTitle')}</h3>
            {damIndexChart.tradeDay ? (
              <p className="dam-indexes-trade-day">
                {t('damIndexesTradeDay')}: {damIndexChart.tradeDay}
              </p>
            ) : null}
            <div className="dam-base-index-block">
              <h4 className="dam-base-index-heading">{t('damBaseIndexHeading')}</h4>
              <div className="dam-compare-row dam-base-index-compare-row">
                <select
                  id={`dam-base-index-compare-${variant}`}
                  className="pf-lang-select dam-compare-select"
                  aria-label={t('damBaseIndexCompareAria')}
                  value={baseIndexCompareMode}
                  onChange={e => setBaseIndexCompareMode(e.target.value)}
                >
                  <option value={DAM_COMPARE_DAY}>{t('damCompareOptionDay')}</option>
                  <option value={DAM_COMPARE_MONTH}>{t('damCompareOptionMonth')}</option>
                </select>
                <div className="dam-trend-line" aria-live="polite">
                  {baseIndexCompareLoading || indexesLoading ? (
                    <span className="dam-trend-line--muted">…</span>
                  ) : baseIndexTrendPct == null ? (
                    <span className="dam-trend-line--muted">—</span>
                  ) : (
                    <span className={baseIndexTrendPct >= 0 ? 'dam-trend-line--up' : 'dam-trend-line--down'}>
                      {fmtPct.format(baseIndexTrendPct)}%
                    </span>
                  )}
                </div>
              </div>
            </div>
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
                    <CartesianGrid stroke="rgba(252, 1, 155, 0.1)" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="label"
                      tick={{ fill: 'rgba(255,248,252,0.78)', fontSize: 11 }}
                      tickLine={false}
                      axisLine={{ stroke: 'rgba(252, 1, 155, 0.25)' }}
                    />
                    <YAxis
                      width={72}
                      tick={{ fill: 'rgba(255,248,252,0.85)', fontSize: 11 }}
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
                      cursor={{ fill: 'rgba(252, 1, 155, 0.06)' }}
                      wrapperClassName="dam-indexes-tooltip-wrap"
                      contentStyle={{
                        background: 'rgba(24, 8, 32, 0.96)',
                        border: '1px solid rgba(252, 1, 155, 0.35)',
                        borderRadius: 10,
                        color: '#ffffff',
                      }}
                      labelStyle={{ color: '#ffffff', fontWeight: 600 }}
                      itemStyle={{ color: '#ffffff' }}
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
                    <Bar dataKey="priceUahKwh" name={t('damIndexesTooltipPrice')} radius={[8, 8, 0, 0]} maxBarSize={56}>
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

        {damMarket === 'oree' ? (
          <section className="dam-oree-embed" aria-labelledby="dam-oree-embed-title">
            <div className="dam-oree-embed-header">
              <h3 id="dam-oree-embed-title" className="dam-oree-embed-title">
                {t('damOreeWebsiteLink')}
              </h3>
            </div>
            <div className="dam-oree-embed-frame-wrap">
              <iframe
                title={t('damOreeEmbedIframeTitle')}
                src={OREE_DAM_CHART_URL}
                className="dam-oree-embed-iframe"
                referrerPolicy="no-referrer-when-downgrade"
              />
            </div>
          </section>
        ) : null}
      </div>
    </>
  );
}
