import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  BINANCE_MINER_URL,
  EV_START_URL,
  SITE_220KM_HOME,
  FLOW_DOT_MOTION_DUR,
  computeSimulatedSources,
  computeWideGeometry,
  edgeInsetPx,
  flowMotionPath,
  formatPower,
} from './powerFlowEngine';
import DamChartPanel from './DamChartPanel';
import RdnConsultationCallback from './RdnConsultationCallback';
import DeyeInverterMessengerModal from './DeyeInverterMessengerModal';
import PeakExportHourlyChartModal from './PeakExportHourlyChartModal';
import MonthlyRetailTariffChartModal from './MonthlyRetailTariffChartModal';
import GridBalancingChartModal from './GridBalancingChartModal';
import RoiStackStatistics from './RoiStackStatistics';
import { KwhCalibrationProvider, useKwhCalibration } from './KwhCalibrationContext';
import { VYRIY_EMS_LOGO_SRC } from './vyriyEmsLogo';
import PartnerHubLogo from './PartnerHubLogo';
import { DEYE_FLOW_BALANCE_PV_FACTOR, usesDeyeFlowBalance } from './deyeFlowBalanceSites';
import { inverterSelectShortLabel, parseEvPortStationNumber } from './deyeInverterDisplay';
import { clearInverterPinCache, readCachedInverterPin, rememberInverterPin } from './deyeInverterPinCache';
import {
  ESS_PREFIX_AC_EV,
  ESS_PREFIX_DEYE,
  ESS_PREFIX_DC_EV,
  ESS_PREFIX_HUAWEI,
  evPortsAcdcFromProvider,
  normalizeEssSelectionValue,
  parseEssSelection,
} from './essSelection';
import PfScrollNumber from './PfScrollNumber';
import PortStickerQrImage from './PortStickerQrImage';
import KioskFleetGenConsChart from './KioskFleetGenConsChart';
import { openEmsUrlWithoutKiosk, openEmsUrlWithKiosk } from './openEmsKiosk';
import { pageShareUrlFromWindow } from './sharePageQr';
import { useMinWidth } from './useMinWidth';
import { useScreenWakeLock } from './useScreenWakeLock';
import './power-flow.css';
import './dam-chart.css';
import './openEmsKiosk.css';
import { useOpenEmsSeo } from './useOpenEmsSeo';

const INVERTER_STORAGE = 'pf-deye-inverter';

/** Wide viewport — kiosk entry button (aligned with B2B graphView=1 at 992px). */
const KIOSK_WIDE_MIN_PX = 992;

/** Huawei Northbound thirdData — strict rate limits (failCode 407 if polled too often). */
const HUAWEI_NORTHBOUND_POLL_MS = 210_000;

/** Aside QR wraps this URL (B12 uncrewed systems unit). */
const QR_SUPPORT_URL = 'https://b12.army/';

/** Open EMS repository (open source). */
const OPEN_EMS_GITHUB_URL = 'https://github.com/220-organization/open-ems';

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  if (!base) return path;
  return `${base}${path}`;
}

/** Kyiv calendar date YYYY-MM-DD for OREE DAM trade day (aligned with DamChartPanel /api/dam/chart-day). */
function kyivCalendarIsoForDam() {
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

/** Kyiv local wall-clock hour 0–23 (Europe/Kyiv); indexes hourlyPriceDamUahPerKwh[0..23] (period 1..24). */
function kyivWallHour0to23() {
  try {
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

function EvCarMark({ className = '' }) {
  return (
    <svg
      className={className}
      viewBox="0 0 96 64"
      aria-hidden="true"
      focusable="false"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="pfEvStationBody" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ff5fc8" />
          <stop offset="55%" stopColor="#fc019b" />
          <stop offset="100%" stopColor="#7a0566" />
        </linearGradient>
        {/* 220-km.com brand: vivid magenta body */}
        <linearGradient id="pfEvCarBody" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ff4db8" />
          <stop offset="48%" stopColor="#fc019b" />
          <stop offset="100%" stopColor="#82004f" />
        </linearGradient>
        <linearGradient id="pfEvGlass" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#1e083a" />
          <stop offset="100%" stopColor="#09011a" />
        </linearGradient>
      </defs>

      {/* Ground shadows */}
      <ellipse cx="62" cy="57.5" rx="32" ry="1.7" fill="rgba(252,1,155,0.2)" />
      <ellipse cx="13" cy="57.5" rx="11" ry="1.3" fill="rgba(252,1,155,0.14)" />

      {/* === Fast charging station === */}
      <g className="pf-node-icon__ev-station">
        <rect x="2" y="55" width="20" height="2.5" rx="1.25" fill="#2d0336" />
        <rect x="6" y="14" width="14" height="41" rx="3.5" fill="url(#pfEvStationBody)" />
        <rect x="6" y="14" width="14" height="3.5" rx="1.75" fill="rgba(255,255,255,0.25)" />
        <rect x="7" y="20" width="1.2" height="31" rx="0.6" fill="rgba(255,255,255,0.25)" />
        <rect x="8.5" y="20" width="9" height="11.5" rx="1.8" fill="#0a0118" />
        <rect
          x="9"
          y="20.5"
          width="8"
          height="10.5"
          rx="1.3"
          fill="none"
          stroke="rgba(255,127,222,0.4)"
          strokeWidth="0.45"
        />
        <path d="M13.5 22.5 L11 26.5 L13.1 26.5 L11.4 29.6 L14.7 25.4 L12.7 25.4 L14.2 22.5 Z" fill="#fff5fb" />
        <circle cx="13" cy="35" r="1.1" fill="#22ff88">
          <animate attributeName="opacity" values="1;0.3;1" dur="1.6s" repeatCount="indefinite" />
        </circle>
        <rect x="9" y="39" width="8" height="1.5" rx="0.75" fill="rgba(255,255,255,0.45)" />
        <rect x="9" y="41.5" width="5.5" height="1" rx="0.5" fill="rgba(255,255,255,0.28)" />
        <rect x="19.5" y="28.5" width="2.5" height="4.5" rx="0.9" fill="#2d0336" />
      </g>

      {/* === Charging cable === */}
      <path d="M22 30.5 C28 30 33 33 38.5 34" stroke="#2d0336" strokeWidth="2.8" fill="none" strokeLinecap="round" />
      <path
        d="M22 30.5 C28 30 33 33 38.5 34"
        stroke="#fc019b"
        strokeWidth="1.4"
        fill="none"
        strokeLinecap="round"
        opacity="0.75"
      />
      <path className="pf-node-icon__ev-flow-line" d="M22 30.5 C28 30 33 33 38.5 34" />
      <circle className="pf-node-icon__ev-flow-dot" r="1.4" fill="#ffffff">
        <animateMotion dur="1.4s" repeatCount="indefinite" path="M 22 30.5 C 28 30 33 33 38.5 34" />
      </circle>
      <circle className="pf-node-icon__ev-flow-dot" r="0.9" fill="#f9a8ef" opacity="0.7">
        <animateMotion dur="1.4s" begin="0.47s" repeatCount="indefinite" path="M 22 30.5 C 28 30 33 33 38.5 34" />
      </circle>

      {/* === Nissan Leaf silhouette (facing right) === */}
      {/* Body — Leaf characteristic tall cabin, rounded nose, sloping hatch */}
      <path
        d="M32 46
           L32 39
           C32 35 34.5 31 38.5 30
           L41 29.5
           C43.2 29 45 27.5 46 25.5
           L48.4 21
           C49.6 18.8 52 17.5 54.5 17.5
           L73.5 17.5
           C77 17.5 80.4 19.5 82.2 22.8
           L84.6 27.5
           C85.3 28.9 86.4 30 87.8 30.6
           L90.2 31.6
           C91.6 32.2 92.5 33.6 92.5 35.2
           L92.5 46 Z"
        fill="url(#pfEvCarBody)"
      />

      {/* Windows — one clean greenhouse shape */}
      <path
        d="M45.5 25.5
           L48 21.2
           C49.2 19.1 51.5 19.5 54 19.5
           L73.5 19.5
           C76.6 19.5 79.5 21.4 81 24.3
           L83.4 29.5
           L45.5 29.5 Z"
        fill="url(#pfEvGlass)"
      />
      {/* Window glare */}
      <path d="M46.5 26 L49 21.5 L57.5 21.5 L54 29 L46.5 29 Z" fill="rgba(255,255,255,0.09)" />

      {/* B-pillar */}
      <rect x="66" y="19.5" width="1.4" height="10" rx="0.7" fill="rgba(0,0,0,0.55)" />

      {/* Body shoulder crease (Leaf character line) */}
      <path d="M35 39 L91 39" stroke="rgba(0,0,0,0.2)" strokeWidth="0.6" strokeLinecap="round" />

      {/* Rear tail-light strip */}
      <rect x="31.8" y="35.5" width="2" height="7" rx="0.9" fill="#fc019b" opacity="0.95" />
      <rect x="31.8" y="35.5" width="2" height="7" rx="0.9" fill="rgba(255,180,240,0.4)" />

      {/* Front DRL — Leaf "boomerang" daytime running light */}
      <path
        d="M89.5 33 L92.5 36.5 L91.5 40.5"
        stroke="#fffbe0"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Charging port inlet (rear quarter) */}
      <rect x="37" y="32.5" width="3.2" height="3" rx="0.7" fill="rgba(255,245,251,0.9)" />
      <circle cx="38.6" cy="34" r="0.7" fill="#fc019b" />

      {/* Large 220-km brand on car body centre */}
      <text
        x="62"
        y="40"
        textAnchor="middle"
        fontSize="7"
        fontWeight="900"
        fontFamily="Arial,Helvetica,sans-serif"
        letterSpacing="-0.2"
        fill="#ffffff"
        opacity="0.95"
      >
        220-km
      </text>

      {/* === Wheels === */}
      {/* Rear */}
      <circle cx="43" cy="48" r="6.5" fill="#0d0222" />
      <circle cx="43" cy="48" r="4.4" fill="#1a0830" />
      <circle cx="43" cy="48" r="2.9" fill="#28103e" />
      <g stroke="#fc019b" strokeWidth="0.55" strokeLinecap="round" opacity="0.8">
        <line x1="43" y1="45.2" x2="43" y2="50.8" />
        <line x1="40.2" y1="48" x2="45.8" y2="48" />
        <line x1="41.1" y1="46" x2="44.9" y2="50" />
        <line x1="41.1" y1="50" x2="44.9" y2="46" />
      </g>
      <circle cx="43" cy="48" r="0.9" fill="#fc019b" />
      {/* Front */}
      <circle cx="80" cy="48" r="6.5" fill="#0d0222" />
      <circle cx="80" cy="48" r="4.4" fill="#1a0830" />
      <circle cx="80" cy="48" r="2.9" fill="#28103e" />
      <g stroke="#fc019b" strokeWidth="0.55" strokeLinecap="round" opacity="0.8">
        <line x1="80" y1="45.2" x2="80" y2="50.8" />
        <line x1="77.2" y1="48" x2="82.8" y2="48" />
        <line x1="78.1" y1="46" x2="81.9" y2="50" />
        <line x1="78.1" y1="50" x2="81.9" y2="46" />
      </g>
      <circle cx="80" cy="48" r="0.9" fill="#fc019b" />
    </svg>
  );
}

/**
 * Ukrainian month forms — `Intl` month: long is nominative only; tariff copy needs accusative (after «за») / instrumental.
 * Index 1 = January … 12 = December.
 */
const UK_MONTH_ACCUSATIVE = Object.freeze([
  '',
  'січень',
  'лютий',
  'березень',
  'квітень',
  'травень',
  'червень',
  'липень',
  'серпень',
  'вересень',
  'жовтень',
  'листопад',
  'грудень',
]);
const UK_MONTH_INSTRUMENTAL = Object.freeze([
  '',
  'січнем',
  'лютим',
  'березнем',
  'квітнем',
  'травнем',
  'червнем',
  'липнем',
  'серпнем',
  'вереснем',
  'жовтнем',
  'листопадом',
  'груднем',
]);
/** Short month labels for arbitrage MoM (after «за»). Index 1 = January … 12 = December. */
const UK_MONTH_SHORT = Object.freeze([
  '',
  'січ.',
  'лют.',
  'бер.',
  'квіт.',
  'трав.',
  'черв.',
  'лип.',
  'серп.',
  'вер.',
  'жовт.',
  'лист.',
  'груд.',
]);

/** UI retail tariff from DAM average: +3.5 UAH/kWh (distribution / rozpodil) then +20% (VAT). */
const LANDING_TARIFF_DISTRIBUTION_UAH_PER_KWH = 3.5;
const LANDING_TARIFF_VAT_MULTIPLIER = 1.2;

/** Landing export block: metric dropdown + counter (fleet or one inverter; default: total export). */
const LANDING_EXPORT_METRIC = Object.freeze({
  GRID_BALANCING: 'grid_balancing',
  MONTHLY_RATES: 'monthly_rates',
  PEAK: 'peak',
  MANUAL: 'manual',
  TOTAL: 'total',
  ARBITRAGE: 'arbitrage',
  LOST_SOLAR_7D: 'lost_solar_7d',
});

const LANDING_EXPORT_METRIC_VALUES = new Set(Object.values(LANDING_EXPORT_METRIC));

/** Landing export metric appears in the selector only when its kWh / UAH counter is > 0. */
function landingExportMetricHasPositiveValue(landingTotals, metric) {
  if (!landingTotals?.ok) return false;
  switch (metric) {
    case LANDING_EXPORT_METRIC.PEAK: {
      const v = landingTotals.peakDamLastSession?.exportSessionKwh;
      return Number.isFinite(Number(v)) && Number(v) > 0;
    }
    case LANDING_EXPORT_METRIC.MANUAL: {
      const v = landingTotals.manualDischargeLastSession?.exportSessionKwh;
      return Number.isFinite(Number(v)) && Number(v) > 0;
    }
    case LANDING_EXPORT_METRIC.TOTAL: {
      const v = landingTotals.totalExportKwh;
      return Number.isFinite(Number(v)) && Number(v) > 0;
    }
    case LANDING_EXPORT_METRIC.ARBITRAGE: {
      const v = landingTotals.arbitrageRevenueUah;
      return Number.isFinite(Number(v)) && Number(v) > 0;
    }
    case LANDING_EXPORT_METRIC.LOST_SOLAR_7D: {
      const v = landingTotals.lostSolarKwhTotal;
      return Number.isFinite(Number(v)) && Number(v) > 0;
    }
    case LANDING_EXPORT_METRIC.GRID_BALANCING: {
      const v = landingTotals.gridBalancing?.balancingPctMtd;
      return landingTotals.gridBalancing?.configured !== false && Number.isFinite(Number(v));
    }
    default:
      return true;
  }
}

function preferredLandingExportMetric(offers) {
  if (offers?.gridBalancing) return LANDING_EXPORT_METRIC.GRID_BALANCING;
  return LANDING_EXPORT_METRIC.MONTHLY_RATES;
}

/** Query keys for landing export metric (values: peak | manual | total | arbitrage | lost_solar_7d). */
const LANDING_EXPORT_METRIC_URL_KEYS = ['exportMetric', 'landingExport'];

/** One preference for the whole UI session — survives inverter / station changes (still normalized for Huawei / fleet). */
const LANDING_EXPORT_METRIC_STORAGE_GLOBAL = 'pf-landing-export-metric-v5-global';
const LANDING_EXPORT_METRIC_STORAGE_LEGACY_KEYS = [
  'pf-landing-export-metric-v4-global',
  'pf-landing-export-metric-v3-global',
];

/** Only these metrics are restored from storage; grid balancing is always the default. */
const PERSISTED_LANDING_EXPORT_METRICS = new Set([
  LANDING_EXPORT_METRIC.PEAK,
  LANDING_EXPORT_METRIC.MANUAL,
  LANDING_EXPORT_METRIC.TOTAL,
  LANDING_EXPORT_METRIC.ARBITRAGE,
  LANDING_EXPORT_METRIC.LOST_SOLAR_7D,
]);

/** Grid balancing is the product default; do not restore monthly_rates from storage. */
function landingExportMetricFromStoredRaw(raw) {
  if (raw === LANDING_EXPORT_METRIC.MONTHLY_RATES) return LANDING_EXPORT_METRIC.GRID_BALANCING;
  return raw;
}

function defaultLandingExportMetric() {
  return LANDING_EXPORT_METRIC.GRID_BALANCING;
}
function normalizeLandingExportMetricForContext(metric, inverterSn, huaweiStationCode, evPortsAcdc) {
  if (!LANDING_EXPORT_METRIC_VALUES.has(metric)) return LANDING_EXPORT_METRIC.GRID_BALANCING;
  const ev = evPortsAcdc === 'dc' || evPortsAcdc === 'ac' ? evPortsAcdc : '';
  if (ev) {
    if (metric !== LANDING_EXPORT_METRIC.MONTHLY_RATES) {
      return LANDING_EXPORT_METRIC.MONTHLY_RATES;
    }
    return metric;
  }
  const h = String(huaweiStationCode || '').trim();
  if (
    h &&
    (metric === LANDING_EXPORT_METRIC.PEAK ||
      metric === LANDING_EXPORT_METRIC.MANUAL ||
      metric === LANDING_EXPORT_METRIC.ARBITRAGE ||
      metric === LANDING_EXPORT_METRIC.LOST_SOLAR_7D)
  ) {
    return LANDING_EXPORT_METRIC.GRID_BALANCING;
  }
  const s = String(inverterSn || '').trim();
  if (!s && !h && metric === LANDING_EXPORT_METRIC.LOST_SOLAR_7D) {
    return LANDING_EXPORT_METRIC.GRID_BALANCING;
  }
  return metric;
}

function readLandingExportMetricFromUrl(inverterSn, huaweiStationCode, evPortsAcdc) {
  try {
    const u = new URLSearchParams(window.location.search);
    let raw = '';
    for (const k of LANDING_EXPORT_METRIC_URL_KEYS) {
      const v = u.get(k);
      if (v != null && String(v).trim()) {
        raw = String(v).trim().toLowerCase();
        break;
      }
    }
    if (!raw || !LANDING_EXPORT_METRIC_VALUES.has(raw)) return null;
    return normalizeLandingExportMetricForContext(raw, inverterSn, huaweiStationCode, evPortsAcdc);
  } catch {
    return null;
  }
}

function replaceLandingExportMetricInUrl(metric) {
  try {
    const u = new URL(window.location.href);
    u.searchParams.delete('landingExport');
    if (metric === LANDING_EXPORT_METRIC.TOTAL || metric === LANDING_EXPORT_METRIC.GRID_BALANCING) {
      u.searchParams.delete('exportMetric');
    } else {
      u.searchParams.set('exportMetric', metric);
    }
    window.history.replaceState({}, '', u);
  } catch {
    /* ignore */
  }
}

function readStoredLandingExportMetric(inverterSn, huaweiStationCode) {
  try {
    let raw = localStorage.getItem(LANDING_EXPORT_METRIC_STORAGE_GLOBAL);
    if (!raw) {
      for (const legacyKey of LANDING_EXPORT_METRIC_STORAGE_LEGACY_KEYS) {
        const prev = localStorage.getItem(legacyKey);
        if (prev && LANDING_EXPORT_METRIC_VALUES.has(prev)) {
          raw = prev;
          break;
        }
      }
      const s = String(inverterSn || '').trim();
      const h = String(huaweiStationCode || '').trim();
      const legacyDevice = h
        ? localStorage.getItem(`pf-landing-export-metric-v1-huawei-${h}`)
        : s
          ? localStorage.getItem(`pf-landing-export-metric-v1-${s}`)
          : null;
      const legacyFleet = localStorage.getItem('pf-landing-export-metric-v1-fleet');
      raw = raw || legacyDevice || legacyFleet || '';
    }
    if (raw && LANDING_EXPORT_METRIC_VALUES.has(raw)) {
      const metric = normalizeLandingExportMetricForContext(
        landingExportMetricFromStoredRaw(raw),
        inverterSn,
        huaweiStationCode,
        null
      );
      if (PERSISTED_LANDING_EXPORT_METRICS.has(metric)) {
        return metric;
      }
      try {
        localStorage.setItem(LANDING_EXPORT_METRIC_STORAGE_GLOBAL, defaultLandingExportMetric());
      } catch {
        /* ignore */
      }
    }
  } catch {
    /* ignore */
  }
  return defaultLandingExportMetric();
}

function writeStoredLandingExportMetric(inverterSn, huaweiStationCode, value) {
  if (!LANDING_EXPORT_METRIC_VALUES.has(value)) return;
  try {
    localStorage.setItem(LANDING_EXPORT_METRIC_STORAGE_GLOBAL, value);
  } catch {
    /* ignore */
  }
}

/** First known SoC for a merged Deye row (representative, then other cluster serials). */
function firstFiniteSocForDeyeRow(row, socBySn) {
  if (!row || !socBySn) return null;
  const rep = String(row.representativeSn || '').trim();
  const sns = Array.isArray(row.clusterSns) ? row.clusterSns.map(s => String(s || '').trim()).filter(Boolean) : [];
  const order = rep ? [rep, ...sns.filter(s => s !== rep)] : sns;
  for (const s of order) {
    const v = socBySn[s];
    if (v != null && Number.isFinite(Number(v))) return Number(v);
  }
  return null;
}

/** Append localized unit for landing export counters (skip placeholders). */
function formatLandingKwhCounterText(displayText, t) {
  const s = displayText == null ? '' : String(displayText).trim();
  if (!s || s === '—' || s === '…') return s || '—';
  return `${s} ${t('powerFlowLandingKwhUnit')}`;
}

/**
 * Total export counter: plain sum from API ``totalExportKwh`` (all 5‑min samples with grid export).
 * Not derived from peak-DAM or manual-discharge session rows.
 */
function formatLandingTotalExportSamplesKwh(totalExportKwh, bcp47) {
  const fmtKwh = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 0 });
  if (totalExportKwh != null && Number.isFinite(Number(totalExportKwh))) {
    return fmtKwh.format(Number(totalExportKwh));
  }
  return '—';
}

/** kWh suffix for export metrics; currency values are already formatted via Intl. */
function formatLandingMetricCounterText(displayText, t, valueIsCurrency) {
  if (valueIsCurrency) {
    const s = displayText == null ? '' : String(displayText).trim();
    if (!s || s === '—' || s === '…') return s || '—';
    return s;
  }
  return formatLandingKwhCounterText(displayText, t);
}

function landingRetailUahPerKwh(damAvgUahPerKwh) {
  const x = Number(damAvgUahPerKwh);
  if (!Number.isFinite(x)) return null;
  return (x + LANDING_TARIFF_DISTRIBUTION_UAH_PER_KWH) * LANDING_TARIFF_VAT_MULTIPLIER;
}

/** Kyiv calendar month label for monthly-rates pill: MM.yy (e.g. 05.26). */
function formatKyivMonthYearMmYy(year, month) {
  const y = Number(year);
  const m = Number(month);
  if (!Number.isFinite(y) || !Number.isFinite(m) || m < 1 || m > 12) return '';
  const yy = ((y % 100) + 100) % 100;
  return `${String(m).padStart(2, '0')}.${String(yy).padStart(2, '0')}`;
}

/** MoM % for displayed retail vs previous calendar month (device import-weighted or fleet DAM). */
function landingMonthlyRatesMom(dam, retailCurrent, bcp47, isDeviceScope) {
  if (retailCurrent == null || !Number.isFinite(retailCurrent)) {
    return null;
  }
  let retailPrev = null;
  if (isDeviceScope) {
    const prevW = dam?.prevMonthDeviceImportWeightedAvgDamUahPerKwh;
    if (prevW != null && Number.isFinite(Number(prevW))) {
      retailPrev = landingRetailUahPerKwh(Number(prevW));
    }
  }
  if (retailPrev == null && dam?.prevAvgUahPerKwh != null) {
    retailPrev = landingRetailUahPerKwh(dam.prevAvgUahPerKwh);
  }
  if (retailPrev == null || retailPrev <= 1e-6) return null;
  const pct = ((retailCurrent - retailPrev) / retailPrev) * 100;
  if (!Number.isFinite(pct)) return null;
  const fmtPct = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  const deltaStr = `${pct > 0 ? '+' : ''}${fmtPct.format(pct)}%`;
  let prevMonthLabel = '';
  const prevStart = dam.prevMonthStart;
  if (prevStart) {
    const [py, pm] = prevStart.split('-').map(Number);
    prevMonthLabel = formatKyivMonthYearMmYy(py, pm);
  }
  return { deltaPct: pct, deltaStr, prevMonthLabel };
}

/** % vs average calendar DAM (device: retail vs DAM+dist+VAT; fleet: retail vs raw DAM UAH/kWh). */
function landingMonthlyRatesVsAvgDam(dam, retailCurrent, bcp47, isDeviceScope) {
  const damAvg = dam?.currentAvgUahPerKwh;
  if (damAvg == null || !Number.isFinite(Number(damAvg)) || retailCurrent == null) return null;
  const baseline = isDeviceScope ? landingRetailUahPerKwh(Number(damAvg)) : Number(damAvg);
  if (baseline == null || !Number.isFinite(baseline) || baseline <= 1e-6) return null;
  const pct = ((retailCurrent - baseline) / baseline) * 100;
  if (!Number.isFinite(pct) || Math.abs(pct) < 0.05) return null;
  const fmtPct = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  const deltaStr = `${pct > 0 ? '+' : ''}${fmtPct.format(pct)}`;
  return { deltaPct: pct, deltaStr };
}

/** Retail tariff for landing monthly-rates (device import-weighted or fleet DAM average). */
function landingMonthlyRatesRetailFromTotals(landingTotals) {
  if (!landingTotals?.ok) return null;
  const dam = landingTotals.dam;
  if (!dam?.configured || !dam.currentMonthStart) return null;
  const isDeviceScope =
    landingTotals.exportScope === 'device' ||
    landingTotals.exportScope === 'huawei' ||
    landingTotals.exportScope === 'ev_ports';
  let damAvg = dam.currentAvgUahPerKwh;
  const personal = dam.currentMonthDeviceImportWeightedAvgDamUahPerKwhMtd;
  if (isDeviceScope && personal != null && Number.isFinite(Number(personal))) {
    damAvg = Number(personal);
  }
  const retail = landingRetailUahPerKwh(damAvg);
  if (retail == null || !Number.isFinite(retail)) return null;
  return { dam, retail, isDeviceScope };
}

/** One-line Grid Balancing MTD for landing (under metric when an inverter is selected). */
function landingGridBalancingSupplement(landingTotals, bcp47) {
  const gb = landingTotals?.gridBalancing;
  if (!landingTotals?.ok || gb?.configured === false) return null;
  const pct = gb?.balancingPctMtd;
  const n = pct != null ? Number(pct) : null;
  if (n == null || !Number.isFinite(n)) return null;
  const fmtPct = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  return {
    pctStr: `${fmtPct.format(n)}%`,
    tier: landingGridBalancingScoreTier(n),
  };
}

/** Device tariff vs calendar DAM retail (Ukraine average) for landing monthly-rates supplement. */
function landingMonthlyRatesTariffVsUkraineSupplement(landingTotals, bcp47) {
  const ctx = landingMonthlyRatesRetailFromTotals(landingTotals);
  if (!ctx?.isDeviceScope) return null;
  const vs = landingMonthlyRatesVsAvgDam(ctx.dam, ctx.retail, bcp47, true);
  const fmtPct = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  if (vs == null) {
    return { kind: 'equal' };
  }
  const deltaStr = fmtPct.format(Math.abs(vs.deltaPct));
  if (vs.deltaPct > 0) {
    return { kind: 'more', deltaPct: vs.deltaPct, deltaStr };
  }
  return { kind: 'less', deltaPct: vs.deltaPct, deltaStr };
}

const LANDING_MONTHLY_RATES_WRAP_CLASS =
  'pf-landing-totals__counter-wrap pf-landing-totals__counter-wrap--monthly-rates';
const LANDING_MONTHLY_RATES_COUNTER_CLASS = 'pf-landing-totals__counter pf-landing-totals__counter--monthly-rates';

/** Counter model for landing «Monthly rates» — rate+₴ in pill; month, unit, MoM outside. */
function formatLandingMonthlyRatesMetric(landingTotals, bcp47, t) {
  const unitSuffix = t('powerFlowLandingMonthlyRatesUnit');
  const base = {
    monthlyRatesLayout: true,
    unitSuffix,
    wrapClass: LANDING_MONTHLY_RATES_WRAP_CLASS,
    counterClass: LANDING_MONTHLY_RATES_COUNTER_CLASS,
    valueIsCurrency: true,
  };
  if (!landingTotals?.ok) {
    return {
      ...base,
      monthLabel: '',
      rateInBox: '…',
      title: t('powerFlowLandingMonthlyRatesHint'),
      counterAria: t('powerFlowLandingMonthlyRatesHint'),
      monthlyRatesMom: null,
    };
  }
  const dam = landingTotals.dam;
  const fmtRate = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 2, minimumFractionDigits: 2 });
  if (!dam?.configured || !dam.currentMonthStart) {
    return {
      ...base,
      monthLabel: '',
      rateInBox: '—',
      title: t('powerFlowLandingMonthlyRatesHint'),
      counterAria: t('powerFlowLandingMonthlyRatesHint'),
      monthlyRatesMom: null,
    };
  }
  const [cy, cm] = dam.currentMonthStart.split('-').map(Number);
  const curMonth = formatKyivMonthYearMmYy(cy, cm);
  const isDeviceScope =
    landingTotals.exportScope === 'device' ||
    landingTotals.exportScope === 'huawei' ||
    landingTotals.exportScope === 'ev_ports';
  let damAvg = dam.currentAvgUahPerKwh;
  const personal = dam.currentMonthDeviceImportWeightedAvgDamUahPerKwhMtd;
  if (isDeviceScope && personal != null && Number.isFinite(Number(personal))) {
    damAvg = Number(personal);
  } else if (landingTotals.exportScope === 'ev_ports') {
    return {
      ...base,
      monthLabel: curMonth,
      rateInBox: '—',
      title: t('powerFlowLandingMonthlyRatesHintEvPorts'),
      counterAria: t('powerFlowLandingMonthlyRatesHintEvPorts'),
      monthlyRatesMom: null,
    };
  }
  const retail = landingRetailUahPerKwh(damAvg);
  const rate = retail != null ? fmtRate.format(retail) : '—';
  const monthlyRatesMom = retail != null ? landingMonthlyRatesMom(dam, retail, bcp47, isDeviceScope) : null;
  let hintKey = isDeviceScope ? 'powerFlowLandingMonthlyRatesHintDevice' : 'powerFlowLandingMonthlyRatesHint';
  if (landingTotals.exportScope === 'ev_ports') {
    hintKey = 'powerFlowLandingMonthlyRatesHintEvPorts';
  }
  return {
    ...base,
    monthLabel: curMonth,
    rateInBox: rate,
    title: t(hintKey),
    counterAria: t('powerFlowLandingMonthlyRatesCounterAria', { month: curMonth, rate }),
    monthlyRatesMom,
  };
}

/** Month label + neon pill (rate ₴) + unit suffix + optional MoM outside the pill. */
function LandingMonthlyRatesDisplay({ display, t, asButton, chartAria, onChartOpen }) {
  const rateText = t('powerFlowLandingMonthlyRatesCounterInBox', {
    rate: display.rateInBox ?? '—',
  });
  const inBox = (
    <div className="pf-landing-totals__counter-scroll">
      <PfScrollNumber
        direction="up"
        duration={0.32}
        ease={[0.33, 0, 0.2, 1]}
        className={display.counterClass}
        numberStyle={{ letterSpacing: '0.03em' }}
      >
        {formatLandingMetricCounterText(rateText, t, true)}
      </PfScrollNumber>
    </div>
  );
  const wrapClass = asButton
    ? `${display.wrapClass} pf-landing-totals__counter-wrap--export-chart-trigger`
    : display.wrapClass;
  const aria = display.counterAria || display.title || undefined;
  const box = asButton ? (
    <button type="button" className={wrapClass} aria-label={chartAria || aria} onClick={onChartOpen}>
      {inBox}
    </button>
  ) : (
    <div className={wrapClass} aria-label={aria}>
      {inBox}
    </div>
  );
  function monthlyRatesMomBadge(mom, labelKey, labelParams) {
    if (mom == null) return null;
    return (
      <span
        className={
          mom.deltaPct > 0
            ? 'pf-landing-totals__monthly-rates-mom-out pf-landing-totals__monthly-rates-mom-out--up'
            : mom.deltaPct < 0
              ? 'pf-landing-totals__monthly-rates-mom-out pf-landing-totals__monthly-rates-mom-out--down'
              : 'pf-landing-totals__monthly-rates-mom-out pf-landing-totals__monthly-rates-mom-out--flat'
        }
      >
        {t(labelKey, labelParams)}
      </span>
    );
  }
  const mom = monthlyRatesMomBadge(display.monthlyRatesMom, 'powerFlowLandingMonthlyRatesMom', {
    delta: display.monthlyRatesMom?.deltaStr,
    prevMonth: display.monthlyRatesMom?.prevMonthLabel,
  });
  return (
    <>
      {display.monthLabel ? <span className="pf-landing-totals__monthly-rates-month">{display.monthLabel}</span> : null}
      {box}
      <span className="pf-landing-totals__monthly-rates-unit">{display.unitSuffix}</span>
      {mom}
    </>
  );
}

/** MoM percentage points for grid-balancing score (Kyiv MTD vs same span in previous month). */
function landingGridBalancingMom(gb, bcp47) {
  const pp = gb?.kyivMonthMomDeltaPp;
  const amY = gb?.kyivMonthMomYear;
  const amM = gb?.kyivMonthMomMonth;
  if (typeof pp !== 'number' || !Number.isFinite(pp) || typeof amY !== 'number' || typeof amM !== 'number') {
    return null;
  }
  const fmtPp = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  const deltaStr = `${pp > 0 ? '+' : ''}${fmtPp.format(pp)}`;
  const amPct = pp;
  const prevStart = gb?.prevMonthStart;
  let prevMonthLabel = '';
  if (prevStart) {
    const [py, pm] = prevStart.split('-').map(Number);
    prevMonthLabel = formatKyivMonthYearMmYy(py, pm);
  } else if (amM >= 1 && amM <= 12) {
    const pm = amM === 1 ? 12 : amM - 1;
    const py = amM === 1 ? amY - 1 : amY;
    prevMonthLabel = formatKyivMonthYearMmYy(py, pm);
  }
  return { deltaPct: amPct, deltaStr, prevMonthLabel };
}

const LANDING_GRID_BALANCING_WRAP_CLASS =
  'pf-landing-totals__counter-wrap pf-landing-totals__counter-wrap--monthly-rates pf-landing-totals__counter-wrap--grid-balancing';
const LANDING_GRID_BALANCING_COUNTER_CLASS =
  'pf-landing-totals__counter pf-landing-totals__counter--monthly-rates pf-landing-totals__counter--grid-balancing';

function formatLandingGridBalancingPct(pct, bcp47) {
  const n = pct != null ? Number(pct) : null;
  if (n == null || !Number.isFinite(n)) return '—';
  const fmt = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  return `${fmt.format(n)}%`;
}

/** Grid-balancing score color tier: &lt;20 red, &lt;60 yellow, else green (up to 100%). */
function landingGridBalancingScoreTier(pct) {
  const n = pct != null ? Number(pct) : null;
  if (n == null || !Number.isFinite(n)) return null;
  if (n < 20) return 'low';
  if (n < 60) return 'mid';
  return 'high';
}

function landingGridBalancingCounterClass(tier) {
  const base = LANDING_GRID_BALANCING_COUNTER_CLASS;
  if (!tier) return base;
  return `${base} pf-landing-totals__counter--grid-balancing--${tier}`;
}

function formatLandingGridBalancingMetric(landingTotals, bcp47, t) {
  const base = {
    monthlyRatesLayout: true,
    unitSuffix: '',
    wrapClass: LANDING_GRID_BALANCING_WRAP_CLASS,
    counterClass: LANDING_GRID_BALANCING_COUNTER_CLASS,
  };
  const gb = landingTotals?.gridBalancing;
  if (!landingTotals?.ok || gb?.configured === false) {
    return {
      ...base,
      text: '—',
      rateInBox: '—',
      monthLabel: '',
      title: t('powerFlowLandingGridBalancingHint'),
      counterAria: t('powerFlowLandingGridBalancingHint'),
      monthlyRatesMom: null,
    };
  }
  const dam = landingTotals.dam;
  let curMonth = '';
  if (dam?.currentMonthStart) {
    const [cy, cm] = dam.currentMonthStart.split('-').map(Number);
    curMonth = formatKyivMonthYearMmYy(cy, cm);
  } else if (gb?.kyivMonthMomYear != null && gb?.kyivMonthMomMonth != null) {
    curMonth = formatKyivMonthYearMmYy(gb.kyivMonthMomYear, gb.kyivMonthMomMonth);
  }
  const pctRaw = gb?.balancingPctMtd;
  const pctStr = formatLandingGridBalancingPct(pctRaw, bcp47);
  const scoreTier = landingGridBalancingScoreTier(pctRaw);
  const scopeFleet = landingTotals.exportScope === 'fleet';
  const hintKey = scopeFleet ? 'powerFlowLandingGridBalancingHintFleet' : 'powerFlowLandingGridBalancingHint';
  const mom = landingGridBalancingMom({ ...gb, prevMonthStart: dam?.prevMonthStart }, bcp47);
  return {
    ...base,
    text: pctStr,
    rateInBox: pctStr,
    monthLabel: curMonth,
    counterClass: landingGridBalancingCounterClass(scoreTier),
    title: t(hintKey),
    counterAria: t('powerFlowLandingGridBalancingCounterAria', { month: curMonth, pct: pctStr.replace('%', '') }),
    monthlyRatesMom: mom,
  };
}

/** Same layout as monthly rates; % in the pill. */
function LandingGridBalancingDisplay({ display, t, asButton, chartAria, onChartOpen }) {
  const pctText = display.rateInBox ?? '—';
  const inBox = (
    <div className="pf-landing-totals__counter-scroll">
      <PfScrollNumber
        direction="up"
        duration={0.32}
        ease={[0.33, 0, 0.2, 1]}
        className={display.counterClass}
        numberStyle={{ letterSpacing: '0.03em' }}
      >
        {formatLandingMetricCounterText(pctText, t, true)}
      </PfScrollNumber>
    </div>
  );
  const wrapClass = asButton
    ? `${display.wrapClass} pf-landing-totals__counter-wrap--export-chart-trigger`
    : display.wrapClass;
  const aria = display.counterAria || display.title || undefined;
  const box = asButton ? (
    <button type="button" className={wrapClass} aria-label={chartAria || aria} onClick={onChartOpen}>
      {inBox}
    </button>
  ) : (
    <div className={wrapClass} aria-label={aria}>
      {inBox}
    </div>
  );
  const mom =
    display.monthlyRatesMom != null ? (
      <span
        className={
          display.monthlyRatesMom.deltaPct > 0
            ? 'pf-landing-totals__monthly-rates-mom-out pf-landing-totals__grid-balancing-mom-out--up'
            : display.monthlyRatesMom.deltaPct < 0
              ? 'pf-landing-totals__monthly-rates-mom-out pf-landing-totals__grid-balancing-mom-out--down'
              : 'pf-landing-totals__monthly-rates-mom-out pf-landing-totals__monthly-rates-mom-out--flat'
        }
      >
        {t('powerFlowLandingGridBalancingMom', {
          delta: display.monthlyRatesMom.deltaStr,
          prevMonth: display.monthlyRatesMom.prevMonthLabel,
        })}
      </span>
    ) : null;
  return (
    <>
      {display.monthLabel ? <span className="pf-landing-totals__monthly-rates-month">{display.monthLabel}</span> : null}
      {box}
      {mom}
    </>
  );
}

/**
 * Power-weighted mean UAH/kWh from active EV sessions (charging-ports items).
 * ``costPerKwt`` is kopecks/kWh (see 220-km ChargingPage: UAH/kWh = costPerKwt/100).
 * Weights by live ``powerWt`` (W); sessions without power fall back to a simple mean.
 */
function volumeWeightedActiveEvSessionTariffUahPerKwh(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  let wsum = 0;
  let wtot = 0;
  const unweighted = [];
  for (const it of items) {
    const ck = Number(it?.costPerKwt);
    if (!Number.isFinite(ck) || ck <= 0) continue;
    const uah = ck / 100.0;
    const pw = Number(it?.powerWt);
    if (Number.isFinite(pw) && pw > 0) {
      wsum += uah * pw;
      wtot += pw;
    } else {
      unweighted.push(uah);
    }
  }
  if (wtot > 1e-6) return wsum / wtot;
  if (unweighted.length > 0) {
    return unweighted.reduce((a, b) => a + b, 0) / unweighted.length;
  }
  return null;
}

/** Fleet totals block: kWh exported + DAM tariff line (Kyiv current month vs previous month). */
function formatLandingTotalsDisplay(landingTotals, bcp47, t) {
  if (!landingTotals?.ok) return null;
  const fmtKwh = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 0 });
  const fmtUah = new Intl.NumberFormat(bcp47, {
    style: 'currency',
    currency: 'UAH',
    maximumFractionDigits: 3,
    minimumFractionDigits: 3,
  });
  const fmtRate = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 3, minimumFractionDigits: 3 });
  const arbRaw = landingTotals.arbitrageRevenueUah;
  let arbitrage = null;
  if (typeof arbRaw === 'number' && Number.isFinite(arbRaw) && arbRaw > 0) {
    const amPct = landingTotals.arbitrageKyivMonthMomPct;
    const amY = landingTotals.arbitrageKyivMonthMomYear;
    const amM = landingTotals.arbitrageKyivMonthMomMonth;
    let mom = null;
    if (
      typeof amPct === 'number' &&
      Number.isFinite(amPct) &&
      typeof amY === 'number' &&
      typeof amM === 'number' &&
      amY >= 2000 &&
      amM >= 1 &&
      amM <= 12
    ) {
      const fmtPct = new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
      const deltaStr = `${amPct > 0 ? '+' : ''}${fmtPct.format(amPct)}%`;
      const bcp47Lower = String(bcp47 || '').toLowerCase();
      const isUk = bcp47Lower === 'uk' || bcp47Lower.startsWith('uk-');
      let monthLabel;
      if (isUk && amM >= 1 && amM <= 12) {
        const sh = UK_MONTH_SHORT[amM];
        monthLabel = sh ? sh.charAt(0).toUpperCase() + sh.slice(1) : String(amM);
      } else {
        monthLabel = new Intl.DateTimeFormat(bcp47, { month: 'short', timeZone: 'Europe/Kyiv' }).format(
          new Date(Date.UTC(amY, amM - 1, 15, 12, 0, 0))
        );
        if (monthLabel.length > 0) {
          monthLabel = monthLabel.charAt(0).toUpperCase() + monthLabel.slice(1);
        }
      }
      mom = { deltaPct: amPct, deltaStr, monthLabel };
    }
    arbitrage = { revenueText: fmtUah.format(arbRaw), mom };
  }
  const pds = landingTotals.peakDamLastSession;
  let peakDam = null;
  if (
    pds &&
    typeof pds.exportSessionKwh === 'number' &&
    Number.isFinite(pds.exportSessionKwh) &&
    pds.exportSessionKwh > 0
  ) {
    peakDam = {
      exportText: fmtKwh.format(pds.exportSessionKwh),
    };
  }
  const mds = landingTotals.manualDischargeLastSession;
  let manualDischarge = null;
  if (
    mds &&
    typeof mds.exportSessionKwh === 'number' &&
    Number.isFinite(mds.exportSessionKwh) &&
    mds.exportSessionKwh > 0
  ) {
    manualDischarge = {
      exportText: fmtKwh.format(mds.exportSessionKwh),
    };
  }
  const dam = landingTotals.dam;
  if (dam?.configured && dam.currentAvgUahPerKwh != null && dam.currentMonthStart && dam.prevMonthStart) {
    const monthFmt = new Intl.DateTimeFormat(bcp47, { month: 'long' });
    const [cy, cm] = dam.currentMonthStart.split('-').map(Number);
    const [py, pm] = dam.prevMonthStart.split('-').map(Number);
    const bcp47Lower = String(bcp47 || '').toLowerCase();
    const isUk = bcp47Lower === 'uk' || bcp47Lower.startsWith('uk-');
    let curMonth;
    let prevMonth;
    if (isUk && cm >= 1 && cm <= 12 && pm >= 1 && pm <= 12) {
      const acc = UK_MONTH_ACCUSATIVE[cm];
      const ins = UK_MONTH_INSTRUMENTAL[pm];
      curMonth = acc ? acc.charAt(0).toUpperCase() + acc.slice(1) : acc;
      prevMonth = ins ? ins.charAt(0).toUpperCase() + ins.slice(1) : ins;
    } else {
      curMonth = monthFmt.format(new Date(cy, cm - 1, 15));
      prevMonth = monthFmt.format(new Date(py, pm - 1, 15));
    }
    const retailCurrent = landingRetailUahPerKwh(dam.currentAvgUahPerKwh);
    const retailPrev = landingRetailUahPerKwh(dam.prevAvgUahPerKwh);
    const rate = retailCurrent != null ? fmtRate.format(retailCurrent) : '—';
    const isDeviceScope =
    landingTotals.exportScope === 'device' ||
    landingTotals.exportScope === 'huawei' ||
    landingTotals.exportScope === 'ev_ports';
    const personalDamWavg = dam.currentMonthDeviceImportWeightedAvgDamUahPerKwhMtd;
    let damTariffLine = null;
    if (isDeviceScope && personalDamWavg != null && Number.isFinite(Number(personalDamWavg))) {
      const retailPersonal = landingRetailUahPerKwh(Number(personalDamWavg));
      if (retailPersonal != null) {
        damTariffLine = t('powerFlowLandingDamTariffLine', {
          month: curMonth,
          rate: fmtRate.format(retailPersonal),
        });
      }
    }
    if (dam.prevAvgUahPerKwh != null && retailCurrent != null && retailPrev != null && retailPrev > 0) {
      const pct = ((retailCurrent - retailPrev) / retailPrev) * 100;
      const deltaStr = `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`;
      return {
        tariffLine: null,
        tariffCompare: {
          lead: t('powerFlowLandingTariffLineLead', { month: curMonth, rate }),
          deltaPct: pct,
          deltaStr,
          tail: t('powerFlowLandingTariffLineTail', { prevMonth }),
        },
        damTariffLine,
        peakDam,
        manualDischarge,
        arbitrage,
      };
    }
    return {
      tariffLine: t('powerFlowLandingTariffPartial', { month: curMonth, rate }),
      tariffCompare: null,
      damTariffLine,
      peakDam,
      manualDischarge,
      arbitrage,
    };
  }
  return {
    tariffLine: t('powerFlowLandingTariffUnavailable'),
    tariffCompare: null,
    damTariffLine: null,
    peakDam,
    manualDischarge,
    arbitrage,
  };
}

/** Target SoC (%) after discharge; same order as the toolbar dropdown. */
const DISCHARGE_TARGET_SOC_OPTIONS = Object.freeze([95, 80, 50, 20, 10, 5, 1, 0]);

function peakPrefDischargePctForApi(pct) {
  return normalizeDischargeSocDeltaPct(pct);
}

/** SoC drop (percentage points) sent to POST /api/deye/discharge-2pct from current SoC to target floor. */
function effectiveDischargeDeltaForApi(targetSocPct, currentSoc) {
  const c = Number(currentSoc);
  const t = Math.round(Number(targetSocPct));
  if (!Number.isFinite(c) || !Number.isFinite(t)) return 2;
  const d = Math.round(c - t);
  return Math.min(100, Math.max(1, d));
}

function normalizeDischargeSocDeltaPct(p) {
  const n = Math.round(Number(p));
  if (!Number.isFinite(n)) return 80;
  if (DISCHARGE_TARGET_SOC_OPTIONS.includes(n)) return n;
  const legacy = { 2: 80, 10: 50, 20: 20, 100: 5 };
  if (legacy[n] != null) return legacy[n];
  return DISCHARGE_TARGET_SOC_OPTIONS.reduce((best, x) => (Math.abs(x - n) < Math.abs(best - n) ? x : best));
}

const CHARGE_SOC_DELTA_OPTIONS = Object.freeze([2, 10, 20, 50, 100]);

function normalizeChargeSocDeltaPct(p) {
  const n = Math.round(Number(p));
  if (!Number.isFinite(n)) return 10;
  if (CHARGE_SOC_DELTA_OPTIONS.includes(n)) return n;
  return CHARGE_SOC_DELTA_OPTIONS.reduce((best, x) => (Math.abs(x - n) < Math.abs(best - n) ? x : best));
}

/** Battery SoC row color: &lt;20 red, &lt;70 yellow, else green. */
function essSocBandClassName(pct) {
  const n = Number(pct);
  if (!Number.isFinite(n)) return '';
  if (n < 20) return 'pf-ess-soc--low';
  if (n < 70) return 'pf-ess-soc--mid';
  return 'pf-ess-soc--high';
}

const TOOLBAR_HINT_HOVER_MS = 1000;

/** Hint popup after hover delay (native ``title`` is instant and weak on nested controls). */
function DelayedHintTooltip({ hintText, children }) {
  const tipId = useId();
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState('');
  const timerRef = useRef(null);
  const hintRef = useRef(hintText);
  hintRef.current = hintText;

  const clearTimer = useCallback(() => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const onEnter = useCallback(() => {
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setShown(hintRef.current);
      setOpen(true);
    }, TOOLBAR_HINT_HOVER_MS);
  }, [clearTimer]);

  const onLeave = useCallback(() => {
    clearTimer();
    setOpen(false);
  }, [clearTimer]);

  useEffect(() => () => clearTimer(), [clearTimer]);

  return (
    <span className="pf-delayed-hint-wrap" onMouseEnter={onEnter} onMouseLeave={onLeave}>
      {open ? (
        <span id={tipId} role="tooltip" className="pf-discharge-go-tooltip">
          {shown}
        </span>
      ) : null}
      {children}
    </span>
  );
}

function MotionDot({ pathD }) {
  return (
    <circle r="5.8" fill="url(#pf-flow-dot-grad)" className="pf-flow-dot">
      <animateMotion
        dur={FLOW_DOT_MOTION_DUR}
        repeatCount="indefinite"
        calcMode="spline"
        keyTimes="0;1"
        keySplines="0.45 0 0.55 1"
        path={pathD}
      />
      <animate
        attributeName="opacity"
        values="0.98;0.98;0"
        keyTimes="0;0.82;1"
        dur={FLOW_DOT_MOTION_DUR}
        repeatCount="indefinite"
      />
    </circle>
  );
}

function LandingExportMetricCounter({
  display,
  t,
  landingHuaweiEss,
  showMonthlyRatesChart,
  showExportHourlyChart,
  landingExportMetric,
  onOpenMonthlyRates,
  onOpenExportChart,
}) {
  const { kwhHidden, requestReveal } = useKwhCalibration();
  const masked = !display.valueIsCurrency && kwhHidden;
  const counterText = masked
    ? `— ${t('powerFlowLandingKwhUnit')}`
    : formatLandingMetricCounterText(display.text, t, display.valueIsCurrency);

  const counterInner = (
    <div className="pf-landing-totals__counter-scroll">
      <PfScrollNumber
        direction="up"
        duration={0.32}
        ease={[0.33, 0, 0.2, 1]}
        className={display.counterClass}
        numberStyle={{ letterSpacing: '0.05em' }}
      >
        {counterText}
      </PfScrollNumber>
    </div>
  );

  if (masked) {
    return (
      <button
        type="button"
        className={`${display.wrapClass} pf-landing-totals__counter-wrap--kwh-calibration`}
        aria-label={t('kwhCalibrationMessage')}
        onClick={requestReveal}
      >
        {counterInner}
      </button>
    );
  }

  if (landingHuaweiEss && !showMonthlyRatesChart && !showExportHourlyChart) {
    return (
      <div className={display.wrapClass} aria-label={display.title || undefined}>
        {counterInner}
      </div>
    );
  }

  return (
    <button
      type="button"
      className={`${display.wrapClass} pf-landing-totals__counter-wrap--export-chart-trigger`}
      aria-label={
        showMonthlyRatesChart
          ? t('powerFlowMonthlyRatesChartOpenAria')
          : landingExportMetric === LANDING_EXPORT_METRIC.LOST_SOLAR_7D
            ? t('powerFlowLostSolarHourlyChartOpenAria')
            : t('powerFlowPeakHourlyChartOpenAria')
      }
      onClick={() => {
        if (showMonthlyRatesChart) onOpenMonthlyRates();
        else onOpenExportChart();
      }}
    >
      {counterInner}
    </button>
  );
}

export default function PowerFlowPage({
  t,
  getBcp47Locale,
  locale,
  SUPPORTED,
  LOCALE_NAMES,
  onLangSelectChange,
  isDark,
  kioskMode = false,
}) {
  const graphRef = useRef(null);
  const isWideViewport = useMinWidth(KIOSK_WIDE_MIN_PX);
  const [graphWidth, setGraphWidth] = useState(400);
  const [stationFilter, setStationFilter] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get('station') || '';
    } catch {
      return '';
    }
  });
  const [loadError, setLoadError] = useState('');
  const [realtimePower, setRealtimePower] = useState(null);
  /** Sum of latest /api/deye/ess-power samples across all Deye inverters (no ESS selected). */
  const [fleetDeyeAggregate, setFleetDeyeAggregate] = useState({
    loading: false,
    okResponses: 0,
    pvW: 0,
    gridW: 0,
    batteryW: 0,
    loadW: 0,
  });
  /** Sums from GET /api/huawei/power-flow across all plants (no ESS selected). */
  const [fleetHuaweiAggregate, setFleetHuaweiAggregate] = useState({
    loading: false,
    okResponses: 0,
    pvW: 0,
    loadW: 0,
    batteryW: 0,
  });
  const [minerSnap, setMinerSnap] = useState(null);
  const [inverterRows, setInverterRows] = useState({
    loading: true,
    configured: false,
    items: [],
    error: false,
  });
  const [huaweiRows, setHuaweiRows] = useState({
    loading: true,
    configured: false,
    items: [],
    error: false,
    northboundRateLimited: false,
    authFailed: false,
  });
  const [chargingPorts, setChargingPorts] = useState({
    loading: true,
    ok: true,
    items: [],
  });
  /** Charging power (W) from GET /api/b2b/station-status for the selected EV port; null = unknown / error. */
  const [evStationPowerW, setEvStationPowerW] = useState(null);
  const [evStationPowerLoading, setEvStationPowerLoading] = useState(false);
  /** Sum of EV charger power (W) from GET /api/b2b/ev-ports-power when EV DC/AC aggregate source is selected. */
  const [evPortsLive, setEvPortsLive] = useState({ loading: false, powerW: null, activeSessions: 0, acdc: null });
  /**
   * Fallback: network-wide volume-weighted avg UAH/kWh from GET /api/b2b/charging-network-tariff-avg (past UTC days).
   * EV node prefers live session tariffs from charging-ports when any active job includes costPerKwt.
   */
  const [evChargingNetworkTariff, setEvChargingNetworkTariff] = useState({ loading: true, value: null });
  /** Reference LCOE (UAH/kWh) from GET /api/power-flow/reference-lcoe — illustrative, not site-specific. */
  const [referenceLcoe, setReferenceLcoe] = useState({
    loading: true,
    ok: false,
    solarUahPerKwh: null,
    batteryUahPerKwh: null,
  });
  /** Kyiv-today OREE hourly DAM (UAH/kWh) from GET /api/dam/chart-day — for grid node's current hour. */
  const [damKyivTodayHourly, setDamKyivTodayHourly] = useState({
    loading: true,
    tradeDayIso: null,
    hourlyUahPerKwh: null,
    oreeConfigured: false,
  });
  const [simTick, setSimTick] = useState(0);
  const [deyeMessengerOpen, setDeyeMessengerOpen] = useState(false);

  const closeDeyeMessenger = useCallback(() => {
    setDeyeMessengerOpen(false);
    try {
      if (window.location.hash === '#addInverterToOpenEms') {
        const { pathname, search } = window.location;
        window.history.replaceState(null, '', pathname + (search || ''));
      }
    } catch {
      /* ignore */
    }
  }, []);

  const bcp47 = getBcp47Locale();
  const inverterSocFmt = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 1,
      }),
    [bcp47]
  );

  const formatUahPerKwhTariffLine = useCallback(
    v => {
      const n = Number(v);
      if (!Number.isFinite(n)) return '';
      return t('tariffKwh', {
        value: new Intl.NumberFormat(bcp47, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }).format(Math.max(0, n)),
      });
    },
    [bcp47, t]
  );

  /** Dropdown CAPEX: plain amount + space + $ (no locale currency symbol / grouping). */
  const formatInverterCapexUsd = useCallback(n => {
    const v = Math.round(Number(n));
    if (!Number.isFinite(v)) return '';
    return `${v} $`;
  }, []);

  const geoForPortsRef = useRef(null);
  const geoRequestedRef = useRef(false);
  /** Only the first charging-ports fetch toggles `loading` so the page overlay does not flash on 60s refresh. */
  const chargingPortsInitialFetchRef = useRef(true);
  /** First solar-insolation fetch per inverter sets `loading` (page overlay); hourly refresh does not. */
  const solarInsolationInitialFetchRef = useRef(true);

  useEffect(() => {
    let cancelled = false;
    const readGeoOnce = () =>
      new Promise(resolve => {
        if (typeof navigator === 'undefined' || !navigator.geolocation) {
          resolve(null);
          return;
        }
        navigator.geolocation.getCurrentPosition(
          p => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
          () => resolve(null),
          { maximumAge: 300_000, timeout: 8_000 }
        );
      });

    const load = async () => {
      if (chargingPortsInitialFetchRef.current) {
        setChargingPorts(s => ({ ...s, loading: true }));
      }
      try {
        if (!geoRequestedRef.current) {
          geoRequestedRef.current = true;
          geoForPortsRef.current = await readGeoOnce();
        }
        const geo = geoForPortsRef.current;
        const params = new URLSearchParams();
        if (geo) {
          params.set('lat', String(geo.lat));
          params.set('lon', String(geo.lon));
        }
        const qs = params.toString();
        const r = await fetch(apiUrl(`/api/b2b/charging-ports${qs ? `?${qs}` : ''}`), {
          cache: 'no-store',
        });
        const data = await r.json();
        if (cancelled) return;
        const items = Array.isArray(data?.items) ? data.items : [];
        setChargingPorts({
          loading: false,
          ok: data?.ok !== false,
          items,
        });
      } catch {
        if (!cancelled) {
          setChargingPorts({ loading: false, ok: false, items: [] });
        }
      } finally {
        chargingPortsInitialFetchRef.current = false;
      }
    };

    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch(apiUrl('/api/b2b/charging-network-tariff-avg?days=7'), { cache: 'no-store' });
        const d = await r.json();
        if (cancelled) return;
        const v = d?.avgUahPerKwh;
        if (d?.ok && typeof v === 'number' && Number.isFinite(v)) {
          setEvChargingNetworkTariff({ loading: false, value: v });
        } else {
          setEvChargingNetworkTariff({ loading: false, value: null });
        }
      } catch {
        if (!cancelled) setEvChargingNetworkTariff({ loading: false, value: null });
      }
    };
    void load();
    const id = setInterval(load, 3_600_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch(apiUrl('/api/power-flow/reference-lcoe'), { cache: 'no-store' });
        const d = await r.json();
        if (cancelled) return;
        const s = Number(d?.solarAmortizedUahPerKwh);
        const b = Number(d?.batteryAmortizedUahPerKwh);
        if (d?.ok && Number.isFinite(s) && Number.isFinite(b)) {
          setReferenceLcoe({ loading: false, ok: true, solarUahPerKwh: s, batteryUahPerKwh: b });
        } else {
          setReferenceLcoe({ loading: false, ok: false, solarUahPerKwh: null, batteryUahPerKwh: null });
        }
      } catch {
        if (!cancelled) {
          setReferenceLcoe({ loading: false, ok: false, solarUahPerKwh: null, batteryUahPerKwh: null });
        }
      }
    };
    void load();
    const id = setInterval(load, 6 * 3_600_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const day = kyivCalendarIsoForDam();
      try {
        const r = await fetch(apiUrl(`/api/dam/chart-day?date=${encodeURIComponent(day)}`), { cache: 'no-store' });
        const d = await r.json();
        if (cancelled) return;
        const hourly = Array.isArray(d?.hourlyPriceDamUahPerKwh) ? d.hourlyPriceDamUahPerKwh : null;
        setDamKyivTodayHourly({
          loading: false,
          tradeDayIso: typeof d?.date === 'string' ? d.date : day,
          hourlyUahPerKwh: hourly,
          oreeConfigured: Boolean(d?.oreeConfigured),
        });
      } catch {
        if (!cancelled) {
          setDamKyivTodayHourly({
            loading: false,
            tradeDayIso: day,
            hourlyUahPerKwh: null,
            oreeConfigured: false,
          });
        }
      }
    };
    void load();
    const id = setInterval(load, 300_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useOpenEmsSeo(t('pageTitle'), locale, t, { variant: 'default', canonicalPath: '/' });

  useEffect(() => {
    return () => {};
  }, []);

  useEffect(() => {
    const el = graphRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => {
      setGraphWidth(el.offsetWidth || 400);
    });
    ro.observe(el);
    setGraphWidth(el.offsetWidth || 400);
    return () => ro.disconnect();
  }, []);

  const fetchRealtime = useCallback(async () => {
    const q = stationFilter.trim() ? `?station=${encodeURIComponent(stationFilter.trim())}` : '';
    const r = await fetch(apiUrl(`/api/b2b/realtime-power${q}`), { cache: 'no-store' });
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    return r.json();
  }, [stationFilter]);

  const fetchMiner = useCallback(async () => {
    const r = await fetch(apiUrl('/api/b2b/miner-power'), { cache: 'no-store' });
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    return r.json();
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchRealtime();
        if (!cancelled) {
          setRealtimePower(data);
          setLoadError('');
        }
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
      }
    })();
    const id = setInterval(async () => {
      try {
        const data = await fetchRealtime();
        setRealtimePower(data);
        setLoadError('');
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : String(e));
      }
    }, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [fetchRealtime]);

  useEffect(() => {
    const sn = stationFilter.trim();
    if (!sn) {
      setEvStationPowerW(null);
      setEvStationPowerLoading(false);
      return undefined;
    }
    let cancelled = false;
    let first = true;
    const parsePowerFromStationStatus = data => {
      if (!data || typeof data !== 'object') return null;
      if (data.lastJobPresented === false) return 0;
      const job = data.lastJob;
      if (!job || typeof job !== 'object') return 0;
      if (job.deviceOnline === false) return 0;
      const st = String(job.state || '')
        .toUpperCase()
        .replace(/-/g, '_');
      if (st !== 'IN_PROGRESS') return 0;
      const p = job.powerWt;
      if (p == null || !Number.isFinite(Number(p))) return 0;
      return Math.max(0, Number(p));
    };
    const tick = async () => {
      if (first) setEvStationPowerLoading(true);
      try {
        const q = new URLSearchParams({ station_number: sn });
        const r = await fetch(apiUrl(`/api/b2b/station-status?${q}`), { cache: 'no-store' });
        const data = await r.json().catch(() => null);
        if (!cancelled) {
          if (r.ok && data && typeof data === 'object') setEvStationPowerW(parsePowerFromStationStatus(data));
          else setEvStationPowerW(null);
        }
      } catch {
        if (!cancelled) setEvStationPowerW(null);
      } finally {
        if (!cancelled) {
          setEvStationPowerLoading(false);
          first = false;
        }
      }
    };
    void tick();
    const id = setInterval(() => void tick(), 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [stationFilter]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchMiner();
        if (!cancelled) setMinerSnap(data);
      } catch {
        /* keep previous */
      }
    })();
    const id = setInterval(async () => {
      try {
        const data = await fetchMiner();
        if (!cancelled) setMinerSnap(data);
      } catch {
        /* keep */
      }
    }, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [fetchMiner]);

  const loadInverters = useCallback(async () => {
    try {
      const r = await fetch(apiUrl('/api/deye/inverters'), { cache: 'no-store' });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setInverterRows({ loading: false, configured: false, items: [], error: true });
      } else {
        setInverterRows({
          loading: false,
          configured: !!data.configured,
          items: data.items || [],
          error: false,
        });
      }
    } catch {
      setInverterRows({ loading: false, configured: false, items: [], error: true });
    }
  }, []);

  useEffect(() => {
    void loadInverters();
    const id = setInterval(() => void loadInverters(), 60_000);
    return () => clearInterval(id);
  }, [loadInverters]);

  const loadHuaweiStations = useCallback(async () => {
    try {
      const r = await fetch(apiUrl('/api/huawei/stations'), { cache: 'no-store' });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setHuaweiRows({
          loading: false,
          configured: false,
          items: [],
          error: true,
          northboundRateLimited: false,
          authFailed: false,
        });
      } else {
        setHuaweiRows({
          loading: false,
          configured: !!data.configured,
          items: data.items || [],
          error: false,
          northboundRateLimited: !!data.northboundRateLimited,
          authFailed: !!data.huaweiAuthFailed,
        });
      }
    } catch {
      setHuaweiRows({
        loading: false,
        configured: false,
        items: [],
        error: true,
        northboundRateLimited: false,
        authFailed: false,
      });
    }
  }, []);

  useEffect(() => {
    void loadHuaweiStations();
    const id = setInterval(() => void loadHuaweiStations(), HUAWEI_NORTHBOUND_POLL_MS);
    return () => clearInterval(id);
  }, [loadHuaweiStations]);

  const [inverterValue, setInverterValue] = useState('');
  const deyeCombinedItems = useMemo(() => {
    const byKey = new Map();
    for (const row of inverterRows.items) {
      const sn = String(row?.deviceSn || '').trim();
      if (!sn) continue;
      const shortLabel = inverterSelectShortLabel(row.label, row.deviceSn);
      const key = shortLabel || sn;
      const prev = byKey.get(key);
      if (!prev) {
        byKey.set(key, {
          key,
          shortLabel: key,
          representativeSn: sn,
          clusterSns: [sn],
          capexUsd: row?.capexUsd ?? null,
          pinRequired: !!row?.pinRequired,
        });
        continue;
      }
      prev.clusterSns.push(sn);
      // Keep representative stable: smallest serial.
      if (sn < prev.representativeSn) prev.representativeSn = sn;
      if (prev.capexUsd == null && row?.capexUsd != null) prev.capexUsd = row.capexUsd;
      prev.pinRequired = prev.pinRequired || !!row?.pinRequired;
    }
    return Array.from(byKey.values()).sort((a, b) => a.shortLabel.localeCompare(b.shortLabel));
  }, [inverterRows.items]);
  const deyeSnToRepresentative = useMemo(() => {
    const m = new Map();
    for (const it of deyeCombinedItems) {
      m.set(it.representativeSn, it.representativeSn);
      for (const sn of it.clusterSns) m.set(sn, it.representativeSn);
    }
    return m;
  }, [deyeCombinedItems]);

  useEffect(() => {
    if (inverterRows.loading || huaweiRows.loading) return;
    let want = '';
    try {
      want = new URLSearchParams(window.location.search).get('inverter') || '';
      if (!want) want = localStorage.getItem(INVERTER_STORAGE) || '';
      want = normalizeEssSelectionValue(want);
    } catch {
      /* ignore */
    }
    if (!want) return;
    const parsed = parseEssSelection(want);
    if (parsed.provider === 'deye' && inverterRows.configured && !inverterRows.error) {
      const rep = deyeSnToRepresentative.get(parsed.id) || parsed.id;
      if (deyeCombinedItems.some(r => r.representativeSn === rep)) {
        setInverterValue(`${ESS_PREFIX_DEYE}${rep}`);
      }
    } else if (parsed.provider === 'huawei' && huaweiRows.configured && !huaweiRows.error) {
      if (huaweiRows.items.some(r => r.stationCode === parsed.id)) {
        setInverterValue(want);
      }
    } else if (parsed.provider === 'dc-ev' || parsed.provider === 'ac-ev') {
      setInverterValue(`${parsed.provider === 'ac-ev' ? ESS_PREFIX_AC_EV : ESS_PREFIX_DC_EV}${parsed.id || 'all'}`);
    }
  }, [inverterRows, huaweiRows, deyeCombinedItems, deyeSnToRepresentative]);

  const onInverterChange = useCallback(e => {
    const v = normalizeEssSelectionValue(e.target.value);
    setInverterValue(v);
    setStationFilter('');
    try {
      if (v) localStorage.setItem(INVERTER_STORAGE, v);
      else localStorage.removeItem(INVERTER_STORAGE);
    } catch {
      /* ignore */
    }
    const u = new URL(window.location.href);
    if (v) u.searchParams.set('inverter', v);
    else u.searchParams.delete('inverter');
    u.searchParams.delete('station');
    window.history.replaceState({}, '', u);
  }, []);

  const essSel = useMemo(() => parseEssSelection(inverterValue), [inverterValue]);
  const selInverterSn = essSel.provider === 'deye' ? essSel.id.trim() : '';
  const selHuaweiStationCode = essSel.provider === 'huawei' ? essSel.id.trim() : '';
  const selEvPortsAcdc = evPortsAcdcFromProvider(essSel.provider);
  const selEvPortsAggregate = selEvPortsAcdc != null;
  const essAnySelected = Boolean(selInverterSn || selHuaweiStationCode || selEvPortsAggregate);

  const inverterSnsKey = useMemo(
    () =>
      inverterRows.items
        .map(r => r.deviceSn)
        .filter(Boolean)
        .sort()
        .join(','),
    [inverterRows.items]
  );

  /** One poll per merged Deye dropdown row — avoids summing duplicate plant telemetry for every raw serial. */
  const fleetDeyeRepresentativeSnsKey = useMemo(
    () =>
      deyeCombinedItems
        .map(r => String(r.representativeSn || '').trim())
        .filter(Boolean)
        .sort()
        .join(','),
    [deyeCombinedItems]
  );

  useEffect(() => {
    if (essAnySelected || !inverterRows.configured || inverterRows.error) {
      setFleetDeyeAggregate({
        loading: false,
        okResponses: 0,
        pvW: 0,
        gridW: 0,
        batteryW: 0,
        loadW: 0,
      });
      return undefined;
    }
    const sns = deyeCombinedItems.map(r => String(r.representativeSn || '').trim()).filter(Boolean);
    if (sns.length === 0) {
      setFleetDeyeAggregate({
        loading: false,
        okResponses: 0,
        pvW: 0,
        gridW: 0,
        batteryW: 0,
        loadW: 0,
      });
      return undefined;
    }
    let cancelled = false;
    const poll = async () => {
      setFleetDeyeAggregate(prev => ({ ...prev, loading: true }));
      let ok = 0;
      let pv = 0;
      let grid = 0;
      let bat = 0;
      let load = 0;
      await Promise.all(
        sns.map(async sn => {
          try {
            const q = new URLSearchParams({ deviceSn: sn });
            const r = await fetch(`${apiUrl('/api/deye/ess-power')}?${q}`, { cache: 'no-store' });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok || data.configured === false) return;
            ok += 1;
            const batv = data.batteryPowerW;
            const loadW = data.loadPowerW;
            const pvW = data.pvPowerW;
            const gridW = data.gridPowerW;
            if (batv != null && Number.isFinite(Number(batv))) bat += Number(batv);
            if (loadW != null && Number.isFinite(Number(loadW))) load += Math.max(0, Number(loadW));
            if (pvW != null && Number.isFinite(Number(pvW))) pv += Math.max(0, Number(pvW));
            if (gridW != null && Number.isFinite(Number(gridW))) grid += Number(gridW);
          } catch {
            /* ignore per device */
          }
        })
      );
      if (!cancelled) {
        setFleetDeyeAggregate({
          loading: false,
          okResponses: ok,
          pvW: pv,
          gridW: grid,
          batteryW: bat,
          loadW: load,
        });
      }
    };
    void poll();
    const id = setInterval(() => void poll(), 20_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [essAnySelected, inverterRows.configured, inverterRows.error, fleetDeyeRepresentativeSnsKey]);

  const huaweiStationCodesKey = useMemo(
    () =>
      huaweiRows.items
        .map(r => String(r.stationCode || '').trim())
        .filter(Boolean)
        .sort()
        .join(','),
    [huaweiRows.items]
  );

  /** Poll all Huawei plants for fleet PV/load when no single ESS is selected (slower interval — Northbound limits). */
  useEffect(() => {
    if (essAnySelected || !huaweiRows.configured || huaweiRows.error || huaweiRows.authFailed) {
      setFleetHuaweiAggregate({ loading: false, okResponses: 0, pvW: 0, loadW: 0, batteryW: 0 });
      return undefined;
    }
    const codes = huaweiRows.items.map(r => String(r.stationCode || '').trim()).filter(Boolean);
    if (codes.length === 0) {
      setFleetHuaweiAggregate({ loading: false, okResponses: 0, pvW: 0, loadW: 0, batteryW: 0 });
      return undefined;
    }
    let cancelled = false;
    const poll = async () => {
      setFleetHuaweiAggregate(prev => ({ ...prev, loading: true }));
      let ok = 0;
      let pv = 0;
      let load = 0;
      let bat = 0;
      await Promise.all(
        codes.map(async stationCode => {
          try {
            const q = new URLSearchParams({ stationCodes: stationCode });
            const r = await fetch(`${apiUrl('/api/huawei/power-flow')}?${q}`, { cache: 'no-store' });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok || data.configured === false) return;
            ok += 1;
            const pvW = data.pvPowerW;
            if (pvW != null && Number.isFinite(Number(pvW))) pv += Math.max(0, Number(pvW));
            const loadW = data.loadPowerW;
            if (loadW != null && Number.isFinite(Number(loadW))) load += Math.max(0, Number(loadW));
            const batW = data.batteryPowerW;
            if (batW != null && Number.isFinite(Number(batW))) bat += Number(batW);
          } catch {
            /* ignore per plant */
          }
        })
      );
      if (!cancelled) {
        setFleetHuaweiAggregate({
          loading: false,
          okResponses: ok,
          pvW: pv,
          loadW: load,
          batteryW: bat,
        });
      }
    };
    void poll();
    const id = setInterval(() => void poll(), 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [essAnySelected, huaweiRows.configured, huaweiRows.error, huaweiRows.authFailed, huaweiStationCodesKey]);

  const selInverterPinRequired = useMemo(() => {
    const sn = selInverterSn.trim();
    if (!sn) return false;
    const row = deyeCombinedItems.find(r => r.representativeSn === sn);
    return Boolean(row?.pinRequired);
  }, [selInverterSn, deyeCombinedItems]);

  /** Composed list label for the selected inverter (includes evport<N> when bound). */
  const selInverterLabel = useMemo(() => {
    const sn = selInverterSn.trim();
    if (!sn) return '';
    const row = deyeCombinedItems.find(r => r.representativeSn === sn);
    return row?.shortLabel != null ? String(row.shortLabel) : '';
  }, [selInverterSn, deyeCombinedItems]);
  /**
   * Some Deye plants expose multiple ESS serials under one station label (e.g. "Холод Склад 1").
   * For realtime graph values we aggregate all serials that share the same select short-label.
   */
  const selDeyeClusterSns = useMemo(() => {
    const sn = selInverterSn.trim();
    if (!sn) return [];
    const grouped = deyeCombinedItems.find(r => r.representativeSn === sn);
    if (!grouped) return [sn];
    return grouped.clusterSns.length > 0 ? grouped.clusterSns : [sn];
  }, [selInverterSn, deyeCombinedItems]);

  /** EV port binding in Deye name — remote writes allowed without a trailing `` pin`` suffix (server-side). */
  const selInverterEvportBound = useMemo(() => Boolean(parseEvPortStationNumber(selInverterLabel)), [selInverterLabel]);

  /** Deye Cloud encodes a PIN **or** label has evport<N> (same as backend assert). */
  const remoteWriteConfigured = useMemo(
    () => selInverterPinRequired || selInverterEvportBound,
    [selInverterPinRequired, selInverterEvportBound]
  );

  /** Bumps when PIN cache mutates (localStorage is outside React). */
  const [pinCacheBust, setPinCacheBust] = useState(0);
  /** Saved PIN for write actions (24h in localStorage); empty if none / expired. */
  const cachedWritePin = useMemo(
    () => readCachedInverterPin(selInverterSn),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pinCacheBust forces re-read when PIN cache updates
    [selInverterSn, pinCacheBust]
  );

  const [socBySn, setSocBySn] = useState({});
  const [socListLoading, setSocListLoading] = useState(false);
  /** Deye live metrics when an inverter is selected: battery, load, PV, grid. */
  const [deyeLive, setDeyeLive] = useState(null);
  const [deyeLiveLoading, setDeyeLiveLoading] = useState(false);
  /** Matches `selInverterSn` after Deye ess-power has completed for that SN (avoids blur on 20s poll). */
  const [deyeHydratedSn, setDeyeHydratedSn] = useState('');
  /** Huawei real power (getDevRealKpi meter + inverter via GET /api/huawei/power-flow). */
  const [huaweiLive, setHuaweiLive] = useState(null);
  const [huaweiLiveLoading, setHuaweiLiveLoading] = useState(false);
  const [huaweiHydratedCode, setHuaweiHydratedCode] = useState('');
  /** Today/tomorrow insolation % + today cloud icon hint (coordinates never exposed to browser). */
  const [solarForecast, setSolarForecast] = useState({
    loading: false,
    todayPct: null,
    todayCloudy: null,
    tomorrowPct: null,
    hintKey: null,
  });
  const [discharge2Feedback, setDischarge2Feedback] = useState('');
  const [remoteWriteNeedsPinOpen, setRemoteWriteNeedsPinOpen] = useState(false);
  const discharge2BusyRef = useRef(false);
  const charge2BusyRef = useRef(false);
  const [dischargeHoverTipOpen, setDischargeHoverTipOpen] = useState(false);
  const [dischargeHoverTipText, setDischargeHoverTipText] = useState('');
  const dischargeHoverTipTimerRef = useRef(null);
  /** After first load, inverter/station changes keep ``landingExportMetric`` unless URL overrides or context forbids it. */
  const landingExportMetricHydratedRef = useRef(false);
  /** One-shot: after landing totals load, promote legacy monthly_rates selection to grid balancing. */
  const landingExportMetricDefaultedRef = useRef(false);
  /** Previous Deye ``selInverterSn`` (Huawei mode uses empty SN); used to reset metric to total export on inverter change. */
  const prevSelInverterSnForMetricRef = useRef(null);
  const [peakDamDischargeEnabled, setPeakDamDischargeEnabled] = useState(false);
  const [dischargeSocDeltaPct, setDischargeSocDeltaPct] = useState(80);
  const [lowDamChargeEnabled, setLowDamChargeEnabled] = useState(false);
  const [chargeSocDeltaPct, setChargeSocDeltaPct] = useState(10);
  const [selfConsumptionEnabled, setSelfConsumptionEnabled] = useState(false);
  const [nightChargeEnabled, setNightChargeEnabled] = useState(false);
  const [toolbarPrefsLoading, setToolbarPrefsLoading] = useState(false);
  /** Fleet or per-inverter totals from GET /api/power-flow/landing-totals. */
  const [landingTotals, setLandingTotals] = useState(null);
  const [landingTotalsLoading, setLandingTotalsLoading] = useState(false);
  const [landingExportMetric, setLandingExportMetric] = useState(LANDING_EXPORT_METRIC.GRID_BALANCING);

  /** Self-consumption hint / aria: reference LCOE + same till-SoC label as the discharge dropdown. */
  const selfConsumptionHintWithLcoe = useMemo(() => {
    const lcoeStr =
      !referenceLcoe.loading &&
      referenceLcoe.ok &&
      referenceLcoe.batteryUahPerKwh != null &&
      Number.isFinite(Number(referenceLcoe.batteryUahPerKwh))
        ? formatUahPerKwhTariffLine(referenceLcoe.batteryUahPerKwh)
        : '—';
    const tillSocLabel = t('dischargeTillSocOption', {
      pct: Math.round(Number(dischargeSocDeltaPct)),
    });
    return {
      hint: t('selfConsumptionToggleHint', { lcoe: lcoeStr, tillSoc: tillSocLabel }),
      aria: t('selfConsumptionToggleAria', { lcoe: lcoeStr, tillSoc: tillSocLabel }),
    };
  }, [
    referenceLcoe.loading,
    referenceLcoe.ok,
    referenceLcoe.batteryUahPerKwh,
    formatUahPerKwhTariffLine,
    dischargeSocDeltaPct,
    t,
  ]);

  /** Peak DAM hint / aria: same till-SoC label as the discharge dropdown. */
  const peakDamHintWithTillSoc = useMemo(() => {
    const tillSocLabel = t('dischargeTillSocOption', {
      pct: Math.round(Number(dischargeSocDeltaPct)),
    });
    return {
      hint: t('peakDamDischargeToggleHint', { tillSoc: tillSocLabel }),
      aria: t('peakDamDischargeToggleAria', { tillSoc: tillSocLabel }),
    };
  }, [t, dischargeSocDeltaPct]);

  useEffect(() => {
    const fromUrl = readLandingExportMetricFromUrl(selInverterSn, selHuaweiStationCode, selEvPortsAcdc);
    if (fromUrl !== null) {
      setLandingExportMetric(fromUrl);
      writeStoredLandingExportMetric(selInverterSn, selHuaweiStationCode, fromUrl);
      landingExportMetricHydratedRef.current = true;
      return;
    }
    if (!landingExportMetricHydratedRef.current) {
      setLandingExportMetric(readStoredLandingExportMetric(selInverterSn, selHuaweiStationCode));
      landingExportMetricHydratedRef.current = true;
      return;
    }
    setLandingExportMetric(prev =>
      normalizeLandingExportMetricForContext(prev, selInverterSn, selHuaweiStationCode, selEvPortsAcdc)
    );
  }, [selInverterSn, selHuaweiStationCode, selEvPortsAcdc]);

  /** When user selects another Deye inverter, default the landing counter to total export (unless URL sets ``exportMetric``). */
  useEffect(() => {
    const hw = String(selHuaweiStationCode || '').trim();
    if (hw) {
      prevSelInverterSnForMetricRef.current = '';
      return;
    }
    const cur = String(selInverterSn || '').trim();
    const prev = prevSelInverterSnForMetricRef.current;
    if (prev === null) {
      prevSelInverterSnForMetricRef.current = cur;
      return;
    }
    if (prev === cur) return;
    prevSelInverterSnForMetricRef.current = cur;
    if (readLandingExportMetricFromUrl(selInverterSn, selHuaweiStationCode, selEvPortsAcdc) != null) return;
    const gridBalancingConfigured = Boolean(landingTotals?.ok && landingTotals?.gridBalancing?.configured !== false);
    const offers = {
      gridBalancing: gridBalancingConfigured,
      peak: !selHuaweiStationCode && landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.PEAK),
      manual: !selHuaweiStationCode && landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.MANUAL),
      total: landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.TOTAL),
      arbitrage:
        !selHuaweiStationCode && landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.ARBITRAGE),
      lostSolar:
        Boolean(selInverterSn?.trim()) &&
        landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.LOST_SOLAR_7D),
    };
    setLandingExportMetric(preferredLandingExportMetric(offers));
    writeStoredLandingExportMetric(selInverterSn, selHuaweiStationCode, preferredLandingExportMetric(offers));
  }, [selInverterSn, selHuaweiStationCode, landingTotals]);

  useEffect(() => {
    replaceLandingExportMetricInUrl(landingExportMetric);
  }, [landingExportMetric]);

  const landingExportMetricOffers = useMemo(() => {
    if (selEvPortsAcdc) {
      return {
        gridBalancing: false,
        peak: false,
        manual: false,
        total: false,
        arbitrage: false,
        lostSolar: false,
      };
    }
    const gridBalancingConfigured = Boolean(landingTotals?.ok && landingTotals?.gridBalancing?.configured !== false);
    return {
      gridBalancing: landingTotalsLoading || !landingTotals?.ok ? true : gridBalancingConfigured,
      peak: !selHuaweiStationCode && landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.PEAK),
      manual: !selHuaweiStationCode && landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.MANUAL),
      total: landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.TOTAL),
      arbitrage:
        !selHuaweiStationCode && landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.ARBITRAGE),
      lostSolar:
        Boolean(selInverterSn?.trim()) &&
        landingExportMetricHasPositiveValue(landingTotals, LANDING_EXPORT_METRIC.LOST_SOLAR_7D),
    };
  }, [selEvPortsAcdc, selHuaweiStationCode, selInverterSn, landingTotals, landingTotalsLoading]);

  useEffect(() => {
    if (landingTotalsLoading || !landingTotals?.ok) return;
    const unavailable =
      (landingExportMetric === LANDING_EXPORT_METRIC.GRID_BALANCING && !landingExportMetricOffers.gridBalancing) ||
      (landingExportMetric === LANDING_EXPORT_METRIC.PEAK && !landingExportMetricOffers.peak) ||
      (landingExportMetric === LANDING_EXPORT_METRIC.MANUAL && !landingExportMetricOffers.manual) ||
      (landingExportMetric === LANDING_EXPORT_METRIC.TOTAL && !landingExportMetricOffers.total) ||
      (landingExportMetric === LANDING_EXPORT_METRIC.ARBITRAGE && !landingExportMetricOffers.arbitrage) ||
      (landingExportMetric === LANDING_EXPORT_METRIC.LOST_SOLAR_7D && !landingExportMetricOffers.lostSolar);
    if (unavailable) {
      const next = preferredLandingExportMetric(landingExportMetricOffers);
      setLandingExportMetric(next);
      writeStoredLandingExportMetric(selInverterSn, selHuaweiStationCode, next);
    }
  }, [
    landingExportMetricOffers,
    landingExportMetric,
    selInverterSn,
    selHuaweiStationCode,
    landingTotalsLoading,
    landingTotals,
  ]);

  useEffect(() => {
    if (landingExportMetricDefaultedRef.current) return;
    if (landingTotalsLoading || !landingTotals?.ok) return;
    landingExportMetricDefaultedRef.current = true;
    if (readLandingExportMetricFromUrl(selInverterSn, selHuaweiStationCode, selEvPortsAcdc) != null) return;
    if (!landingExportMetricOffers.gridBalancing) return;
    if (landingExportMetric !== LANDING_EXPORT_METRIC.MONTHLY_RATES) return;
    setLandingExportMetric(LANDING_EXPORT_METRIC.GRID_BALANCING);
    writeStoredLandingExportMetric(selInverterSn, selHuaweiStationCode, LANDING_EXPORT_METRIC.GRID_BALANCING);
  }, [
    landingTotalsLoading,
    landingTotals,
    landingExportMetricOffers.gridBalancing,
    landingExportMetric,
    selInverterSn,
    selHuaweiStationCode,
  ]);

  const [exportHourlyChartOpen, setExportHourlyChartOpen] = useState(false);
  const [monthlyRatesChartOpen, setMonthlyRatesChartOpen] = useState(false);
  const [gridBalancingChartOpen, setGridBalancingChartOpen] = useState(false);
  const exportHourlyScope = useMemo(() => {
    if (landingExportMetric === LANDING_EXPORT_METRIC.PEAK) return 'peak';
    if (landingExportMetric === LANDING_EXPORT_METRIC.MANUAL) return 'manual';
    if (landingExportMetric === LANDING_EXPORT_METRIC.LOST_SOLAR_7D) return 'total';
    return 'total';
  }, [landingExportMetric]);
  const exportHourlyBarsUrl = useMemo(() => {
    const q = new URLSearchParams({ days: '7', hourlyScope: exportHourlyScope });
    const sn = selInverterSn?.trim();
    if (sn) q.set('deviceSn', sn);
    return apiUrl(`/api/power-flow/export-hourly-bars?${q}`);
  }, [selInverterSn, exportHourlyScope]);
  const lostSolarHourlyBarsUrl = useMemo(() => {
    const q = new URLSearchParams({ days: '7' });
    const sn = selInverterSn?.trim();
    if (sn) q.set('deviceSn', sn);
    return apiUrl(`/api/power-flow/lost-solar-hourly-bars?${q}`);
  }, [selInverterSn]);
  const peakHourlyChartFetchUrl = useMemo(
    () => (landingExportMetric === LANDING_EXPORT_METRIC.LOST_SOLAR_7D ? lostSolarHourlyBarsUrl : exportHourlyBarsUrl),
    [landingExportMetric, lostSolarHourlyBarsUrl, exportHourlyBarsUrl]
  );
  const monthlyRatesChartFetchUrl = useMemo(() => {
    const q = new URLSearchParams({ months: '12' });
    const sn = selInverterSn?.trim();
    const hw = selHuaweiStationCode?.trim();
    if (selEvPortsAcdc) q.set('evPortsAcdc', selEvPortsAcdc);
    else if (sn) q.set('deviceSn', sn);
    else if (hw) q.set('huaweiStationCode', hw);
    return apiUrl(`/api/power-flow/monthly-retail-tariff-bars?${q}`);
  }, [selInverterSn, selHuaweiStationCode, selEvPortsAcdc]);
  const gridBalancingChartFetchUrl = useMemo(() => {
    const q = new URLSearchParams({ months: '12' });
    const sn = selInverterSn?.trim();
    const hw = selHuaweiStationCode?.trim();
    if (sn) q.set('deviceSn', sn);
    else if (hw) q.set('huaweiStationCode', hw);
    return apiUrl(`/api/power-flow/monthly-grid-balancing-bars?${q}`);
  }, [selInverterSn, selHuaweiStationCode]);
  const peakHourlyChartKind = landingExportMetric === LANDING_EXPORT_METRIC.LOST_SOLAR_7D ? 'lostSolar' : 'export';

  /** No serial or prefs still loading — controls stay disabled (no click). Missing PIN in name: enabled, click opens modal. */
  const deyeWritesHardBlocked = !selInverterSn || toolbarPrefsLoading;
  /** Night charge mode: server forces self-consumption and disables peak / low DAM; UI locks other toolbar controls. */
  const toolbarLockedByNightCharge = nightChargeEnabled;

  const closeRemoteWriteNeedsPinModal = useCallback(() => {
    setRemoteWriteNeedsPinOpen(false);
  }, []);

  const [dischargeConfirmOpen, setDischargeConfirmOpen] = useState(false);
  const [chargeConfirmOpen, setChargeConfirmOpen] = useState(false);
  const [dischargeConfirmPin, setDischargeConfirmPin] = useState('');
  const [chargeConfirmPin, setChargeConfirmPin] = useState('');
  /** PIN gate for peak/low DAM toggles and depth dropdowns when inverter name encodes a PIN. */
  const [writePinGate, setWritePinGate] = useState(null);
  const [writePinValue, setWritePinValue] = useState('');
  const [writePinError, setWritePinError] = useState('');
  /** Deye charge/discharge: loading spinner then result in a follow-up modal. */
  const [deyeCommandModal, setDeyeCommandModal] = useState(null);
  /** Centered zoom popup for tapped flow nodes. */
  const [nodePopup, setNodePopup] = useState(null);
  const peakPrefSaveTimerRef = useRef(null);
  const chargePrefSaveTimerRef = useRef(null);
  const peakDamEnabledRef = useRef(false);
  const lowDamEnabledRef = useRef(false);

  const closeNodePopup = useCallback(() => {
    setNodePopup(null);
  }, []);

  const openNodePopup = useCallback((event, options = {}) => {
    if (!event?.currentTarget) return;
    event.preventDefault();
    event.stopPropagation();
    const html = String(event.currentTarget.innerHTML || '').replace(/\sid="[^"]*"/g, '');
    if (!html) return;
    setNodePopup({
      html,
      title: options.title ? String(options.title) : '',
      actionHref: options.actionHref ? String(options.actionHref) : '',
      actionLabel: options.actionLabel ? String(options.actionLabel) : '',
    });
  }, []);

  useEffect(() => {
    peakDamEnabledRef.current = peakDamDischargeEnabled;
  }, [peakDamDischargeEnabled]);

  useEffect(() => {
    lowDamEnabledRef.current = lowDamChargeEnabled;
  }, [lowDamChargeEnabled]);

  useEffect(() => {
    if (!nodePopup) return undefined;
    const onKeyDown = e => {
      if (e.key === 'Escape') closeNodePopup();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [nodePopup, closeNodePopup]);

  const applyNightChargeToolbarSnap = useCallback(snap => {
    if (!snap || typeof snap !== 'object') return;
    if (typeof snap.nightChargeEnabled === 'boolean') setNightChargeEnabled(snap.nightChargeEnabled);
    if (typeof snap.peakDamDischargeEnabled === 'boolean') setPeakDamDischargeEnabled(snap.peakDamDischargeEnabled);
    if (typeof snap.lowDamChargeEnabled === 'boolean') setLowDamChargeEnabled(snap.lowDamChargeEnabled);
    if (typeof snap.selfConsumptionEnabled === 'boolean') setSelfConsumptionEnabled(snap.selfConsumptionEnabled);
    if (snap.chargeSocDeltaPct != null && Number.isFinite(Number(snap.chargeSocDeltaPct))) {
      setChargeSocDeltaPct(normalizeChargeSocDeltaPct(snap.chargeSocDeltaPct));
    }
    if (snap.dischargeSocDeltaPct != null && Number.isFinite(Number(snap.dischargeSocDeltaPct))) {
      setDischargeSocDeltaPct(normalizeDischargeSocDeltaPct(snap.dischargeSocDeltaPct));
    }
  }, []);

  useEffect(() => {
    setDischarge2Feedback('');
    setDeyeCommandModal(null);
  }, [inverterValue]);

  useEffect(() => {
    if (peakPrefSaveTimerRef.current != null) {
      clearTimeout(peakPrefSaveTimerRef.current);
      peakPrefSaveTimerRef.current = null;
    }
    if (chargePrefSaveTimerRef.current != null) {
      clearTimeout(chargePrefSaveTimerRef.current);
      chargePrefSaveTimerRef.current = null;
    }
    if (!selInverterSn || inverterRows.error) {
      setPeakDamDischargeEnabled(false);
      setDischargeSocDeltaPct(80);
      setLowDamChargeEnabled(false);
      setChargeSocDeltaPct(10);
      setSelfConsumptionEnabled(false);
      setNightChargeEnabled(false);
      setToolbarPrefsLoading(false);
      return undefined;
    }
    if (inverterRows.loading) {
      return undefined;
    }
    if (!inverterRows.configured) {
      setPeakDamDischargeEnabled(false);
      setDischargeSocDeltaPct(80);
      setLowDamChargeEnabled(false);
      setChargeSocDeltaPct(10);
      setSelfConsumptionEnabled(false);
      setNightChargeEnabled(false);
      setToolbarPrefsLoading(false);
      return undefined;
    }
    let cancelled = false;
    const load = async () => {
      setToolbarPrefsLoading(true);
      try {
        const q = new URLSearchParams({ deviceSn: selInverterSn });
        const [rPeak, rLow, rSc, rNight] = await Promise.all([
          fetch(`${apiUrl('/api/deye/peak-auto-discharge')}?${q}`, { cache: 'no-store' }),
          fetch(`${apiUrl('/api/deye/low-dam-charge')}?${q}`, { cache: 'no-store' }),
          fetch(`${apiUrl('/api/deye/self-consumption')}?${q}`, { cache: 'no-store' }),
          fetch(`${apiUrl('/api/deye/night-charge')}?${q}`, { cache: 'no-store' }),
        ]);
        const dataPeak = await rPeak.json().catch(() => ({}));
        const dataLow = await rLow.json().catch(() => ({}));
        const dataSc = await rSc.json().catch(() => ({}));
        const dataNight = await rNight.json().catch(() => ({}));
        if (cancelled) return;
        if (rPeak.ok && dataPeak.ok && dataPeak.configured && typeof dataPeak.enabled === 'boolean') {
          setPeakDamDischargeEnabled(dataPeak.enabled);
        } else {
          setPeakDamDischargeEnabled(false);
        }
        const p = dataPeak.dischargeSocDeltaPct;
        if (p != null && Number.isFinite(Number(p))) {
          setDischargeSocDeltaPct(normalizeDischargeSocDeltaPct(p));
        } else {
          setDischargeSocDeltaPct(80);
        }
        if (rLow.ok && dataLow.ok && dataLow.configured && typeof dataLow.enabled === 'boolean') {
          setLowDamChargeEnabled(dataLow.enabled);
        } else {
          setLowDamChargeEnabled(false);
        }
        const pc = dataLow.chargeSocDeltaPct;
        if (pc != null && Number.isFinite(Number(pc))) {
          setChargeSocDeltaPct(normalizeChargeSocDeltaPct(pc));
        } else {
          setChargeSocDeltaPct(10);
        }
        if (rSc.ok && dataSc.ok && dataSc.configured) {
          const autoDam =
            typeof dataSc.enabled === 'boolean'
              ? dataSc.enabled
              : typeof dataSc.autoDamEnabled === 'boolean'
                ? dataSc.autoDamEnabled
                : false;
          const manualSc = typeof dataSc.selfConsumptionEnabled === 'boolean' ? dataSc.selfConsumptionEnabled : false;
          setSelfConsumptionEnabled(autoDam || manualSc);
        } else {
          setSelfConsumptionEnabled(false);
        }
        if (rNight.ok && dataNight.ok && dataNight.configured && typeof dataNight.nightChargeEnabled === 'boolean') {
          setNightChargeEnabled(dataNight.nightChargeEnabled);
          if (dataNight.nightChargeEnabled) {
            setSelfConsumptionEnabled(true);
          }
          if (
            dataNight.nightChargeEnabled &&
            dataNight.chargeSocDeltaPct != null &&
            Number.isFinite(Number(dataNight.chargeSocDeltaPct))
          ) {
            setChargeSocDeltaPct(normalizeChargeSocDeltaPct(dataNight.chargeSocDeltaPct));
          }
        } else {
          setNightChargeEnabled(false);
        }
      } catch {
        if (!cancelled) {
          setPeakDamDischargeEnabled(false);
          setDischargeSocDeltaPct(80);
          setLowDamChargeEnabled(false);
          setChargeSocDeltaPct(10);
          setSelfConsumptionEnabled(false);
          setNightChargeEnabled(false);
        }
      } finally {
        if (!cancelled) setToolbarPrefsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [selInverterSn, inverterRows.configured, inverterRows.error, inverterRows.loading]);

  const savePeakAutoPref = useCallback(
    async (nextEnabled, nextPct, pin) => {
      const sn = selInverterSn?.trim();
      if (!sn) return null;
      const body = {
        deviceSn: sn,
        enabled: nextEnabled,
        dischargeSocDeltaPct: nextPct,
      };
      const p = pin != null ? String(pin).trim() : '';
      if (p) body.pin = p;
      const r = await fetch(apiUrl('/api/deye/peak-auto-discharge'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) {
        if (r.status === 403) {
          clearInverterPinCache(sn);
          setPinCacheBust(x => x + 1);
        }
        let msg = data.detail ?? r.statusText;
        if (Array.isArray(msg)) {
          msg = msg.map(x => (x && typeof x === 'object' ? x.msg || JSON.stringify(x) : x)).join('; ');
        }
        throw new Error(String(msg || 'Save failed'));
      }
      if (p) {
        rememberInverterPin(sn, p);
        setPinCacheBust(x => x + 1);
      }
      return data;
    },
    [selInverterSn]
  );

  const saveLowDamChargePref = useCallback(
    async (nextEnabled, nextPct, pin) => {
      const sn = selInverterSn?.trim();
      if (!sn) return null;
      const body = {
        deviceSn: sn,
        enabled: nextEnabled,
        chargeSocDeltaPct: nextPct,
      };
      const p = pin != null ? String(pin).trim() : '';
      if (p) body.pin = p;
      const r = await fetch(apiUrl('/api/deye/low-dam-charge'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) {
        if (r.status === 403) {
          clearInverterPinCache(sn);
          setPinCacheBust(x => x + 1);
        }
        let msg = data.detail ?? r.statusText;
        if (Array.isArray(msg)) {
          msg = msg.map(x => (x && typeof x === 'object' ? x.msg || JSON.stringify(x) : x)).join('; ');
        }
        throw new Error(String(msg || 'Save failed'));
      }
      if (p) {
        rememberInverterPin(sn, p);
        setPinCacheBust(x => x + 1);
      }
      return data;
    },
    [selInverterSn]
  );

  const saveNightChargePref = useCallback(
    async (nextEnabled, nextPct, pin) => {
      const sn = selInverterSn?.trim();
      if (!sn) return null;
      const body = {
        deviceSn: sn,
        enabled: nextEnabled,
        chargeSocDeltaPct: nextPct,
      };
      const p = pin != null ? String(pin).trim() : '';
      if (p) body.pin = p;
      const r = await fetch(apiUrl('/api/deye/night-charge'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) {
        if (r.status === 403) {
          clearInverterPinCache(sn);
          setPinCacheBust(x => x + 1);
        }
        let msg = data.detail ?? r.statusText;
        if (Array.isArray(msg)) {
          msg = msg.map(x => (x && typeof x === 'object' ? x.msg || JSON.stringify(x) : x)).join('; ');
        }
        throw new Error(String(msg || 'Save failed'));
      }
      if (p) {
        rememberInverterPin(sn, p);
        setPinCacheBust(x => x + 1);
      }
      return data;
    },
    [selInverterSn]
  );

  const saveSelfConsumptionPref = useCallback(
    async (nextEnabled, pin) => {
      const sn = selInverterSn?.trim();
      if (!sn) return null;
      const body = { deviceSn: sn, enabled: nextEnabled };
      const p = pin != null ? String(pin).trim() : '';
      if (p) body.pin = p;
      const r = await fetch(apiUrl('/api/deye/self-consumption'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) {
        if (r.status === 403) {
          clearInverterPinCache(sn);
          setPinCacheBust(x => x + 1);
        }
        let msg = data.detail ?? r.statusText;
        if (Array.isArray(msg)) {
          msg = msg.map(x => (x && typeof x === 'object' ? x.msg || JSON.stringify(x) : x)).join('; ');
        }
        throw new Error(String(msg || 'Save failed'));
      }
      if (p) {
        rememberInverterPin(sn, p);
        setPinCacheBust(x => x + 1);
      }
      return data;
    },
    [selInverterSn]
  );

  useEffect(() => {
    if (!inverterRows.configured || inverterRows.items.length === 0) {
      setSocBySn({});
      setSocListLoading(false);
      return undefined;
    }
    const sns = inverterRows.items.map(r => r.deviceSn).filter(Boolean);
    if (sns.length === 0) {
      setSocBySn({});
      return undefined;
    }
    let cancelled = false;
    const loadSocs = async () => {
      setSocListLoading(true);
      try {
        const r = await fetch(apiUrl('/api/deye/inverter-socs'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ deviceSns: sns }),
          cache: 'no-store',
        });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        const next = {};
        if (r.ok && data.ok && Array.isArray(data.items)) {
          for (const it of data.items) {
            const sn = it.deviceSn != null ? String(it.deviceSn) : '';
            if (!sn) continue;
            const p = it.socPercent;
            next[sn] = p != null && Number.isFinite(Number(p)) ? Number(p) : null;
          }
        }
        setSocBySn(next);
      } catch {
        if (!cancelled) setSocBySn({});
      } finally {
        if (!cancelled) setSocListLoading(false);
      }
    };
    loadSocs();
    const id = setInterval(loadSocs, 300_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- inverterSnsKey tracks deviceSn set; avoids interval reset on new [] ref
  }, [inverterRows.configured, inverterSnsKey]);

  useEffect(() => {
    if (!selInverterSn || !inverterRows.configured || inverterRows.error) {
      setDeyeLive(null);
      setDeyeLiveLoading(false);
      return undefined;
    }
    let cancelled = false;
    const loadLive = async () => {
      setDeyeLiveLoading(true);
      try {
        const sns = selDeyeClusterSns.length > 0 ? selDeyeClusterSns : [selInverterSn];
        const rows = await Promise.all(
          sns.map(async sn => {
            const q = new URLSearchParams({ deviceSn: sn });
            const r = await fetch(`${apiUrl('/api/deye/ess-power')}?${q}`, { cache: 'no-store' });
            const data = await r.json().catch(() => ({}));
            return { ok: r.ok && data?.ok && data?.configured, data };
          })
        );
        if (cancelled) return;
        const okRows = rows.filter(x => x.ok).map(x => x.data);
        if (okRows.length > 0) {
          /*
           * Two cluster modes for multi-inverter Deye stations:
           *   1) Per-inverter mode — each /device/latest returns distinct watts → SUM across cluster.
           *   2) /station/latest fallback — every serial in the plant returns the same plant total.
           *      Backend marks these rows with stationFallback=true and stationId; we dedupe by
           *      stationId (one row per plant) so a 1 MWh station with N serials shows the plant
           *      total once instead of N × plant total. Falling back to exact-tuple dedup keeps
           *      the previous behaviour for older API versions that omit the new fields.
           */
          const uniqRows = [];
          const seenStationFallback = new Set();
          const seenTuple = new Set();
          for (const row of okRows) {
            const stId = row?.stationId == null ? '' : String(row.stationId).trim();
            if (row?.stationFallback === true && stId) {
              if (seenStationFallback.has(stId)) continue;
              seenStationFallback.add(stId);
              uniqRows.push(row);
              continue;
            }
            const tupleKey = [
              row?.batteryPowerW ?? 'n',
              row?.loadPowerW ?? 'n',
              row?.pvPowerW ?? 'n',
              row?.gridPowerW ?? 'n',
              row?.gridFrequencyHz ?? 'n',
            ].join('|');
            if (seenTuple.has(tupleKey)) continue;
            seenTuple.add(tupleKey);
            uniqRows.push(row);
          }
          const sumField = (key, floorZero = false) => {
            let has = false;
            let sum = 0;
            for (const row of uniqRows) {
              const v = row?.[key];
              if (v != null && Number.isFinite(Number(v))) {
                has = true;
                sum += Number(v);
              }
            }
            if (!has) return null;
            return floorZero ? Math.max(0, sum) : sum;
          };
          const bat = sumField('batteryPowerW', false);
          const loadW = sumField('loadPowerW', true);
          const pvW = sumField('pvPowerW', true);
          const gridW = sumField('gridPowerW', false);
          setDeyeLive({
            batteryPowerW: bat,
            loadPowerW: loadW,
            pvPowerW: pvW,
            gridPowerW: gridW,
          });
        } else {
          setDeyeLive(null);
        }
      } catch {
        if (!cancelled) setDeyeLive(null);
      } finally {
        if (!cancelled) setDeyeLiveLoading(false);
      }
    };
    loadLive();
    const id = setInterval(loadLive, 20_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selInverterSn, selDeyeClusterSns, inverterRows.configured, inverterRows.error]);

  useLayoutEffect(() => {
    setDeyeHydratedSn('');
    if (selInverterSn && inverterRows.configured && !inverterRows.error) {
      setDeyeLiveLoading(true);
    }
  }, [selInverterSn, inverterRows.configured, inverterRows.error]);

  useEffect(() => {
    if (!selInverterSn || !inverterRows.configured || inverterRows.error) {
      setDeyeHydratedSn('');
      return;
    }
    if (!deyeLiveLoading) {
      setDeyeHydratedSn(selInverterSn);
    }
  }, [selInverterSn, deyeLiveLoading, inverterRows.configured, inverterRows.error]);

  useEffect(() => {
    if (!selHuaweiStationCode || !huaweiRows.configured || huaweiRows.error || huaweiRows.authFailed) {
      setHuaweiLive(null);
      setHuaweiLiveLoading(false);
      return undefined;
    }
    let cancelled = false;
    const loadHuawei = async () => {
      setHuaweiLiveLoading(true);
      try {
        const q = new URLSearchParams({ stationCodes: selHuaweiStationCode });
        const r = await fetch(`${apiUrl('/api/huawei/power-flow')}?${q}`, { cache: 'no-store' });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (r.ok && data.ok && data.configured) {
          const pvW = data.pvPowerW;
          const gridW = data.gridPowerW;
          const loadW = data.loadPowerW;
          setHuaweiLive({
            ok: true,
            pvPowerW: pvW != null && Number.isFinite(Number(pvW)) ? Math.max(0, Number(pvW)) : null,
            gridPowerW: gridW != null && Number.isFinite(Number(gridW)) ? Number(gridW) : null,
            loadPowerW: loadW != null && Number.isFinite(Number(loadW)) ? Math.max(0, Number(loadW)) : null,
            northboundRateLimited: !!data.northboundRateLimited,
          });
        } else if (!data?.northboundRateLimited) {
          setHuaweiLive(null);
        }
      } catch {
        if (!cancelled) {
          // Keep last value on transient API/network errors to avoid dropping live power to zero.
        }
      } finally {
        if (!cancelled) setHuaweiLiveLoading(false);
      }
    };
    void loadHuawei();
    const id = setInterval(() => void loadHuawei(), HUAWEI_NORTHBOUND_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selHuaweiStationCode, huaweiRows.configured, huaweiRows.error, huaweiRows.authFailed]);

  useLayoutEffect(() => {
    setHuaweiHydratedCode('');
    if (selHuaweiStationCode && huaweiRows.configured && !huaweiRows.error && !huaweiRows.authFailed) {
      setHuaweiLiveLoading(true);
    }
  }, [selHuaweiStationCode, huaweiRows.configured, huaweiRows.error, huaweiRows.authFailed]);

  useEffect(() => {
    if (!selHuaweiStationCode || !huaweiRows.configured || huaweiRows.error || huaweiRows.authFailed) {
      setHuaweiHydratedCode('');
      return;
    }
    if (!huaweiLiveLoading) {
      setHuaweiHydratedCode(selHuaweiStationCode);
    }
  }, [selHuaweiStationCode, huaweiLiveLoading, huaweiRows.configured, huaweiRows.error, huaweiRows.authFailed]);

  useEffect(() => {
    if (!selEvPortsAcdc) {
      setEvPortsLive({ loading: false, powerW: null, activeSessions: 0, acdc: null });
      return undefined;
    }
    let cancelled = false;
    const acdc = selEvPortsAcdc;
    const load = async () => {
      setEvPortsLive(prev => ({ ...prev, loading: true, acdc }));
      try {
        const q = new URLSearchParams({ acdc });
        const r = await fetch(`${apiUrl('/api/b2b/ev-ports-power')}?${q}`, { cache: 'no-store' });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (r.ok && data?.ok && data.powerW != null && Number.isFinite(Number(data.powerW))) {
          setEvPortsLive({
            loading: false,
            powerW: Math.max(0, Number(data.powerW)),
            activeSessions: Number(data.activeSessions) || 0,
            acdc,
          });
        } else {
          setEvPortsLive({ loading: false, powerW: null, activeSessions: 0, acdc });
        }
      } catch {
        if (!cancelled) setEvPortsLive({ loading: false, powerW: null, activeSessions: 0, acdc });
      }
    };
    void load();
    const id = setInterval(() => void load(), 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selEvPortsAcdc]);

  useEffect(() => {
    if (!selInverterSn || !inverterRows.configured || inverterRows.error) {
      solarInsolationInitialFetchRef.current = true;
      setSolarForecast({
        loading: false,
        todayPct: null,
        todayCloudy: null,
        tomorrowPct: null,
        hintKey: null,
      });
      return undefined;
    }
    solarInsolationInitialFetchRef.current = true;
    let cancelled = false;
    const load = async () => {
      if (solarInsolationInitialFetchRef.current) {
        setSolarForecast({
          loading: true,
          todayPct: null,
          todayCloudy: null,
          tomorrowPct: null,
          hintKey: null,
        });
      }
      try {
        const q = new URLSearchParams({ deviceSn: selInverterSn });
        const r = await fetch(`${apiUrl('/api/deye/solar-insolation')}?${q}`, {
          cache: 'no-store',
        });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (!r.ok) {
          setSolarForecast({
            loading: false,
            todayPct: null,
            todayCloudy: null,
            tomorrowPct: null,
            hintKey: 'solarInsolationUnavailable',
          });
          return;
        }
        if (!data.configured) {
          setSolarForecast({
            loading: false,
            todayPct: null,
            todayCloudy: null,
            tomorrowPct: null,
            hintKey: null,
          });
          return;
        }
        const td = data.today;
        const tm = data.tomorrow;
        const tp = td?.insolationPct;
        const mp = tm?.insolationPct;
        if (data.ok && tp != null && mp != null && Number.isFinite(Number(tp)) && Number.isFinite(Number(mp))) {
          const cloudy = td?.cloudy;
          setSolarForecast({
            loading: false,
            todayPct: Math.max(0, Math.min(100, Math.round(Number(tp)))),
            todayCloudy: typeof cloudy === 'boolean' ? cloudy : null,
            tomorrowPct: Math.max(0, Math.min(100, Math.round(Number(mp)))),
            hintKey: null,
          });
          return;
        }
        const d = data.detail;
        if (d === 'no_station_coordinates') {
          setSolarForecast({
            loading: false,
            todayPct: null,
            todayCloudy: null,
            tomorrowPct: null,
            hintKey: 'solarInsolationNoCoords',
          });
        } else {
          setSolarForecast({
            loading: false,
            todayPct: null,
            todayCloudy: null,
            tomorrowPct: null,
            hintKey: 'solarInsolationUnavailable',
          });
        }
      } catch {
        if (!cancelled) {
          setSolarForecast({
            loading: false,
            todayPct: null,
            todayCloudy: null,
            tomorrowPct: null,
            hintKey: 'solarInsolationUnavailable',
          });
        }
      } finally {
        solarInsolationInitialFetchRef.current = false;
      }
    };
    void load();
    const id = setInterval(load, 3_600_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selInverterSn, inverterRows.configured, inverterRows.error]);

  const onStationChange = useCallback(e => {
    const v = e.target.value;
    setStationFilter(v);
    const u = new URL(window.location.href);
    const t = v.trim();
    if (t) u.searchParams.set('station', t);
    else u.searchParams.delete('station');
    window.history.replaceState({}, '', u);
  }, []);

  const openKiosk = useCallback(() => {
    try {
      const next = openEmsUrlWithKiosk(window.location.href);
      window.history.pushState({}, '', next);
      window.dispatchEvent(new PopStateEvent('popstate'));
    } catch {
      /* ignore */
    }
  }, []);

  const exitKiosk = useCallback(() => {
    try {
      const next = openEmsUrlWithoutKiosk(window.location.href);
      window.history.replaceState({}, '', next);
      window.dispatchEvent(new PopStateEvent('popstate'));
    } catch {
      /* ignore */
    }
  }, []);

  useScreenWakeLock(kioskMode);

  useEffect(() => {
    if (!kioskMode) return undefined;
    document.documentElement.classList.add('open-ems-kiosk');
    document.documentElement.setAttribute('data-theme', 'light');
    return () => {
      document.documentElement.classList.remove('open-ems-kiosk');
    };
  }, [kioskMode]);

  const kioskShareUrl = useMemo(
    () => (kioskMode ? pageShareUrlFromWindow({ stripParams: ['kiosk'] }) : ''),
    [kioskMode, stationFilter, locale, selInverterSn, selHuaweiStationCode, essSel.provider],
  );

  /** When the selected inverter label contains ``evport<N>``, select that EV port in the header dropdown. */
  useEffect(() => {
    if (inverterRows.loading || inverterRows.error || !inverterRows.configured) return;
    const sn = selInverterSn.trim();
    if (!sn) return;
    const row = inverterRows.items.find(r => r.deviceSn === sn);
    if (!row?.label) return;
    const evStation = parseEvPortStationNumber(row.label);
    if (!evStation) return;
    setStationFilter(prev => {
      if (prev.trim() === evStation) return prev;
      try {
        const u = new URL(window.location.href);
        u.searchParams.set('station', evStation);
        window.history.replaceState({}, '', u);
      } catch {
        /* ignore */
      }
      return evStation;
    });
  }, [selInverterSn, inverterRows.loading, inverterRows.error, inverterRows.configured, inverterRows.items]);

  const portSelectOptions = useMemo(() => {
    const base = chargingPorts.items;
    const s = stationFilter.trim();
    if (!s || base.some(x => String(x.number) === s)) {
      return base;
    }
    return [...base, { number: s, label: s, distanceMeters: null, powerWt: null, maxPowerWt: null }];
  }, [chargingPorts.items, stationFilter]);
  const evPortsUsedCount = chargingPorts.items.length;

  /** Prefer selected EV port tariff; else active-session weighted tariff; else 7-day network average. */
  const evDisplayTariffUahPerKwh = useMemo(() => {
    const selectedPort = stationFilter.trim();
    if (selectedPort) {
      const selected = chargingPorts.items.find(x => String(x?.number) === selectedPort);
      if (selected) {
        const selectedCostPerKwt = Number(selected?.costPerKwt);
        if (Number.isFinite(selectedCostPerKwt) && selectedCostPerKwt > 0) {
          return selectedCostPerKwt / 100.0;
        }
        const selectedTariffUahPerKwh = Number(selected?.tariffUahPerKwh);
        if (Number.isFinite(selectedTariffUahPerKwh) && selectedTariffUahPerKwh > 0) {
          return selectedTariffUahPerKwh;
        }
      }
    }
    const fromSessions = volumeWeightedActiveEvSessionTariffUahPerKwh(chargingPorts.items);
    if (fromSessions != null && Number.isFinite(fromSessions)) return fromSessions;
    if (
      !evChargingNetworkTariff.loading &&
      evChargingNetworkTariff.value != null &&
      Number.isFinite(evChargingNetworkTariff.value)
    ) {
      return evChargingNetworkTariff.value;
    }
    return null;
  }, [chargingPorts.items, stationFilter, evChargingNetworkTariff.loading, evChargingNetworkTariff.value]);

  const consumptionMw = realtimePower?.powerMw ?? 0;
  const liveMinerW =
    minerSnap?.configured && minerSnap.powerW != null && Number.isFinite(minerSnap.powerW)
      ? Math.max(0, minerSnap.powerW)
      : null;

  /* simTick triggers a periodic re-render so Kyiv-time simulation updates */
  void simTick;
  const sim = essAnySelected
    ? { solarW: 0, gridW: 0, essW: 0, minerW: 0, consumptionW: 0 }
    : computeSimulatedSources(consumptionMw, liveMinerW);

  const { solarW, gridW, essW, minerW, consumptionW } = sim;

  const fleetDeyeAggregateActive =
    !essAnySelected && inverterRows.configured && !inverterRows.error && fleetDeyeAggregate.okResponses > 0;
  const fleetHuaweiTelemetryActive =
    !essAnySelected &&
    huaweiRows.configured &&
    !huaweiRows.error &&
    !huaweiRows.authFailed &&
    fleetHuaweiAggregate.okResponses > 0;
  /** Live fleet PV: sum Deye + Huawei (and future backends — extend fleetSolarPvW). */
  const fleetSolarTelemetryActive = fleetDeyeAggregateActive || fleetHuaweiTelemetryActive;
  const fleetSolarPvW =
    (fleetDeyeAggregateActive ? fleetDeyeAggregate.pvW : 0) +
    (fleetHuaweiTelemetryActive ? fleetHuaweiAggregate.pvW : 0);
  /** Live fleet load: sum Deye + Huawei (extend fleetLoadW for new ESS backends). */
  const fleetLoadTelemetryActive = fleetDeyeAggregateActive || fleetHuaweiTelemetryActive;
  const fleetLoadW =
    (fleetDeyeAggregateActive ? fleetDeyeAggregate.loadW : 0) +
    (fleetHuaweiTelemetryActive ? fleetHuaweiAggregate.loadW : 0);
  /** Live fleet battery (signed): sum Deye + Huawei batteryPowerW when present on power-flow. */
  const fleetBatteryTelemetryActive = fleetDeyeAggregateActive || fleetHuaweiTelemetryActive;
  const fleetBatteryW =
    (fleetDeyeAggregateActive ? fleetDeyeAggregate.batteryW : 0) +
    (fleetHuaweiTelemetryActive ? fleetHuaweiAggregate.batteryW : 0);

  /** B2B aggregate charging power (W) from 220-km when /realtime-power has been received (powerMw in MW). */
  const b2bAggregateEvChargingW =
    realtimePower != null && Number.isFinite(Number(realtimePower.powerMw))
      ? Math.max(0, Number(realtimePower.powerMw) * 1e6)
      : null;
  /** Fleet aggregate EV: 220-km B2B only (no inverter grid emulation). */
  const aggregateEvFlowW = !essAnySelected ? (b2bAggregateEvChargingW != null ? b2bAggregateEvChargingW : 0) : 0;

  const useLivePvDeye = Boolean(selInverterSn) && deyeLive?.pvPowerW != null && Number.isFinite(deyeLive.pvPowerW);
  const useLivePvHuawei =
    Boolean(selHuaweiStationCode) && huaweiLive?.pvPowerW != null && Number.isFinite(huaweiLive.pvPowerW);
  const useLivePv = useLivePvDeye || useLivePvHuawei;
  const rawPvW = useLivePvDeye
    ? Math.max(0, deyeLive.pvPowerW)
    : useLivePvHuawei
      ? Math.max(0, huaweiLive.pvPowerW)
      : null;
  const rawDisplaySolarW = essAnySelected
    ? useLivePv
      ? rawPvW
      : null
    : fleetSolarTelemetryActive
      ? fleetSolarPvW
      : solarW;
  const displaySolarW =
    rawDisplaySolarW != null && usesDeyeFlowBalance(selInverterSn)
      ? rawDisplaySolarW * DEYE_FLOW_BALANCE_PV_FACTOR
      : rawDisplaySolarW;
  /** Aggregate EV charging (B2B) is misleading next to a single site — hide when an inverter/plant is selected. */
  const showEvAggregate = !essAnySelected;
  const useLiveGridDeye =
    Boolean(selInverterSn) && deyeLive?.gridPowerW != null && Number.isFinite(deyeLive.gridPowerW);
  const useLiveGridHuawei =
    Boolean(selHuaweiStationCode) && huaweiLive?.gridPowerW != null && Number.isFinite(huaweiLive.gridPowerW);
  /** No fleet ESS selected: do not sum inverter grid — hub grid is derived from balance below. */
  const effectiveGridW = essAnySelected
    ? useLiveGridHuawei
      ? huaweiLive.gridPowerW
      : useLiveGridDeye
        ? deyeLive.gridPowerW
        : null
    : gridW;
  const useLiveEss =
    Boolean(selInverterSn) && deyeLive?.batteryPowerW != null && Number.isFinite(deyeLive.batteryPowerW);
  const displayEssW = essAnySelected
    ? useLiveEss
      ? deyeLive.batteryPowerW
      : null
    : fleetBatteryTelemetryActive
      ? fleetBatteryW
      : essW;
  /** Miner: B2B /api/b2b/miner-power (220-km) only — no simulated miner in fleet view. */
  const displayMinerW = liveMinerW;
  const minerFlowW = liveMinerW ?? 0;
  const displayLoadW = fleetLoadTelemetryActive
    ? fleetLoadW
    : Boolean(selHuaweiStationCode) && huaweiLive?.loadPowerW != null && Number.isFinite(huaweiLive.loadPowerW)
      ? Math.max(0, huaweiLive.loadPowerW)
      : Boolean(selInverterSn) && deyeLive?.loadPowerW != null && Number.isFinite(deyeLive.loadPowerW)
        ? Math.max(0, deyeLive.loadPowerW)
        : null;
  const useSpecialGridBalance =
    usesDeyeFlowBalance(selInverterSn) && displaySolarW != null && displayEssW != null && displayLoadW != null;
  /**
   * Fleet hub: Deye ``batteryPowerW`` signed (+ discharge, − charge). Card uses ``abs(battery)``.
   * Closure: solar + grid + battery = load + EV + miner  ⇔  grid = load + EV + miner − battery − solar.
   */
  const fleetCompensatedGridW =
    !essAnySelected &&
    fleetSolarTelemetryActive &&
    fleetLoadTelemetryActive &&
    fleetBatteryTelemetryActive &&
    displaySolarW != null &&
    Number.isFinite(displaySolarW) &&
    displayLoadW != null &&
    Number.isFinite(displayLoadW) &&
    displayEssW != null &&
    Number.isFinite(displayEssW)
      ? displayLoadW + aggregateEvFlowW + minerFlowW - displayEssW - displaySolarW
      : null;
  const displayGridW = useSpecialGridBalance
    ? displayLoadW - displaySolarW - displayEssW
    : fleetCompensatedGridW != null
      ? fleetCompensatedGridW
      : effectiveGridW;

  /** B2B EV port selected without a site ESS: diagram is virtual grid → EV only (220-km station power). */
  const evPortFocusMode = !essAnySelected && Boolean(stationFilter.trim());
  /** EV DC/AC aggregate selected as ESS source: grid → all active sessions of that type. */
  const evPortsFocusMode = selEvPortsAggregate;
  const evOnlyFocusMode = evPortFocusMode || evPortsFocusMode;
  const evPortsDisplayPowerW = evPortsFocusMode
    ? evPortsLive.loading && evPortsLive.powerW == null
      ? null
      : Math.max(0, Number(evPortsLive.powerW ?? 0))
    : null;
  const evOnlyGraphLoading =
    (evPortFocusMode && evStationPowerLoading && evStationPowerW == null) ||
    (evPortsFocusMode && evPortsLive.loading && evPortsDisplayPowerW == null);
  const graphDisplaySolarW = evOnlyFocusMode ? null : displaySolarW;
  const graphDisplayLoadW = evOnlyFocusMode ? null : displayLoadW;
  const graphDisplayEssW = evOnlyFocusMode ? null : displayEssW;
  const graphDisplayMinerW = evOnlyFocusMode ? null : displayMinerW;
  const graphMinerFlowW = evOnlyFocusMode ? 0 : minerFlowW;
  const graphDisplayGridW = evPortFocusMode
    ? evStationPowerLoading && evStationPowerW == null
      ? null
      : Math.max(0, Number(evStationPowerW ?? 0))
    : evPortsFocusMode
      ? evPortsDisplayPowerW
      : displayGridW;
  const graphDisplayEssCharging = graphDisplayEssW != null && graphDisplayEssW < 0;

  const loadFlowActive = graphDisplayLoadW != null && graphDisplayLoadW > 0;
  const solarFlowActive = graphDisplaySolarW != null && graphDisplaySolarW > 0;
  const solarForecastIconChar =
    selInverterSn && !solarForecast.loading && solarForecast.todayCloudy === true ? '🌤️' : '☀️';
  const solarForecastIconAria =
    selInverterSn && !solarForecast.loading && solarForecast.todayPct != null
      ? solarForecast.todayCloudy === true
        ? t('solarForecastIconAriaCloudy')
        : t('solarForecastIconAriaClear')
      : undefined;
  const gridFlowActive = graphDisplayGridW != null && Math.abs(graphDisplayGridW) > 0;
  const gridSelling = graphDisplayGridW != null && graphDisplayGridW < 0;
  const stationEvFlowActive = !showEvAggregate && Boolean(stationFilter.trim()) && (evStationPowerW ?? 0) > 0;
  const evFlowActive =
    (evPortFocusMode && (evStationPowerW ?? 0) > 0) ||
    (evPortsFocusMode && (evPortsDisplayPowerW ?? 0) > 0) ||
    (showEvAggregate && !evOnlyFocusMode && aggregateEvFlowW > 0) ||
    stationEvFlowActive;
  const hasFlow =
    evFlowActive ||
    gridFlowActive ||
    solarFlowActive ||
    loadFlowActive ||
    (graphDisplayEssW != null && Math.abs(graphDisplayEssW) > 0) ||
    graphMinerFlowW > 0;
  const geom = useMemo(() => computeWideGeometry(graphWidth, { kiosk: kioskMode }), [graphWidth, kioskMode]);
  const graphAnchorPct = useMemo(
    () => (edgeInsetPx(graphWidth, { kiosk: kioskMode }) / Math.max(graphWidth, 1)) * 100,
    [graphWidth, kioskMode],
  );
  const gridDamMonthAvgUahPerKwh = useMemo(() => {
    const dam = landingTotals?.dam;
    if (!dam?.configured) return null;
    const x = dam.currentAvgUahPerKwh;
    return typeof x === 'number' && Number.isFinite(x) ? x : null;
  }, [landingTotals]);

  const gridDamTariffUahPerKwh = useMemo(() => {
    const today = kyivCalendarIsoForDam();
    const h = kyivWallHour0to23();
    const snap = damKyivTodayHourly;
    if (
      !snap.loading &&
      snap.oreeConfigured &&
      snap.tradeDayIso === today &&
      snap.hourlyUahPerKwh &&
      snap.hourlyUahPerKwh.length >= 24 &&
      h != null
    ) {
      const raw = snap.hourlyUahPerKwh[h];
      const n = Number(raw);
      if (Number.isFinite(n)) return n;
    }
    return gridDamMonthAvgUahPerKwh;
  }, [damKyivTodayHourly, gridDamMonthAvgUahPerKwh]);

  const gBuy = geom.gridLine;
  const gSell = geom.gridLineSelling;

  const gridLineCoords = gridSelling
    ? { ...gSell, active: hasFlow && gridFlowActive }
    : { ...gBuy, active: hasFlow && gridFlowActive };

  const gridDotPath = gridSelling
    ? flowMotionPath(gSell.start.x, gSell.start.y, gSell.end.x, gSell.end.y)
    : flowMotionPath(gBuy.start.x, gBuy.start.y, gBuy.end.x, gBuy.end.y);

  const essActive = hasFlow && graphDisplayEssW != null && Math.abs(graphDisplayEssW) > 0;
  /** Motion dots that travel *into* the hub (line ends at EMS): solar, grid import, ESS discharge. */
  const hubLogoInboundFlow =
    solarFlowActive || (!gridSelling && gridLineCoords.active) || (essActive && !graphDisplayEssCharging);
  const essCoords = graphDisplayEssCharging ? geom.essLineCharging : geom.essLine;
  const essPath = graphDisplayEssCharging
    ? flowMotionPath(
        geom.essLineCharging.start.x,
        geom.essLineCharging.start.y,
        geom.essLineCharging.end.x,
        geom.essLineCharging.end.y
      )
    : flowMotionPath(geom.essLine.start.x, geom.essLine.start.y, geom.essLine.end.x, geom.essLine.end.y);

  const tf = minerSnap?.tariffUahPerKwh;
  const minerLabel = t('nodeMiner');

  const fleetDeyePollBusy =
    showEvAggregate &&
    !essAnySelected &&
    inverterRows.configured &&
    !inverterRows.error &&
    inverterRows.items.some(r => String(r.deviceSn || '').trim()) &&
    fleetDeyeAggregate.loading &&
    fleetDeyeAggregate.okResponses === 0;
  const evBusy = fleetDeyePollBusy;
  const qrBase = process.env.PUBLIC_URL || '';

  const essSocPercent = useMemo(() => {
    const sn = selInverterSn.trim();
    if (!sn) return undefined;
    const row = deyeCombinedItems.find(r => r.representativeSn === sn);
    const order = row
      ? [
          sn,
          ...row.clusterSns
            .map(x => String(x || '').trim())
            .filter(Boolean)
            .filter(x => x !== sn),
        ]
      : [sn];
    for (const s of order) {
      const v = socBySn[s];
      if (v != null && Number.isFinite(Number(v))) return Number(v);
    }
    return undefined;
  }, [selInverterSn, deyeCombinedItems, socBySn]);
  const essSocHasKey = essSocPercent != null && Number.isFinite(essSocPercent);
  const essSocPending = Boolean(selInverterSn.trim() && essSocPercent == null && socListLoading);

  /** Same rule as ``requestDischarge2Pct``: no headroom to discharge toward the selected floor. */
  const dischargeGoDisabledInsufficientSoc = useMemo(() => {
    if (!essSocHasKey || essSocPercent == null || !Number.isFinite(Number(essSocPercent))) {
      return false;
    }
    const cur = Number(essSocPercent);
    const targetSoc = Math.round(Number(dischargeSocDeltaPct));
    return cur <= targetSoc + 0.05;
  }, [essSocHasKey, essSocPercent, dischargeSocDeltaPct]);

  const dischargeGoHoverTitle = useMemo(() => {
    const sn = selInverterSn.trim();
    if (sn && !essSocHasKey) {
      return t('dischargeConfirmNoSoc');
    }
    if (dischargeGoDisabledInsufficientSoc && essSocHasKey) {
      return t('dischargeGoDisabledTooltip', {
        target: inverterSocFmt.format(Math.round(Number(dischargeSocDeltaPct))),
      });
    }
    return t('dischargeSoc2Hint');
  }, [
    selInverterSn,
    essSocHasKey,
    dischargeGoDisabledInsufficientSoc,
    essSocPercent,
    dischargeSocDeltaPct,
    inverterSocFmt,
    t,
  ]);

  const clearDischargeHoverTipTimer = useCallback(() => {
    if (dischargeHoverTipTimerRef.current != null) {
      clearTimeout(dischargeHoverTipTimerRef.current);
      dischargeHoverTipTimerRef.current = null;
    }
  }, []);

  const onDischargeGoWrapMouseEnter = useCallback(() => {
    clearDischargeHoverTipTimer();
    dischargeHoverTipTimerRef.current = window.setTimeout(() => {
      dischargeHoverTipTimerRef.current = null;
      setDischargeHoverTipText(dischargeGoHoverTitle);
      setDischargeHoverTipOpen(true);
    }, 1000);
  }, [clearDischargeHoverTipTimer, dischargeGoHoverTitle]);

  const onDischargeGoWrapMouseLeave = useCallback(() => {
    clearDischargeHoverTipTimer();
    setDischargeHoverTipOpen(false);
  }, [clearDischargeHoverTipTimer]);

  useEffect(() => () => clearDischargeHoverTipTimer(), [clearDischargeHoverTipTimer]);

  useEffect(() => {
    clearDischargeHoverTipTimer();
    setDischargeHoverTipOpen(false);
  }, [selInverterSn, clearDischargeHoverTipTimer]);

  const executeDischarge2Pct = useCallback(
    async (commandPin = '') => {
      const deviceSn = selInverterSn?.trim();
      if (!deviceSn || discharge2BusyRef.current) return null;
      discharge2BusyRef.current = true;
      setDischarge2Feedback('');
      try {
        const socDeltaPercent = effectiveDischargeDeltaForApi(dischargeSocDeltaPct, essSocPercent);
        const body = {
          deviceSn,
          socDeltaPercent,
          respondAfterStart: true,
        };
        const p = String(commandPin ?? '').trim();
        if (p) body.pin = p;
        const r = await fetch(apiUrl('/api/deye/discharge-2pct'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          cache: 'no-store',
        });
        let data = {};
        try {
          data = await r.json();
        } catch {
          /* ignore */
        }
        if (!r.ok) {
          if (r.status === 403) {
            clearInverterPinCache(deviceSn);
            setPinCacheBust(x => x + 1);
          }
          let msg = data.detail ?? data.msg ?? r.statusText;
          if (Array.isArray(msg)) {
            msg = msg.map(x => (x && typeof x === 'object' ? x.msg || JSON.stringify(x) : x)).join('; ');
          }
          throw new Error(String(msg || 'Request failed'));
        }
        if (!data.ok) {
          throw new Error(String(data.detail || 'Discharge not started'));
        }
        if (p) {
          rememberInverterPin(deviceSn, p);
          setPinCacheBust(x => x + 1);
        }
        const from =
          data.startSoc != null && Number.isFinite(Number(data.startSoc))
            ? inverterSocFmt.format(Number(data.startSoc))
            : '—';
        const to =
          data.lastSoc != null && Number.isFinite(Number(data.lastSoc))
            ? inverterSocFmt.format(Number(data.lastSoc))
            : '—';
        const startN = Number(data.startSoc);
        const lastN = Number(data.lastSoc);
        const reportedSocFlat = Number.isFinite(startN) && Number.isFinite(lastN) && Math.abs(startN - lastN) < 0.2;
        const detail = data.respondAfterStart
          ? t('deyeCommandContinuesBackground')
          : data.hitTarget
            ? t('dischargeSoc2Ok', { from, to })
            : reportedSocFlat
              ? t('dischargeSoc2PartialFlat', { from, to })
              : t('dischargeSoc2Partial', { from, to });
        const message = `${t('commandSentStatus')}\n\n${detail}`;
        try {
          const rs = await fetch(apiUrl(`/api/deye/soc?${new URLSearchParams({ deviceSn })}`), { cache: 'no-store' });
          const js = await rs.json();
          if (rs.ok && js.socPercent != null && Number.isFinite(Number(js.socPercent))) {
            setSocBySn(prev => ({
              ...prev,
              [deviceSn]: Number(js.socPercent),
            }));
          }
        } catch {
          /* ignore */
        }
        return { ok: true, message };
      } catch (e) {
        const err = e instanceof Error ? e.message : String(e);
        return { ok: false, message: `${t('dischargeSoc2Error')}: ${err}` };
      } finally {
        discharge2BusyRef.current = false;
      }
    },
    [selInverterSn, inverterSocFmt, t, dischargeSocDeltaPct, essSocPercent]
  );

  const executeCharge2Pct = useCallback(
    async (commandPin = '') => {
      const deviceSn = selInverterSn?.trim();
      if (!deviceSn || charge2BusyRef.current) return null;
      charge2BusyRef.current = true;
      setDischarge2Feedback('');
      try {
        const body = {
          deviceSn,
          socDeltaPercent: chargeSocDeltaPct,
          respondAfterStart: true,
        };
        const p = String(commandPin ?? '').trim();
        if (p) body.pin = p;
        const r = await fetch(apiUrl('/api/deye/charge-2pct'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          cache: 'no-store',
        });
        let data = {};
        try {
          data = await r.json();
        } catch {
          /* ignore */
        }
        if (!r.ok) {
          if (r.status === 403) {
            clearInverterPinCache(deviceSn);
            setPinCacheBust(x => x + 1);
          }
          let msg = data.detail ?? data.msg ?? r.statusText;
          if (Array.isArray(msg)) {
            msg = msg.map(x => (x && typeof x === 'object' ? x.msg || JSON.stringify(x) : x)).join('; ');
          }
          throw new Error(String(msg || 'Request failed'));
        }
        if (!data.ok) {
          throw new Error(String(data.detail || 'Charge not started'));
        }
        if (p) {
          rememberInverterPin(deviceSn, p);
          setPinCacheBust(x => x + 1);
        }
        const from =
          data.startSoc != null && Number.isFinite(Number(data.startSoc))
            ? inverterSocFmt.format(Number(data.startSoc))
            : '—';
        const to =
          data.lastSoc != null && Number.isFinite(Number(data.lastSoc))
            ? inverterSocFmt.format(Number(data.lastSoc))
            : '—';
        const startN = Number(data.startSoc);
        const lastN = Number(data.lastSoc);
        const reportedSocFlat = Number.isFinite(startN) && Number.isFinite(lastN) && Math.abs(startN - lastN) < 0.2;
        const detail = data.respondAfterStart
          ? t('deyeChargeStarted')
          : data.hitTarget
            ? t('chargeSoc2Ok', { from, to })
            : reportedSocFlat
              ? t('chargeSoc2PartialFlat', { from, to })
              : t('chargeSoc2Partial', { from, to });
        const message = `${t('commandSentStatus')}\n\n${detail}`;
        try {
          const rs = await fetch(apiUrl(`/api/deye/soc?${new URLSearchParams({ deviceSn })}`), { cache: 'no-store' });
          const js = await rs.json();
          if (rs.ok && js.socPercent != null && Number.isFinite(Number(js.socPercent))) {
            setSocBySn(prev => ({
              ...prev,
              [deviceSn]: Number(js.socPercent),
            }));
          }
        } catch {
          /* ignore */
        }
        return { ok: true, message };
      } catch (e) {
        const err = e instanceof Error ? e.message : String(e);
        return { ok: false, message: `${t('chargeSoc2Error')}: ${err}` };
      } finally {
        charge2BusyRef.current = false;
      }
    },
    [selInverterSn, inverterSocFmt, t, chargeSocDeltaPct]
  );

  const requestDischarge2Pct = useCallback(() => {
    const deviceSn = selInverterSn?.trim();
    if (!deviceSn || discharge2BusyRef.current) return;
    if (!remoteWriteConfigured) {
      setRemoteWriteNeedsPinOpen(true);
      return;
    }
    if (!essSocHasKey || essSocPercent == null || !Number.isFinite(Number(essSocPercent))) {
      setDischarge2Feedback(t('dischargeConfirmNoSoc'));
      return;
    }
    const cur = Number(essSocPercent);
    const targetSoc = Math.round(Number(dischargeSocDeltaPct));
    const deltaNeeded = effectiveDischargeDeltaForApi(targetSoc, cur);
    if (deltaNeeded < 1 || cur <= targetSoc + 0.05) {
      setDischarge2Feedback(
        t('dischargeConfirmInsufficientSoc', {
          current: inverterSocFmt.format(cur),
          target: inverterSocFmt.format(targetSoc),
        })
      );
      return;
    }
    setDischarge2Feedback('');
    setDischargeConfirmPin('');
    setDischargeConfirmOpen(true);
  }, [selInverterSn, remoteWriteConfigured, essSocHasKey, essSocPercent, dischargeSocDeltaPct, inverterSocFmt, t]);

  const requestCharge2Pct = useCallback(() => {
    const deviceSn = selInverterSn?.trim();
    if (!deviceSn || charge2BusyRef.current) return;
    if (!remoteWriteConfigured) {
      setRemoteWriteNeedsPinOpen(true);
      return;
    }
    if (!essSocHasKey || essSocPercent == null || !Number.isFinite(Number(essSocPercent))) {
      setDischarge2Feedback(t('chargeConfirmNoSoc'));
      return;
    }
    const cur = Number(essSocPercent);
    const target = Math.min(100, cur + chargeSocDeltaPct);
    if (cur >= target - 0.06) {
      setDischarge2Feedback(t('chargeConfirmNoHeadroom'));
      return;
    }
    setDischarge2Feedback('');
    setChargeConfirmPin('');
    setChargeConfirmOpen(true);
  }, [selInverterSn, remoteWriteConfigured, essSocHasKey, essSocPercent, chargeSocDeltaPct, t]);

  const cancelDischargeConfirm = useCallback(() => {
    setDischargeConfirmOpen(false);
    setDischargeConfirmPin('');
  }, []);

  const confirmDischargeFromModal = useCallback(() => {
    const pinForCmd = (cachedWritePin || dischargeConfirmPin).trim();
    if (selInverterPinRequired && !pinForCmd) {
      setDischarge2Feedback(t('deyeWritePinMissing'));
      return;
    }
    setDischarge2Feedback('');
    setDischargeConfirmOpen(false);
    setDischargeConfirmPin('');
    setDeyeCommandModal({ phase: 'loading', kind: 'discharge' });
    void (async () => {
      const out = await executeDischarge2Pct(pinForCmd);
      if (out == null) {
        setDeyeCommandModal(null);
        return;
      }
      setDeyeCommandModal({
        phase: 'result',
        kind: 'discharge',
        ok: out.ok,
        message: out.message,
      });
    })();
  }, [executeDischarge2Pct, selInverterPinRequired, dischargeConfirmPin, cachedWritePin, t]);

  const cancelChargeConfirm = useCallback(() => {
    setChargeConfirmOpen(false);
    setChargeConfirmPin('');
  }, []);

  const confirmChargeFromModal = useCallback(() => {
    const pinForCmd = (cachedWritePin || chargeConfirmPin).trim();
    if (selInverterPinRequired && !pinForCmd) {
      setDischarge2Feedback(t('deyeWritePinMissing'));
      return;
    }
    setDischarge2Feedback('');
    setChargeConfirmOpen(false);
    setChargeConfirmPin('');
    setDeyeCommandModal({ phase: 'loading', kind: 'charge' });
    void (async () => {
      const out = await executeCharge2Pct(pinForCmd);
      if (out == null) {
        setDeyeCommandModal(null);
        return;
      }
      setDeyeCommandModal({
        phase: 'result',
        kind: 'charge',
        ok: out.ok,
        message: out.message,
      });
    })();
  }, [executeCharge2Pct, selInverterPinRequired, chargeConfirmPin, cachedWritePin, t]);

  const cancelWritePinGate = useCallback(() => {
    setWritePinGate(null);
    setWritePinValue('');
    setWritePinError('');
  }, []);

  const submitWritePinGate = useCallback(async () => {
    const pin = writePinValue.trim();
    if (!writePinGate) return;
    const g = writePinGate;
    if (!pin && !selInverterEvportBound) {
      setWritePinError(t('deyeWritePinMissing'));
      return;
    }
    setWritePinError('');
    try {
      if (g.kind === 'peak') {
        const data = await savePeakAutoPref(g.nextEnabled, g.nextPct, pin);
        if (data && typeof data.enabled === 'boolean') {
          setPeakDamDischargeEnabled(data.enabled);
        }
        const p = data?.dischargeSocDeltaPct;
        if (p != null && Number.isFinite(Number(p))) {
          setDischargeSocDeltaPct(normalizeDischargeSocDeltaPct(p));
        }
      } else if (g.kind === 'low') {
        const data = await saveLowDamChargePref(g.nextEnabled, g.nextPct, pin);
        if (data && typeof data.enabled === 'boolean') {
          setLowDamChargeEnabled(data.enabled);
        }
        const p = data?.chargeSocDeltaPct;
        if (p != null && Number.isFinite(Number(p))) {
          setChargeSocDeltaPct(normalizeChargeSocDeltaPct(p));
        }
      } else if (g.kind === 'peakPct') {
        const data = await savePeakAutoPref(peakDamEnabledRef.current, g.nextPct, pin);
        if (data && typeof data.enabled === 'boolean') {
          setPeakDamDischargeEnabled(data.enabled);
        }
        const p = data?.dischargeSocDeltaPct;
        if (p != null && Number.isFinite(Number(p))) {
          setDischargeSocDeltaPct(normalizeDischargeSocDeltaPct(p));
        } else {
          setDischargeSocDeltaPct(normalizeDischargeSocDeltaPct(g.nextPct));
        }
      } else if (g.kind === 'lowPct') {
        const data = await saveLowDamChargePref(lowDamEnabledRef.current, g.nextPct, pin);
        if (data && typeof data.enabled === 'boolean') {
          setLowDamChargeEnabled(data.enabled);
        }
        const p = data?.chargeSocDeltaPct;
        if (p != null && Number.isFinite(Number(p))) {
          setChargeSocDeltaPct(normalizeChargeSocDeltaPct(p));
        } else {
          setChargeSocDeltaPct(g.nextPct);
        }
      } else if (g.kind === 'selfConsumption') {
        const data = await saveSelfConsumptionPref(g.nextEnabled, pin);
        if (data && typeof data.selfConsumptionEnabled === 'boolean') {
          setSelfConsumptionEnabled(data.selfConsumptionEnabled);
        } else if (data && typeof data.enabled === 'boolean') {
          setSelfConsumptionEnabled(data.enabled);
        }
      } else if (g.kind === 'nightCharge') {
        const data = await saveNightChargePref(g.nextEnabled, g.nextPct, pin);
        applyNightChargeToolbarSnap(data);
      }
      setWritePinGate(null);
      setWritePinValue('');
    } catch (err) {
      const m = err instanceof Error ? err.message : String(err);
      setWritePinError(m);
    }
  }, [
    writePinGate,
    writePinValue,
    t,
    savePeakAutoPref,
    saveLowDamChargePref,
    saveSelfConsumptionPref,
    saveNightChargePref,
    applyNightChargeToolbarSnap,
    selInverterEvportBound,
  ]);

  const closeDeyeCommandModal = useCallback(() => {
    setDeyeCommandModal(null);
  }, []);

  useEffect(() => {
    if (!dischargeConfirmOpen) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') cancelDischargeConfirm();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dischargeConfirmOpen, cancelDischargeConfirm]);

  useEffect(() => {
    if (!chargeConfirmOpen) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') cancelChargeConfirm();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [chargeConfirmOpen, cancelChargeConfirm]);

  useEffect(() => {
    if (!writePinGate) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') cancelWritePinGate();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [writePinGate, cancelWritePinGate]);

  useEffect(() => {
    if (!remoteWriteNeedsPinOpen) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') closeRemoteWriteNeedsPinModal();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [remoteWriteNeedsPinOpen, closeRemoteWriteNeedsPinModal]);

  useEffect(() => {
    if (!deyeCommandModal || deyeCommandModal.phase === 'loading') return undefined;
    const onKey = e => {
      if (e.key === 'Escape') setDeyeCommandModal(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [deyeCommandModal]);

  useEffect(() => {
    const id = setInterval(() => setSimTick(n => n + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const syncFromHash = () => {
      if (window.location.hash === '#addInverterToOpenEms') {
        setDeyeMessengerOpen(true);
        requestAnimationFrame(() => {
          document.getElementById('addInverterToOpenEms')?.scrollIntoView({
            behavior: 'smooth',
            block: 'nearest',
          });
        });
      } else {
        setDeyeMessengerOpen(false);
      }
    };
    syncFromHash();
    window.addEventListener('hashchange', syncFromHash);
    return () => window.removeEventListener('hashchange', syncFromHash);
  }, []);

  const deyeListReady = inverterRows.configured && !inverterRows.loading && !inverterRows.error;
  const huaweiListReady = huaweiRows.configured && !huaweiRows.loading && !huaweiRows.error && !huaweiRows.authFailed;
  const inverterListReady = deyeListReady || huaweiListReady;

  useEffect(() => {
    setLandingTotals(null);
  }, [selInverterSn, selHuaweiStationCode, selEvPortsAcdc]);

  useEffect(() => {
    if (!inverterListReady) {
      setLandingTotalsLoading(false);
      return undefined;
    }
    let cancelled = false;
    const landingTotalsUrl = () => {
      if (selEvPortsAcdc) {
        const q = new URLSearchParams({ evPortsAcdc: selEvPortsAcdc });
        return apiUrl(`/api/power-flow/landing-totals?${q}`);
      }
      const hw = selHuaweiStationCode.trim();
      if (hw) {
        const q = new URLSearchParams({ huaweiStationCode: hw });
        return apiUrl(`/api/power-flow/landing-totals?${q}`);
      }
      const sn = selInverterSn.trim();
      const q = sn ? `?deviceSn=${encodeURIComponent(sn)}` : '';
      return apiUrl(`/api/power-flow/landing-totals${q}`);
    };
    const load = async () => {
      setLandingTotalsLoading(true);
      try {
        const r = await fetch(landingTotalsUrl());
        const data = await r.json();
        if (!cancelled && data.ok) setLandingTotals(data);
        else if (!cancelled) setLandingTotals(null);
      } catch {
        if (!cancelled) setLandingTotals(null);
      } finally {
        if (!cancelled) setLandingTotalsLoading(false);
      }
    };
    const poll = async () => {
      if (cancelled) return;
      try {
        const r = await fetch(landingTotalsUrl());
        const data = await r.json();
        if (!cancelled && data.ok) setLandingTotals(data);
        else if (!cancelled) setLandingTotals(null);
      } catch {
        if (!cancelled) setLandingTotals(null);
      }
    };
    void load();
    const id = setInterval(() => void poll(), 300_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selInverterSn, selHuaweiStationCode, selEvPortsAcdc, inverterListReady]);

  const showPowerFlowSections =
    (!inverterRows.error && (inverterRows.loading || inverterRows.configured)) ||
    (!huaweiRows.error && (huaweiRows.loading || huaweiRows.configured));
  const dischargeFeedbackText = discharge2Feedback;
  /** One full-page (main column) blur until initial REST payloads needed for Power Flow are ready — no per-section blur. */
  const pageRestHydrationPending =
    inverterRows.loading ||
    huaweiRows.loading ||
    chargingPorts.loading ||
    (realtimePower === null &&
      loadError === '' &&
      !(
        !essAnySelected &&
        ((inverterRows.configured && !inverterRows.error && fleetDeyeAggregate.okResponses > 0) ||
          (huaweiRows.configured &&
            !huaweiRows.error &&
            !huaweiRows.authFailed &&
            fleetHuaweiAggregate.okResponses > 0))
      )) ||
    (inverterListReady && landingTotalsLoading) ||
    (Boolean(selInverterSn) &&
      deyeListReady &&
      !inverterRows.error &&
      (deyeHydratedSn !== selInverterSn || toolbarPrefsLoading || solarForecast.loading)) ||
    (Boolean(selHuaweiStationCode) &&
      huaweiListReady &&
      !huaweiRows.error &&
      (huaweiHydratedCode !== selHuaweiStationCode || huaweiLiveLoading));

  const noEssListYet = (inverterRows.loading || huaweiRows.loading) && !deyeListReady && !huaweiListReady;

  return (
    <KwhCalibrationProvider inverterSn={selInverterSn} t={t}>
      <div className={`pf-body${kioskMode ? ' pf-body--kiosk' : ''}`}>
        {kioskMode ? (
          <button type="button" className="open-ems-kiosk-close" onClick={exitKiosk}>
            ← {t('openEmsKioskClose')}
          </button>
        ) : null}
        <div className={`pf-root${kioskMode ? ' pf-root--kiosk' : ''}`}>
          <div className="pf-top-bar">
            <header className="pf-header">
              <div className="pf-header-primary">
                <div className="pf-station-field pf-inverter-field">
                  <select
                    id="pf-inverter"
                    className="pf-inverter-select pf-header-select--inverter"
                    aria-label={t('inverterSelectLabel')}
                    value={noEssListYet ? '' : inverterValue}
                    onChange={onInverterChange}
                  >
                    {noEssListYet ? (
                      <option value="" disabled>
                        …
                      </option>
                    ) : inverterRows.error && huaweiRows.error && !inverterRows.configured && !huaweiRows.configured ? (
                      <option value="" disabled>
                        {t('inverterLoadError')}
                      </option>
                    ) : (
                      <>
                        <option value="">{t('inverterSelectLabel')}</option>
                        {deyeListReady && deyeCombinedItems.length > 0 ? (
                          <optgroup label={t('essDeyeCloud')}>
                            {deyeCombinedItems.map(row => {
                              const p = firstFiniteSocForDeyeRow(row, socBySn);
                              const socSuffix =
                                p != null && Number.isFinite(p) ? ` · ${inverterSocFmt.format(p)}%` : '';
                              const c = row.capexUsd;
                              const capexSuffix =
                                c != null && Number.isFinite(Number(c))
                                  ? ` · ${formatInverterCapexUsd(Number(c))}`
                                  : '';
                              return (
                                <option
                                  key={`deye-${row.representativeSn}`}
                                  value={`${ESS_PREFIX_DEYE}${row.representativeSn}`}
                                >
                                  {row.shortLabel + socSuffix + capexSuffix}
                                </option>
                              );
                            })}
                          </optgroup>
                        ) : null}
                        <optgroup label={t('essEvPorts')}>
                          <option value={`${ESS_PREFIX_DC_EV}all`}>{t('essEvPortsDc')}</option>
                          <option value={`${ESS_PREFIX_AC_EV}all`}>{t('essEvPortsAc')}</option>
                        </optgroup>
                        {huaweiRows.configured && !huaweiRows.loading && !huaweiRows.error && huaweiRows.authFailed ? (
                          <optgroup label={t('essHuaweiFusionSolar')}>
                            <option value="" disabled>
                              {t('huaweiAuthFailedHint')}
                            </option>
                          </optgroup>
                        ) : huaweiListReady && huaweiRows.northboundRateLimited && huaweiRows.items.length === 0 ? (
                          <optgroup label={t('essHuaweiFusionSolar')}>
                            <option value="" disabled>
                              {t('huaweiNorthboundRateLimited')}
                            </option>
                          </optgroup>
                        ) : huaweiListReady && huaweiRows.items.length > 0 ? (
                          <optgroup label={t('essHuaweiFusionSolar')}>
                            {huaweiRows.items.map(row => {
                              const shortLabel = inverterSelectShortLabel(row.stationName, row.stationCode);
                              return (
                                <option
                                  key={`huawei-${row.stationCode}`}
                                  value={`${ESS_PREFIX_HUAWEI}${row.stationCode}`}
                                >
                                  {shortLabel}
                                </option>
                              );
                            })}
                          </optgroup>
                        ) : null}
                      </>
                    )}
                  </select>
                  <button
                    type="button"
                    id="addInverterToOpenEms"
                    className="pf-add-deye-btn"
                    aria-label={t('addDeyeInverterAria')}
                    title={t('addDeyeInverterAria')}
                    onClick={() => setDeyeMessengerOpen(true)}
                  >
                    {t('addDeyeInverterButton')}
                  </button>
                </div>
              </div>
            </header>
          </div>

          <div className="pf-page-main" aria-busy={pageRestHydrationPending ? 'true' : undefined}>
            {showPowerFlowSections
              ? (() => {
                  const ltd = inverterListReady ? formatLandingTotalsDisplay(landingTotals, bcp47, t) : null;
                  const landingTotalsScopeFleet = landingTotals?.exportScope === 'fleet';
                  const listPending = !inverterListReady;
                  const landingHuaweiEss = Boolean(selHuaweiStationCode);
                  const landingEvPortsEss = Boolean(selEvPortsAcdc);
                  const landingExportMetricUi = (() => {
                    const m = landingExportMetric;
                    const offers = landingExportMetricOffers;
                    if (
                      (landingHuaweiEss || landingEvPortsEss) &&
                      (m === LANDING_EXPORT_METRIC.PEAK ||
                        m === LANDING_EXPORT_METRIC.MANUAL ||
                        m === LANDING_EXPORT_METRIC.ARBITRAGE ||
                        m === LANDING_EXPORT_METRIC.LOST_SOLAR_7D)
                    ) {
                      return preferredLandingExportMetric(offers);
                    }
                    if (landingEvPortsEss && m === LANDING_EXPORT_METRIC.GRID_BALANCING) {
                      return LANDING_EXPORT_METRIC.MONTHLY_RATES;
                    }
                    if (landingTotals?.ok && m === LANDING_EXPORT_METRIC.GRID_BALANCING && !offers.gridBalancing) {
                      return LANDING_EXPORT_METRIC.MONTHLY_RATES;
                    }
                    if (m === LANDING_EXPORT_METRIC.PEAK && !offers.peak) {
                      return preferredLandingExportMetric(offers);
                    }
                    if (m === LANDING_EXPORT_METRIC.MANUAL && !offers.manual) {
                      return preferredLandingExportMetric(offers);
                    }
                    if (m === LANDING_EXPORT_METRIC.TOTAL && !offers.total) {
                      return preferredLandingExportMetric(offers);
                    }
                    if (m === LANDING_EXPORT_METRIC.ARBITRAGE && !offers.arbitrage) {
                      return preferredLandingExportMetric(offers);
                    }
                    if (m === LANDING_EXPORT_METRIC.LOST_SOLAR_7D && !offers.lostSolar) {
                      return preferredLandingExportMetric(offers);
                    }
                    return m;
                  })();

                  const showGridBalancingChart = landingExportMetricUi === LANDING_EXPORT_METRIC.GRID_BALANCING;
                  const showMonthlyRatesChart = landingExportMetricUi === LANDING_EXPORT_METRIC.MONTHLY_RATES;
                  const showExportHourlyChart =
                    !showGridBalancingChart &&
                    !showMonthlyRatesChart &&
                    !landingHuaweiEss &&
                    (landingExportMetricUi === LANDING_EXPORT_METRIC.PEAK ||
                      landingExportMetricUi === LANDING_EXPORT_METRIC.MANUAL ||
                      landingExportMetricUi === LANDING_EXPORT_METRIC.TOTAL ||
                      landingExportMetricUi === LANDING_EXPORT_METRIC.ARBITRAGE ||
                      landingExportMetricUi === LANDING_EXPORT_METRIC.LOST_SOLAR_7D);

                  const sourceSelected = Boolean(selInverterSn || selHuaweiStationCode || selEvPortsAcdc);
                  const showMonthlyRatesInverterSupplements =
                    sourceSelected &&
                    inverterListReady &&
                    landingExportMetricUi === LANDING_EXPORT_METRIC.MONTHLY_RATES;
                  const showGridBalancingSupplement =
                    sourceSelected &&
                    !landingEvPortsEss &&
                    inverterListReady &&
                    (showMonthlyRatesInverterSupplements ||
                      landingExportMetricUi !== LANDING_EXPORT_METRIC.GRID_BALANCING);
                  const gridBalancingSupplement = showGridBalancingSupplement
                    ? landingGridBalancingSupplement(landingTotals, bcp47)
                    : null;
                  const monthlyRatesTariffVsUkraineSupplement = showMonthlyRatesInverterSupplements
                    ? landingMonthlyRatesTariffVsUkraineSupplement(landingTotals, bcp47)
                    : null;
                  const inverterMetricDisplay =
                    landingExportMetricUi === LANDING_EXPORT_METRIC.GRID_BALANCING
                      ? formatLandingGridBalancingMetric(landingTotals, bcp47, t)
                      : landingExportMetricUi === LANDING_EXPORT_METRIC.MONTHLY_RATES
                        ? formatLandingMonthlyRatesMetric(landingTotals, bcp47, t)
                        : ltd
                          ? (() => {
                              if (landingExportMetricUi === LANDING_EXPORT_METRIC.TOTAL) {
                                return {
                                  text: formatLandingTotalExportSamplesKwh(landingTotals.totalExportKwh, bcp47),
                                  title: landingTotalsScopeFleet
                                    ? t('powerFlowLandingExportTotalHintFleet')
                                    : t('powerFlowLandingExportTotalHint'),
                                  wrapClass: 'pf-landing-totals__counter-wrap',
                                  counterClass: 'pf-landing-totals__counter',
                                  valueIsCurrency: false,
                                };
                              }
                              if (landingExportMetricUi === LANDING_EXPORT_METRIC.PEAK) {
                                const p = ltd.peakDam;
                                return {
                                  text: p ? p.exportText : '—',
                                  title: landingTotalsScopeFleet
                                    ? t('powerFlowLandingPeakDamSessionHintFleet')
                                    : t('powerFlowLandingPeakDamSessionHint'),
                                  wrapClass: `pf-landing-totals__counter-wrap${p ? ' pf-landing-totals__counter-wrap--peak-dam' : ''}`,
                                  counterClass: `pf-landing-totals__counter${p ? ' pf-landing-totals__counter--peak-dam' : ''}`,
                                  valueIsCurrency: false,
                                };
                              }
                              if (landingExportMetricUi === LANDING_EXPORT_METRIC.MANUAL) {
                                const m = ltd.manualDischarge;
                                return {
                                  text: m ? m.exportText : '—',
                                  title: landingTotalsScopeFleet
                                    ? t('powerFlowLandingManualDischargeHintFleet')
                                    : t('powerFlowLandingManualDischargeHint'),
                                  wrapClass: `pf-landing-totals__counter-wrap${m ? ' pf-landing-totals__counter-wrap--manual-discharge' : ''}`,
                                  counterClass: `pf-landing-totals__counter${m ? ' pf-landing-totals__counter--manual-discharge' : ''}`,
                                  valueIsCurrency: false,
                                };
                              }
                              if (landingExportMetricUi === LANDING_EXPORT_METRIC.ARBITRAGE) {
                                const a = ltd.arbitrage;
                                return {
                                  text: a ? a.revenueText : '—',
                                  title: landingTotalsScopeFleet
                                    ? t('powerFlowLandingArbitrageHintFleet')
                                    : t('powerFlowLandingArbitrageHint'),
                                  wrapClass: `pf-landing-totals__counter-wrap${a ? ' pf-landing-totals__counter-wrap--arbitrage' : ''}`,
                                  counterClass: `pf-landing-totals__counter${a ? ' pf-landing-totals__counter--arbitrage' : ''}`,
                                  valueIsCurrency: true,
                                  arbitrageMom: a?.mom ?? null,
                                };
                              }
                              if (landingExportMetricUi === LANDING_EXPORT_METRIC.LOST_SOLAR_7D) {
                                const ls = landingTotals?.lostSolarKwhTotal;
                                const lsNum = ls != null ? Number(ls) : null;
                                const fmtLs = new Intl.NumberFormat(bcp47, {
                                  maximumFractionDigits: 1,
                                  minimumFractionDigits: 0,
                                });
                                return {
                                  text:
                                    lsNum != null && Number.isFinite(lsNum) && lsNum > 0 ? fmtLs.format(lsNum) : '—',
                                  title: landingTotalsScopeFleet
                                    ? t('powerFlowLandingExportMetricLostSolar7dHintFleet')
                                    : t('powerFlowLandingExportMetricLostSolar7dHint'),
                                  wrapClass:
                                    'pf-landing-totals__counter-wrap pf-landing-totals__counter-wrap--lost-solar',
                                  counterClass: 'pf-landing-totals__counter pf-landing-totals__counter--lost-solar',
                                  valueIsCurrency: false,
                                };
                              }
                              return {
                                text: formatLandingTotalExportSamplesKwh(landingTotals.totalExportKwh, bcp47),
                                title: landingTotalsScopeFleet
                                  ? t('powerFlowLandingExportTotalHintFleet')
                                  : t('powerFlowLandingExportTotalHint'),
                                wrapClass: 'pf-landing-totals__counter-wrap',
                                counterClass: 'pf-landing-totals__counter',
                                valueIsCurrency: false,
                              };
                            })()
                          : null;

                  if (listPending) {
                    return (
                      <div className="pf-landing-totals-slot">
                        <div
                          className="pf-landing-totals pf-landing-totals--skeleton"
                          aria-busy="true"
                          aria-label={t('powerFlowLandingTotalsAria')}
                        >
                          <div className="pf-landing-totals__export">
                            <div className="pf-landing-totals__metric-row">
                              <div className="pf-skeleton-line pf-skeleton-line--metric-select" />
                              <div className="pf-landing-totals__counter-wrap pf-landing-totals__counter-wrap--skeleton">
                                <span className="pf-skeleton-line pf-skeleton-line--counter" />
                              </div>
                            </div>
                          </div>
                          <div className="pf-skeleton-line pf-skeleton-line--center pf-skeleton-line--tariff" />
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div className="pf-landing-totals-slot">
                      <div className="pf-landing-totals" aria-label={t('powerFlowLandingTotalsAria')}>
                        <div className="pf-landing-totals__export pf-landing-totals__export--inverter-metric">
                          <div
                            className="pf-landing-totals__metric-row"
                            title={inverterMetricDisplay?.title ?? undefined}
                          >
                            <select
                              id="pf-landing-export-metric"
                              className="pf-lang-select pf-landing-totals__metric-select"
                              aria-label={t('powerFlowLandingExportMetricAria')}
                              value={landingExportMetricUi}
                              onChange={e => {
                                const v = e.target.value;
                                setLandingExportMetric(v);
                                writeStoredLandingExportMetric(selInverterSn, selHuaweiStationCode, v);
                              }}
                            >
                              {landingExportMetricOffers.gridBalancing ? (
                                <option value={LANDING_EXPORT_METRIC.GRID_BALANCING}>
                                  {t('powerFlowLandingExportMetricGridBalancing')}
                                </option>
                              ) : null}
                              <option value={LANDING_EXPORT_METRIC.MONTHLY_RATES}>
                                {t('powerFlowLandingExportMetricMonthlyRates')}
                              </option>
                              {landingHuaweiEss || landingEvPortsEss || !landingExportMetricOffers.peak ? null : (
                                <option value={LANDING_EXPORT_METRIC.PEAK}>
                                  {t('powerFlowLandingExportMetricPeak')}
                                </option>
                              )}
                              {landingHuaweiEss || landingEvPortsEss || !landingExportMetricOffers.manual ? null : (
                                <option value={LANDING_EXPORT_METRIC.MANUAL}>
                                  {t('powerFlowLandingExportMetricManual')}
                                </option>
                              )}
                              {landingExportMetricOffers.total ? (
                                <option value={LANDING_EXPORT_METRIC.TOTAL}>
                                  {t('powerFlowLandingExportMetricTotal')}
                                </option>
                              ) : null}
                              {landingHuaweiEss || landingEvPortsEss || !landingExportMetricOffers.lostSolar ? null : (
                                <option value={LANDING_EXPORT_METRIC.LOST_SOLAR_7D}>
                                  {t('powerFlowLandingExportMetricLostSolar7d')}
                                </option>
                              )}
                              {landingHuaweiEss || landingEvPortsEss || !landingExportMetricOffers.arbitrage ? null : (
                                <option value={LANDING_EXPORT_METRIC.ARBITRAGE}>
                                  {t('powerFlowLandingExportMetricArbitrage')}
                                </option>
                              )}
                            </select>
                            {inverterMetricDisplay ? (
                              <div
                                className={
                                  inverterMetricDisplay.monthlyRatesLayout
                                    ? inverterMetricDisplay.monthlyRatesMom
                                      ? 'pf-landing-totals__export-value pf-landing-totals__export-value--monthly-rates pf-landing-totals__export-value--with-monthly-rates-mom'
                                      : 'pf-landing-totals__export-value pf-landing-totals__export-value--monthly-rates'
                                    : inverterMetricDisplay.arbitrageMom
                                      ? 'pf-landing-totals__export-value pf-landing-totals__export-value--with-arbitrage-mom'
                                      : 'pf-landing-totals__export-value'
                                }
                              >
                                {landingExportMetricUi === LANDING_EXPORT_METRIC.GRID_BALANCING ? (
                                  <LandingGridBalancingDisplay
                                    display={inverterMetricDisplay}
                                    t={t}
                                    asButton={
                                      !(landingHuaweiEss || landingEvPortsEss) ||
                                      showGridBalancingChart ||
                                      showExportHourlyChart
                                    }
                                    chartAria={t('powerFlowGridBalancingChartOpenAria')}
                                    onChartOpen={() => setGridBalancingChartOpen(true)}
                                  />
                                ) : inverterMetricDisplay.monthlyRatesLayout ? (
                                  <LandingMonthlyRatesDisplay
                                    display={inverterMetricDisplay}
                                    t={t}
                                    asButton={
                                      !(landingHuaweiEss || landingEvPortsEss) ||
                                      showMonthlyRatesChart ||
                                      showExportHourlyChart
                                    }
                                    chartAria={t('powerFlowMonthlyRatesChartOpenAria')}
                                    onChartOpen={() => setMonthlyRatesChartOpen(true)}
                                  />
                                ) : (
                                  <LandingExportMetricCounter
                                    display={inverterMetricDisplay}
                                    t={t}
                                    landingHuaweiEss={landingHuaweiEss}
                                    showMonthlyRatesChart={showMonthlyRatesChart}
                                    showExportHourlyChart={showExportHourlyChart}
                                    landingExportMetric={landingExportMetric}
                                    onOpenMonthlyRates={() => setMonthlyRatesChartOpen(true)}
                                    onOpenExportChart={() => setExportHourlyChartOpen(true)}
                                  />
                                )}
                                {inverterMetricDisplay.arbitrageMom ? (
                                  <span
                                    className={
                                      inverterMetricDisplay.arbitrageMom.deltaPct > 0
                                        ? 'pf-landing-totals__arbitrage-mom-out pf-landing-totals__arbitrage-mom-out--up'
                                        : inverterMetricDisplay.arbitrageMom.deltaPct < 0
                                          ? 'pf-landing-totals__arbitrage-mom-out pf-landing-totals__arbitrage-mom-out--down'
                                          : 'pf-landing-totals__arbitrage-mom-out pf-landing-totals__arbitrage-mom-out--flat'
                                    }
                                  >
                                    {t('powerFlowLandingArbitrageMomDelta', {
                                      delta: inverterMetricDisplay.arbitrageMom.deltaStr,
                                      month: inverterMetricDisplay.arbitrageMom.monthLabel,
                                    })}
                                  </span>
                                ) : null}
                              </div>
                            ) : (
                              <div className="pf-landing-totals__counter-wrap pf-landing-totals__counter-wrap--loading">
                                <span className="pf-landing-totals__counter">…</span>
                              </div>
                            )}
                          </div>
                        </div>
                        {sourceSelected ? (
                          <>
                            {landingExportMetricUi === LANDING_EXPORT_METRIC.GRID_BALANCING ? (
                              <p className="pf-landing-totals__tariff pf-landing-totals__tariff--monthly-rates-hint">
                                {t('powerFlowLandingGridBalancingClickHint')}
                              </p>
                            ) : null}
                            {gridBalancingSupplement ? (
                              <p className="pf-landing-totals__tariff pf-landing-totals__tariff--grid-balancing-supplement">
                                {t('powerFlowLandingGridBalancingSupplementBefore')}
                                <span
                                  className={
                                    gridBalancingSupplement.tier
                                      ? `pf-landing-totals__grid-balancing-supplement-pct pf-landing-totals__grid-balancing-supplement-pct--${gridBalancingSupplement.tier}`
                                      : 'pf-landing-totals__grid-balancing-supplement-pct'
                                  }
                                >
                                  {gridBalancingSupplement.pctStr}
                                </span>
                              </p>
                            ) : null}
                            {monthlyRatesTariffVsUkraineSupplement ? (
                              <p className="pf-landing-totals__tariff pf-landing-totals__tariff--monthly-rates-vs-ukraine">
                                {monthlyRatesTariffVsUkraineSupplement.kind === 'equal' ? (
                                  t('powerFlowLandingTariffVsUkraineEqual')
                                ) : monthlyRatesTariffVsUkraineSupplement.kind === 'more' ? (
                                  <>
                                    {t('powerFlowLandingTariffVsUkraineMoreBefore')}
                                    <span className="pf-landing-totals__monthly-rates-vs-ukraine-pct pf-landing-totals__monthly-rates-vs-ukraine-pct--up">
                                      {monthlyRatesTariffVsUkraineSupplement.deltaStr}%
                                    </span>
                                    {t('powerFlowLandingTariffVsUkraineMoreAfter')}
                                  </>
                                ) : (
                                  <>
                                    {t('powerFlowLandingTariffVsUkraineLessBefore')}
                                    <span className="pf-landing-totals__monthly-rates-vs-ukraine-pct pf-landing-totals__monthly-rates-vs-ukraine-pct--down">
                                      {monthlyRatesTariffVsUkraineSupplement.deltaStr}%
                                    </span>
                                    {t('powerFlowLandingTariffVsUkraineLessAfter')}
                                  </>
                                )}
                              </p>
                            ) : null}
                          </>
                        ) : landingExportMetricUi === LANDING_EXPORT_METRIC.GRID_BALANCING ? (
                          <p className="pf-landing-totals__tariff pf-landing-totals__tariff--monthly-rates-hint">
                            {t('powerFlowLandingGridBalancingClickHint')}
                          </p>
                        ) : landingExportMetricUi === LANDING_EXPORT_METRIC.MONTHLY_RATES ? null : (
                          <>
                            <p className="pf-landing-totals__tariff">
                              {ltd?.tariffCompare ? (
                                <>
                                  {ltd.tariffCompare.lead}
                                  <span
                                    className={
                                      ltd.tariffCompare.deltaPct > 0
                                        ? 'pf-landing-totals__delta pf-landing-totals__delta--up'
                                        : ltd.tariffCompare.deltaPct < 0
                                          ? 'pf-landing-totals__delta pf-landing-totals__delta--down'
                                          : 'pf-landing-totals__delta pf-landing-totals__delta--flat'
                                    }
                                  >
                                    {ltd.tariffCompare.deltaStr}
                                  </span>
                                  {ltd.tariffCompare.tail}
                                </>
                              ) : ltd?.tariffLine != null ? (
                                ltd.tariffLine
                              ) : (
                                t('powerFlowLandingTariffLoading')
                              )}
                            </p>
                            {ltd?.damTariffLine ? (
                              <p className="pf-landing-totals__tariff pf-landing-totals__tariff--dam">
                                {ltd.damTariffLine}
                              </p>
                            ) : null}
                          </>
                        )}
                      </div>
                    </div>
                  );
                })()
              : null}

            {isWideViewport && !kioskMode ? (
              <div className="pf-kiosk-wide-actions">
                <button type="button" className="pf-kiosk-expand-btn" onClick={openKiosk}>
                  {t('openEmsKioskOpen')}
                </button>
              </div>
            ) : null}

            <div className={kioskMode ? 'pf-kiosk-layout' : 'pf-kiosk-layout-passthrough'}>
              <div className={kioskMode ? 'pf-kiosk-layout__graph' : 'pf-kiosk-layout-passthrough'}>
            <div className={`pf-graph-wrap${kioskMode ? ' pf-graph-wrap--kiosk' : ''}`}>
              <div
                id="pf-graph"
                ref={graphRef}
                className={`pf-graph${kioskMode ? ' pf-graph--kiosk' : ''}`}
                style={{ '--pf-graph-anchor-pct': `${graphAnchorPct}%` }}
                aria-label={t('graphAriaLabel')}
              >
                <div className="pf-graph-sizer" aria-hidden="true" />
                <svg id="pf-svg" className="pf-flow-svg" viewBox="0 0 400 400" preserveAspectRatio="xMidYMid meet">
                  <defs>
                    <radialGradient id="pf-flow-dot-grad" cx="40%" cy="40%" r="65%" gradientUnits="objectBoundingBox">
                      <stop offset="0%" stopColor="#fdf4ff" />
                      <stop offset="60%" stopColor="#e879f9" />
                      <stop offset="100%" stopColor="#a855f7" />
                    </radialGradient>
                  </defs>
                  <g id="pf-lines">
                    <line
                      id="pf-line-solar"
                      className="pf-line"
                      data-active={solarFlowActive ? 'true' : 'false'}
                      x1={geom.solarLine.start.x}
                      y1={geom.solarLine.start.y}
                      x2={geom.solarLine.end.x}
                      y2={geom.solarLine.end.y}
                    />
                    <line
                      id="pf-line-grid"
                      className="pf-line"
                      data-active={gridLineCoords.active ? 'true' : 'false'}
                      x1={gridLineCoords.start.x}
                      y1={gridLineCoords.start.y}
                      x2={gridLineCoords.end.x}
                      y2={gridLineCoords.end.y}
                    />
                    <line
                      id="pf-line-load"
                      className="pf-line"
                      data-active={loadFlowActive ? 'true' : 'false'}
                      x1={geom.loadLine.start.x}
                      y1={geom.loadLine.start.y}
                      x2={geom.loadLine.end.x}
                      y2={geom.loadLine.end.y}
                    />
                    <line
                      id="pf-line-ess"
                      className="pf-line"
                      data-active={essActive ? 'true' : 'false'}
                      x1={essCoords.start.x}
                      y1={essCoords.start.y}
                      x2={essCoords.end.x}
                      y2={essCoords.end.y}
                    />
                    <line
                      id="pf-line-miner"
                      className="pf-line"
                      data-active={hasFlow && graphMinerFlowW > 0 ? 'true' : 'false'}
                      x1={geom.minerLine.start.x}
                      y1={geom.minerLine.start.y}
                      x2={geom.minerLine.end.x}
                      y2={geom.minerLine.end.y}
                    />
                    <line
                      id="pf-line-cons"
                      className="pf-line"
                      data-active={evFlowActive ? 'true' : 'false'}
                      x1={geom.consumptionLine.start.x}
                      y1={geom.consumptionLine.start.y}
                      x2={geom.consumptionLine.end.x}
                      y2={geom.consumptionLine.end.y}
                    />
                  </g>
                  <g id="pf-dots">
                    <g id="pf-dot-solar" style={{ display: solarFlowActive ? undefined : 'none' }}>
                      <MotionDot
                        pathD={flowMotionPath(
                          geom.solarLine.start.x,
                          geom.solarLine.start.y,
                          geom.solarLine.end.x,
                          geom.solarLine.end.y
                        )}
                      />
                    </g>
                    <g id="pf-dot-grid" style={{ display: gridLineCoords.active ? undefined : 'none' }}>
                      <MotionDot pathD={gridDotPath} />
                    </g>
                    <g id="pf-dot-load" style={{ display: loadFlowActive ? undefined : 'none' }}>
                      <MotionDot
                        pathD={flowMotionPath(
                          geom.loadLine.start.x,
                          geom.loadLine.start.y,
                          geom.loadLine.end.x,
                          geom.loadLine.end.y
                        )}
                      />
                    </g>
                    <g id="pf-dot-ess" style={{ display: essActive ? undefined : 'none' }}>
                      <MotionDot pathD={essPath} />
                    </g>
                    <g id="pf-dot-miner" style={{ display: hasFlow && graphMinerFlowW > 0 ? undefined : 'none' }}>
                      <MotionDot
                        pathD={flowMotionPath(
                          geom.minerLine.start.x,
                          geom.minerLine.start.y,
                          geom.minerLine.end.x,
                          geom.minerLine.end.y
                        )}
                      />
                    </g>
                    <g id="pf-dot-cons" style={{ display: evFlowActive ? undefined : 'none' }}>
                      <MotionDot
                        pathD={flowMotionPath(
                          geom.consumptionLine.start.x,
                          geom.consumptionLine.start.y,
                          geom.consumptionLine.end.x,
                          geom.consumptionLine.end.y
                        )}
                      />
                    </g>
                  </g>
                </svg>

                <div id="pf-nodes">
                  <div
                    className="pf-node"
                    data-pos="left-top"
                    id="pf-node-solar"
                    data-active={solarFlowActive ? 'true' : 'false'}
                    role="button"
                    tabIndex={0}
                    onClick={e => openNodePopup(e, { title: t('nodeSolar') })}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') openNodePopup(e, { title: t('nodeSolar') });
                    }}
                  >
                    <div className="pf-solar-header">
                      <span
                        className="pf-node-icon"
                        aria-hidden={!solarForecastIconAria}
                        aria-label={solarForecastIconAria}
                        title={solarForecastIconAria}
                      >
                        {solarForecastIconChar}
                      </span>
                      {selInverterSn && (solarForecast.loading || solarForecast.todayPct != null) ? (
                        <span className="pf-solar-today-near-icon" id="pf-solar-insolation-today">
                          {solarForecast.loading ? '…' : t('solarInsolationToday', { pct: solarForecast.todayPct })}
                        </span>
                      ) : null}
                    </div>
                    <span className="pf-node-label">{t('nodeSolar')}</span>
                    <span className="pf-node-value" id="pf-val-solar">
                      {evOnlyGraphLoading ? '…' : formatPower(graphDisplaySolarW, t, bcp47)}
                    </span>
                    {selInverterSn ? (
                      <span className="pf-node-sub pf-node-solar-forecast" id="pf-solar-insolation-forecast">
                        {solarForecast.loading ? (
                          ''
                        ) : solarForecast.tomorrowPct != null ? (
                          <span className="pf-solar-insolation-line">
                            {t('solarInsolationTomorrow', { pct: solarForecast.tomorrowPct })}
                          </span>
                        ) : solarForecast.hintKey ? (
                          t(solarForecast.hintKey)
                        ) : (
                          ''
                        )}
                      </span>
                    ) : null}
                    <div className="pf-node-meta" id="pf-solar-lcoe" title={t('lcoeSolarMetaTitle')}>
                      {!referenceLcoe.loading && referenceLcoe.ok
                        ? formatUahPerKwhTariffLine(referenceLcoe.solarUahPerKwh)
                        : ''}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="pf-graph-refresh"
                    data-pos="top-center"
                    onClick={() => window.location.reload()}
                    aria-label={t('hubRefreshAria')}
                    title={t('hubRefreshAria')}
                  >
                    <span className="pf-graph-refresh-icon" aria-hidden>
                      ↻
                    </span>
                  </button>
                  <div className="pf-node-stack" data-pos="left-center">
                    <button
                      type="button"
                      className="pf-node"
                      id="pf-node-grid"
                      data-active={hasFlow && gridFlowActive ? 'true' : 'false'}
                      onClick={e => openNodePopup(e, { title: t('nodeGrid') })}
                    >
                      <span className="pf-node-icon" aria-hidden>
                        ⚡
                      </span>
                      <span className="pf-node-label">{t('nodeGrid')}</span>
                      <span className="pf-node-value" id="pf-val-grid">
                        {evOnlyGraphLoading
                          ? '…'
                          : gridSelling
                            ? `↓ ${formatPower(Math.abs(graphDisplayGridW), t, bcp47)}`
                            : formatPower(graphDisplayGridW, t, bcp47)}
                      </span>
                      <span className="pf-ess-status" id="pf-grid-selling" hidden={!gridSelling}>
                        {t('gridSelling')}
                      </span>
                      <div className="pf-node-meta" id="pf-grid-tariff" title={t('gridDamTariffNodeTitle')}>
                        {formatUahPerKwhTariffLine(gridDamTariffUahPerKwh)}
                      </div>
                    </button>
                  </div>
                  <div
                    className="pf-node"
                    data-pos="left-bottom"
                    id="pf-node-load"
                    data-active={loadFlowActive ? 'true' : 'false'}
                    role="button"
                    tabIndex={0}
                    onClick={e => openNodePopup(e, { title: t('nodeLoad') })}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') openNodePopup(e, { title: t('nodeLoad') });
                    }}
                  >
                    <span className="pf-node-icon" aria-hidden>
                      🏠
                    </span>
                    <span className="pf-node-label">{t('nodeLoad')}</span>
                    <span className="pf-node-value" id="pf-val-load">
                      {!essAnySelected
                        ? evOnlyFocusMode
                          ? evStationPowerLoading && evStationPowerW == null
                            ? '…'
                            : formatPower(graphDisplayLoadW, t, bcp47)
                          : fleetDeyePollBusy
                            ? '…'
                            : fleetLoadTelemetryActive
                              ? formatPower(displayLoadW, t, bcp47)
                              : formatPower(null, t, bcp47)
                        : selHuaweiStationCode
                          ? huaweiLiveLoading
                            ? '…'
                            : displayLoadW != null
                              ? formatPower(displayLoadW, t, bcp47)
                              : formatPower(null, t, bcp47)
                          : deyeLiveLoading
                            ? '…'
                            : displayLoadW != null
                              ? formatPower(displayLoadW, t, bcp47)
                              : formatPower(null, t, bcp47)}
                    </span>
                  </div>
                  <div className="pf-hub" id="pf-hub">
                    <PartnerHubLogo t={t} flowEndsHere={hubLogoInboundFlow} />
                    <a
                      className="pf-hub-opensource"
                      href={OPEN_EMS_GITHUB_URL}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={t('openSourceGithubAria')}
                    >
                      <svg
                        className="pf-hub-opensource-icon"
                        viewBox="0 0 98 96"
                        xmlns="http://www.w3.org/2000/svg"
                        aria-hidden="true"
                        focusable="false"
                      >
                        <path
                          fill="currentColor"
                          fillRule="evenodd"
                          clipRule="evenodd"
                          d="M48.854 0C21.839 0 0 22 0 49.217c0 21.756 13.993 40.172 33.405 46.69 2.427.49 3.316-1.059 3.316-2.362 0-1.141-.08-5.052-.08-9.127-13.59 2.934-16.42-5.867-16.42-5.867-2.184-5.704-5.42-7.17-5.42-7.17-4.448-3.015.324-3.015.324-3.015 4.934.326 7.523 5.052 7.523 5.052 4.367 7.496 11.404 5.378 14.235 4.074.404-3.178 1.699-5.378 3.074-6.6-10.839-1.225-22.23-5.546-22.23-24.727 0-5.378 1.94-9.778 5.014-13.2-.485-1.222-2.184-6.275.486-13.038 0 0 4.125-1.304 13.426 5.052a46.97 46.97 0 0 1 12.214-1.63c4.125 0 8.33.571 12.213 1.63 9.302-6.356 13.427-5.052 13.427-5.052 2.67 6.763.97 11.816.485 13.038 3.155 3.422 5.015 7.822 5.015 13.2 0 19.343-11.424 23.502-22.307 24.727 1.814 1.577 3.483 4.731 3.483 9.578 0 6.896-.08 12.55-.08 14.29 0 1.307.89 2.853 3.316 2.364 19.412-6.52 33.405-24.935 33.405-46.691C97.707 22 75.788 0 48.854 0z"
                        />
                      </svg>
                      <span className="pf-hub-opensource-text">{t('openSourceLabel')}</span>
                    </a>
                  </div>
                  <button
                    type="button"
                    className="pf-node"
                    data-pos="right-top"
                    id="pf-node-ess"
                    data-active={essActive ? 'true' : 'false'}
                    onClick={e => openNodePopup(e, { title: t('nodeEss') })}
                  >
                    <span className="pf-node-icon" id="pf-ess-icon" aria-hidden>
                      {graphDisplayEssCharging ? (
                        <span className="pf-ess-icon-charging">
                          <span className="pf-ess-icon-charging-bat">🔋</span>
                          <span className="pf-ess-icon-charging-bolt">⚡</span>
                        </span>
                      ) : (
                        '🔋'
                      )}
                    </span>
                    <span className="pf-node-label">{t('nodeEss')}</span>
                    <span className="pf-node-value" id="pf-val-ess">
                      {evOnlyGraphLoading ? '…' : formatPower(graphDisplayEssW != null ? Math.abs(graphDisplayEssW) : null, t, bcp47)}
                    </span>
                    {selInverterSn && essSocPercent != null && Number.isFinite(essSocPercent) ? (
                      <span
                        className={`pf-node-sub pf-ess-soc ${essSocBandClassName(essSocPercent)}`.trim()}
                        id="pf-ess-soc"
                      >
                        {t('essSoc', {
                          value: inverterSocFmt.format(essSocPercent),
                        })}
                      </span>
                    ) : null}
                    {essSocPending ? (
                      <span className="pf-node-sub pf-ess-soc pf-ess-soc-loading" id="pf-ess-soc-loading">
                        {t('essSocLoading')}
                      </span>
                    ) : null}
                    <div className="pf-node-meta" id="pf-ess-lcoe" title={t('lcoeBatteryMetaTitle')}>
                      {!referenceLcoe.loading && referenceLcoe.ok
                        ? formatUahPerKwhTariffLine(referenceLcoe.batteryUahPerKwh)
                        : ''}
                    </div>
                  </button>
                  <a
                    className="pf-node"
                    data-pos="right-center"
                    id="pf-node-miner"
                    href={BINANCE_MINER_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-active={hasFlow && graphMinerFlowW > 0 ? 'true' : 'false'}
                    onClick={e =>
                      openNodePopup(e, {
                        title: t('nodeMiner'),
                        actionHref: BINANCE_MINER_URL,
                        actionLabel: 'Open Binance',
                      })
                    }
                  >
                    <span className="pf-node-icon" aria-hidden>
                      💠
                    </span>
                    <span className="pf-node-label" id="pf-miner-label">
                      {minerLabel}
                    </span>
                    <span className="pf-node-value" id="pf-val-miner">
                      {evOnlyGraphLoading ? '…' : formatPower(graphDisplayMinerW, t, bcp47)}
                    </span>
                    <div className="pf-node-meta" id="pf-miner-tariff">
                      {formatUahPerKwhTariffLine(tf)}
                    </div>
                  </a>
                  {stationFilter.trim() ? (
                    <a
                      className="pf-node"
                      data-pos="right-bottom"
                      id="pf-node-ev"
                      href={`${EV_START_URL}?station=${encodeURIComponent(stationFilter.trim())}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-active={evFlowActive ? 'true' : 'false'}
                      title={t('stationLabel')}
                      onClick={e =>
                        openNodePopup(e, {
                          title: t('nodeEv'),
                          actionHref: `${EV_START_URL}?station=${encodeURIComponent(stationFilter.trim())}`,
                          actionLabel: 'Open EV station',
                        })
                      }
                    >
                      <span className="pf-node-icon pf-node-icon--inline-count" aria-hidden>
                        <EvCarMark className="pf-node-icon__tesla" />
                      </span>
                      <span className="pf-node-label">{t('nodeEv')}</span>
                      <span className="pf-node-value" id="pf-val-ev">
                        {evStationPowerLoading && evStationPowerW == null
                          ? '…'
                          : formatPower(evStationPowerW, t, bcp47)}
                      </span>
                      <div className="pf-node-meta" id="pf-ev-tariff">
                        {evDisplayTariffUahPerKwh != null ? formatUahPerKwhTariffLine(evDisplayTariffUahPerKwh) : ''}
                      </div>
                    </a>
                  ) : selEvPortsAggregate ? (
                    <a
                      className="pf-node"
                      data-pos="right-bottom"
                      id="pf-node-ev"
                      href={SITE_220KM_HOME}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-active={evFlowActive ? 'true' : 'false'}
                      title={selEvPortsAcdc === 'ac' ? t('essEvPortsAc') : t('essEvPortsDc')}
                      onClick={e =>
                        openNodePopup(e, {
                          title: t('nodeEv'),
                          actionHref: SITE_220KM_HOME,
                          actionLabel: 'Open EV station',
                        })
                      }
                    >
                      <span className="pf-node-icon pf-node-icon--inline-count" aria-hidden>
                        <EvCarMark className="pf-node-icon__tesla" />
                      </span>
                      <span className="pf-node-label">{t('nodeEv')}</span>
                      <span className="pf-node-value" id="pf-val-ev">
                        {evPortsLive.loading && evPortsDisplayPowerW == null
                          ? '…'
                          : formatPower(evPortsDisplayPowerW, t, bcp47)}
                      </span>
                      <div className="pf-node-meta" id="pf-ev-tariff">
                        {evPortsLive.activeSessions > 0
                          ? t('essEvPortsActiveCount', { count: evPortsLive.activeSessions })
                          : ''}
                      </div>
                    </a>
                  ) : showEvAggregate ? (
                    <a
                      className="pf-node"
                      data-pos="right-bottom"
                      id="pf-node-ev"
                      href={SITE_220KM_HOME}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-active={evFlowActive ? 'true' : 'false'}
                      onClick={e =>
                        openNodePopup(e, {
                          title: t('nodeEv'),
                          actionHref: SITE_220KM_HOME,
                          actionLabel: 'Open EV station',
                        })
                      }
                    >
                      <span className="pf-node-icon pf-node-icon--inline-count" aria-hidden>
                        <EvCarMark className="pf-node-icon__tesla" />
                      </span>
                      <span className="pf-node-label">{t('nodeEv')}</span>
                      <span className="pf-node-value" id="pf-val-ev">
                        {evBusy ? '…' : formatPower(aggregateEvFlowW, t, bcp47)}
                      </span>
                      <div className="pf-node-meta" id="pf-ev-tariff">
                        {evDisplayTariffUahPerKwh != null ? formatUahPerKwhTariffLine(evDisplayTariffUahPerKwh) : ''}
                      </div>
                    </a>
                  ) : (
                    <div
                      className="pf-node pf-node-ev-disabled"
                      data-pos="right-bottom"
                      id="pf-node-ev"
                      data-active="false"
                      title={t('evHiddenByInverter')}
                      role="button"
                      tabIndex={0}
                      onClick={e => openNodePopup(e, { title: t('nodeEv') })}
                      onKeyDown={e => {
                        if (e.key === 'Enter' || e.key === ' ') openNodePopup(e, { title: t('nodeEv') });
                      }}
                    >
                      <span className="pf-node-icon pf-node-icon--inline-count" aria-hidden>
                        <EvCarMark className="pf-node-icon__tesla" />
                      </span>
                      <span className="pf-node-label">{t('nodeEv')}</span>
                      <span className="pf-node-value" id="pf-val-ev">
                        {formatPower(null, t, bcp47)}
                      </span>
                      <div className="pf-node-meta" id="pf-ev-tariff">
                        {evDisplayTariffUahPerKwh != null ? formatUahPerKwhTariffLine(evDisplayTariffUahPerKwh) : ''}
                      </div>
                    </div>
                  )}
                  {kioskMode && kioskShareUrl ? (
                    <a
                      className="pf-node pf-node--kiosk-qr"
                      data-pos="bottom-center"
                      href={kioskShareUrl}
                      aria-label={t('pageShareQrAsideAria')}
                    >
                      <PortStickerQrImage
                        url={kioskShareUrl}
                        size={200}
                        alt={t('sharePageQrAlt')}
                      />
                    </a>
                  ) : null}
                </div>
              </div>
              <div id="pf-error" className="pf-error" hidden={!loadError}>
                {loadError}
              </div>
            </div>
              </div>
              {kioskMode ? (
                <KioskFleetGenConsChart
                  deyeItems={deyeCombinedItems}
                  huaweiItems={huaweiListReady ? huaweiRows.items : []}
                  t={t}
                  getBcp47Locale={getBcp47Locale}
                />
              ) : null}
            </div>

            <div className="pf-lang-port-bar" style={{ '--pf-graph-anchor-pct': `${graphAnchorPct}%` }}>
              <div className="pf-lang-port-port-track">
                <div className="pf-lang-port-port-align">
                  <span
                    className="pf-ev-ports-used-count"
                    aria-label={`${t('stationPlaceholder')}: ${evPortsUsedCount} x`}
                  >
                    {evPortsUsedCount} x
                  </span>
                  <select
                    id="pf-station"
                    className="pf-inverter-select pf-header-select--port"
                    aria-label={t('stationLabel')}
                    title={t('stationPlaceholder')}
                    value={stationFilter}
                    onChange={onStationChange}
                  >
                    <option value="">{chargingPorts.loading ? '…' : t('stationPlaceholder')}</option>
                    {portSelectOptions.map(row => {
                      const num = String(row.number);
                      const maxW = Number(row.maxPowerWt);
                      const maxLabel = Number.isFinite(maxW) && maxW > 0 ? ` · ${formatPower(maxW, t, bcp47)}` : '';
                      return (
                        <option key={num} value={num}>
                          {num}
                          {maxLabel}
                        </option>
                      );
                    })}
                  </select>
                </div>
              </div>
            </div>

            <section className="pf-dam-section" aria-label={t('damChartHeading')}>
              <DamChartPanel
                variant="embedded"
                inverterSn={essSel.provider === 'deye' ? selInverterSn || undefined : undefined}
                huaweiStationCode={
                  essSel.provider === 'huawei' && huaweiListReady && !huaweiRows.error
                    ? selHuaweiStationCode || undefined
                    : undefined
                }
                evPortsAcdc={selEvPortsAcdc || undefined}
                liveEvPortsPowerW={
                  selEvPortsAcdc && evPortsLive.powerW != null ? Number(evPortsLive.powerW) : undefined
                }
                t={t}
                getBcp47Locale={getBcp47Locale}
                chartHeight={320}
              />
            </section>

            <div className="pf-post-charts-bar">
              <div className="pf-roi-bar">
                <RoiStackStatistics
                  t={t}
                  bcp47={bcp47}
                  selInverterSn={selInverterSn}
                  inverterHeaderOk={inverterListReady}
                  inverterListPending={inverterRows.loading && !inverterRows.error}
                  pinRequired={remoteWriteConfigured}
                  cachedPin={cachedWritePin}
                  pinCacheBust={pinCacheBust}
                  onPinRemembered={() => setPinCacheBust(x => x + 1)}
                  onRoiCapexSaved={loadInverters}
                />
              </div>
              {showPowerFlowSections ? (
                !inverterListReady && !selEvPortsAggregate ? (
                  <div className="pf-header-discharge-row pf-header-discharge-row--skeleton" aria-busy="true">
                    <div className="pf-discharge-toolbar pf-discharge-toolbar--combined pf-discharge-toolbar--skeleton">
                      <div className="pf-discharge-skeleton-rows" aria-hidden>
                        <div className="pf-discharge-skeleton-row" />
                        <div className="pf-discharge-skeleton-row" />
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    {selHuaweiStationCode || selEvPortsAggregate ? null : (
                      <div className="pf-header-discharge-row">
                        <div className="pf-discharge-toolbar pf-discharge-toolbar--combined">
                          <div className="pf-deye-command-stack">
                            <div className="pf-grid-discharge-actions pf-grid-discharge-actions--header pf-deye-command-line">
                              <div className="pf-discharge-delta-controls">
                                <span
                                  className="pf-discharge-go-hover-wrap"
                                  onMouseEnter={onDischargeGoWrapMouseEnter}
                                  onMouseLeave={onDischargeGoWrapMouseLeave}
                                >
                                  {dischargeHoverTipOpen ? (
                                    <span
                                      id="pf-discharge-go-tooltip"
                                      role="tooltip"
                                      className="pf-discharge-go-tooltip"
                                    >
                                      {dischargeHoverTipText}
                                    </span>
                                  ) : null}
                                  <button
                                    type="button"
                                    className="pf-discharge-btn pf-discharge-go-btn"
                                    onClick={requestDischarge2Pct}
                                    disabled={
                                      deyeWritesHardBlocked ||
                                      toolbarLockedByNightCharge ||
                                      dischargeGoDisabledInsufficientSoc ||
                                      (Boolean(selInverterSn.trim()) && !essSocHasKey)
                                    }
                                    aria-label={t('dischargeGoAria')}
                                    aria-describedby={dischargeHoverTipOpen ? 'pf-discharge-go-tooltip' : undefined}
                                  >
                                    {t('dischargeGoButton')}
                                  </button>
                                </span>
                                <select
                                  id="pf-discharge-delta-select"
                                  className="pf-discharge-delta-select pf-discharge-delta-select--header"
                                  value={String(dischargeSocDeltaPct)}
                                  disabled={deyeWritesHardBlocked || toolbarLockedByNightCharge}
                                  aria-label={t('dischargeSocDeltaAria')}
                                  onChange={e => {
                                    if (!remoteWriteConfigured) {
                                      setRemoteWriteNeedsPinOpen(true);
                                      return;
                                    }
                                    const n = normalizeDischargeSocDeltaPct(e.target.value);
                                    const apiPct = peakPrefDischargePctForApi(n);
                                    const cached = readCachedInverterPin(selInverterSn?.trim() || '');
                                    if (cached) {
                                      void (async () => {
                                        try {
                                          const data = await savePeakAutoPref(
                                            peakDamEnabledRef.current,
                                            apiPct,
                                            cached
                                          );
                                          setDischargeSocDeltaPct(n);
                                          if (data && typeof data.enabled === 'boolean') {
                                            setPeakDamDischargeEnabled(data.enabled);
                                          }
                                          const p = data?.dischargeSocDeltaPct;
                                          if (p != null && Number.isFinite(Number(p))) {
                                            setDischargeSocDeltaPct(normalizeDischargeSocDeltaPct(p));
                                          }
                                        } catch (err) {
                                          const m = err instanceof Error ? err.message : String(err);
                                          setDischarge2Feedback(`${t('peakDamDischargeSaveError')}: ${m}`);
                                        }
                                      })();
                                      return;
                                    }
                                    if (selInverterEvportBound) {
                                      void (async () => {
                                        try {
                                          const data = await savePeakAutoPref(peakDamEnabledRef.current, apiPct, '');
                                          setDischargeSocDeltaPct(n);
                                          if (data && typeof data.enabled === 'boolean') {
                                            setPeakDamDischargeEnabled(data.enabled);
                                          }
                                          const p = data?.dischargeSocDeltaPct;
                                          if (p != null && Number.isFinite(Number(p))) {
                                            setDischargeSocDeltaPct(normalizeDischargeSocDeltaPct(p));
                                          }
                                        } catch (err) {
                                          const m = err instanceof Error ? err.message : String(err);
                                          setDischarge2Feedback(`${t('peakDamDischargeSaveError')}: ${m}`);
                                        }
                                      })();
                                      return;
                                    }
                                    setWritePinGate({ kind: 'peakPct', nextPct: apiPct });
                                  }}
                                >
                                  {DISCHARGE_TARGET_SOC_OPTIONS.map(o => (
                                    <option key={o} value={o}>
                                      {t('dischargeTillSocOption', { pct: o })}
                                    </option>
                                  ))}
                                </select>
                              </div>
                              <DelayedHintTooltip hintText={peakDamHintWithTillSoc.hint}>
                                <label className="pf-peak-dam-toggle pf-peak-dam-toggle--header">
                                  <input
                                    type="checkbox"
                                    checked={peakDamDischargeEnabled}
                                    disabled={deyeWritesHardBlocked || toolbarLockedByNightCharge}
                                    onChange={async e => {
                                      if (!remoteWriteConfigured) {
                                        setRemoteWriteNeedsPinOpen(true);
                                        return;
                                      }
                                      const v = e.target.checked;
                                      const sn = selInverterSn?.trim();
                                      if (!sn) return;
                                      const prev = peakDamDischargeEnabled;
                                      const prevPct = dischargeSocDeltaPct;
                                      if (peakPrefSaveTimerRef.current != null) {
                                        clearTimeout(peakPrefSaveTimerRef.current);
                                        peakPrefSaveTimerRef.current = null;
                                      }
                                      if (chargePrefSaveTimerRef.current != null) {
                                        clearTimeout(chargePrefSaveTimerRef.current);
                                        chargePrefSaveTimerRef.current = null;
                                      }
                                      const cached = readCachedInverterPin(sn);
                                      if (cached) {
                                        setPeakDamDischargeEnabled(v);
                                        setDischarge2Feedback('');
                                        try {
                                          const data = await savePeakAutoPref(
                                            v,
                                            peakPrefDischargePctForApi(dischargeSocDeltaPct),
                                            cached
                                          );
                                          if (data && typeof data.enabled === 'boolean') {
                                            setPeakDamDischargeEnabled(data.enabled);
                                          }
                                          const p = data?.dischargeSocDeltaPct;
                                          if (p != null && Number.isFinite(Number(p))) {
                                            setDischargeSocDeltaPct(normalizeDischargeSocDeltaPct(p));
                                          }
                                        } catch (err) {
                                          setPeakDamDischargeEnabled(prev);
                                          setDischargeSocDeltaPct(prevPct);
                                          const m = err instanceof Error ? err.message : String(err);
                                          setDischarge2Feedback(`${t('peakDamDischargeSaveError')}: ${m}`);
                                        }
                                        return;
                                      }
                                      if (selInverterEvportBound) {
                                        setPeakDamDischargeEnabled(v);
                                        setDischarge2Feedback('');
                                        try {
                                          const data = await savePeakAutoPref(
                                            v,
                                            peakPrefDischargePctForApi(dischargeSocDeltaPct),
                                            ''
                                          );
                                          if (data && typeof data.enabled === 'boolean') {
                                            setPeakDamDischargeEnabled(data.enabled);
                                          }
                                          const p = data?.dischargeSocDeltaPct;
                                          if (p != null && Number.isFinite(Number(p))) {
                                            setDischargeSocDeltaPct(normalizeDischargeSocDeltaPct(p));
                                          }
                                        } catch (err) {
                                          setPeakDamDischargeEnabled(prev);
                                          setDischargeSocDeltaPct(prevPct);
                                          const m = err instanceof Error ? err.message : String(err);
                                          setDischarge2Feedback(`${t('peakDamDischargeSaveError')}: ${m}`);
                                        }
                                        return;
                                      }
                                      setWritePinGate({
                                        kind: 'peak',
                                        nextEnabled: v,
                                        nextPct: peakPrefDischargePctForApi(dischargeSocDeltaPct),
                                      });
                                    }}
                                    aria-label={peakDamHintWithTillSoc.aria}
                                  />
                                  <span className="pf-peak-dam-toggle-label">{t('peakDamDischargeToggle')}</span>
                                </label>
                              </DelayedHintTooltip>
                              <DelayedHintTooltip hintText={selfConsumptionHintWithLcoe.hint}>
                                <label className="pf-peak-dam-toggle pf-peak-dam-toggle--header">
                                  <input
                                    type="checkbox"
                                    checked={nightChargeEnabled || selfConsumptionEnabled}
                                    disabled={deyeWritesHardBlocked || toolbarLockedByNightCharge}
                                    onChange={async e => {
                                      if (!remoteWriteConfigured) {
                                        setRemoteWriteNeedsPinOpen(true);
                                        return;
                                      }
                                      const v = e.target.checked;
                                      const sn = selInverterSn?.trim();
                                      if (!sn) return;
                                      const prev = selfConsumptionEnabled;
                                      const cached = readCachedInverterPin(sn);
                                      if (cached) {
                                        setSelfConsumptionEnabled(v);
                                        setDischarge2Feedback('');
                                        try {
                                          const data = await saveSelfConsumptionPref(v, cached);
                                          if (data && typeof data.selfConsumptionEnabled === 'boolean') {
                                            setSelfConsumptionEnabled(data.selfConsumptionEnabled);
                                          } else if (data && typeof data.enabled === 'boolean') {
                                            setSelfConsumptionEnabled(data.enabled);
                                          }
                                        } catch (err) {
                                          setSelfConsumptionEnabled(prev);
                                          const m = err instanceof Error ? err.message : String(err);
                                          setDischarge2Feedback(`${t('selfConsumptionSaveError')}: ${m}`);
                                        }
                                        return;
                                      }
                                      if (selInverterEvportBound) {
                                        setSelfConsumptionEnabled(v);
                                        setDischarge2Feedback('');
                                        try {
                                          const data = await saveSelfConsumptionPref(v, '');
                                          if (data && typeof data.selfConsumptionEnabled === 'boolean') {
                                            setSelfConsumptionEnabled(data.selfConsumptionEnabled);
                                          } else if (data && typeof data.enabled === 'boolean') {
                                            setSelfConsumptionEnabled(data.enabled);
                                          }
                                        } catch (err) {
                                          setSelfConsumptionEnabled(prev);
                                          const m = err instanceof Error ? err.message : String(err);
                                          setDischarge2Feedback(`${t('selfConsumptionSaveError')}: ${m}`);
                                        }
                                        return;
                                      }
                                      setWritePinGate({ kind: 'selfConsumption', nextEnabled: v });
                                    }}
                                    aria-label={selfConsumptionHintWithLcoe.aria}
                                  />
                                  <span className="pf-peak-dam-toggle-label">{t('selfConsumptionToggle')}</span>
                                </label>
                              </DelayedHintTooltip>
                            </div>
                            <div className="pf-grid-discharge-actions pf-grid-discharge-actions--header pf-deye-command-line pf-deye-command-line--charge">
                              <div className="pf-discharge-delta-controls">
                                <button
                                  type="button"
                                  className="pf-discharge-btn pf-discharge-go-btn pf-charge-go-btn"
                                  onClick={requestCharge2Pct}
                                  disabled={deyeWritesHardBlocked || toolbarLockedByNightCharge}
                                  title={t('chargeSoc2Hint')}
                                  aria-label={t('chargeGoAria')}
                                >
                                  {t('chargeGoButton')}
                                </button>
                                <select
                                  id="pf-charge-delta-select"
                                  className="pf-discharge-delta-select pf-discharge-delta-select--header"
                                  value={chargeSocDeltaPct}
                                  disabled={deyeWritesHardBlocked || toolbarLockedByNightCharge}
                                  aria-label={t('chargeSocDeltaAria')}
                                  onChange={e => {
                                    if (!remoteWriteConfigured) {
                                      setRemoteWriteNeedsPinOpen(true);
                                      return;
                                    }
                                    const n = normalizeChargeSocDeltaPct(e.target.value);
                                    const cached = readCachedInverterPin(selInverterSn?.trim() || '');
                                    if (cached) {
                                      void (async () => {
                                        try {
                                          const data = await saveLowDamChargePref(lowDamEnabledRef.current, n, cached);
                                          setChargeSocDeltaPct(n);
                                          if (data && typeof data.enabled === 'boolean') {
                                            setLowDamChargeEnabled(data.enabled);
                                          }
                                          const p = data?.chargeSocDeltaPct;
                                          if (p != null && Number.isFinite(Number(p))) {
                                            setChargeSocDeltaPct(normalizeChargeSocDeltaPct(p));
                                          }
                                        } catch (err) {
                                          const m = err instanceof Error ? err.message : String(err);
                                          setDischarge2Feedback(`${t('lowDamChargeSaveError')}: ${m}`);
                                        }
                                      })();
                                      return;
                                    }
                                    if (selInverterEvportBound) {
                                      void (async () => {
                                        try {
                                          const data = await saveLowDamChargePref(lowDamEnabledRef.current, n, '');
                                          setChargeSocDeltaPct(n);
                                          if (data && typeof data.enabled === 'boolean') {
                                            setLowDamChargeEnabled(data.enabled);
                                          }
                                          const p = data?.chargeSocDeltaPct;
                                          if (p != null && Number.isFinite(Number(p))) {
                                            setChargeSocDeltaPct(normalizeChargeSocDeltaPct(p));
                                          }
                                        } catch (err) {
                                          const m = err instanceof Error ? err.message : String(err);
                                          setDischarge2Feedback(`${t('lowDamChargeSaveError')}: ${m}`);
                                        }
                                      })();
                                      return;
                                    }
                                    setWritePinGate({ kind: 'lowPct', nextPct: n });
                                  }}
                                >
                                  {CHARGE_SOC_DELTA_OPTIONS.map(o => (
                                    <option key={o} value={o}>
                                      {t('chargeSocDeltaValue', { pct: o })}
                                    </option>
                                  ))}
                                </select>
                              </div>
                              <label className="pf-peak-dam-toggle pf-peak-dam-toggle--header">
                                <input
                                  type="checkbox"
                                  checked={lowDamChargeEnabled}
                                  disabled={deyeWritesHardBlocked || toolbarLockedByNightCharge}
                                  onChange={async e => {
                                    if (!remoteWriteConfigured) {
                                      setRemoteWriteNeedsPinOpen(true);
                                      return;
                                    }
                                    const v = e.target.checked;
                                    const sn = selInverterSn?.trim();
                                    if (!sn) return;
                                    const prev = lowDamChargeEnabled;
                                    const prevPct = chargeSocDeltaPct;
                                    if (peakPrefSaveTimerRef.current != null) {
                                      clearTimeout(peakPrefSaveTimerRef.current);
                                      peakPrefSaveTimerRef.current = null;
                                    }
                                    if (chargePrefSaveTimerRef.current != null) {
                                      clearTimeout(chargePrefSaveTimerRef.current);
                                      chargePrefSaveTimerRef.current = null;
                                    }
                                    const cached = readCachedInverterPin(sn);
                                    if (cached) {
                                      setLowDamChargeEnabled(v);
                                      setDischarge2Feedback('');
                                      try {
                                        const data = await saveLowDamChargePref(v, chargeSocDeltaPct, cached);
                                        if (data && typeof data.enabled === 'boolean') {
                                          setLowDamChargeEnabled(data.enabled);
                                        }
                                        const p = data?.chargeSocDeltaPct;
                                        if (p != null && Number.isFinite(Number(p))) {
                                          setChargeSocDeltaPct(normalizeChargeSocDeltaPct(p));
                                        }
                                      } catch (err) {
                                        setLowDamChargeEnabled(prev);
                                        setChargeSocDeltaPct(prevPct);
                                        const m = err instanceof Error ? err.message : String(err);
                                        setDischarge2Feedback(`${t('lowDamChargeSaveError')}: ${m}`);
                                      }
                                      return;
                                    }
                                    if (selInverterEvportBound) {
                                      setLowDamChargeEnabled(v);
                                      setDischarge2Feedback('');
                                      try {
                                        const data = await saveLowDamChargePref(v, chargeSocDeltaPct, '');
                                        if (data && typeof data.enabled === 'boolean') {
                                          setLowDamChargeEnabled(data.enabled);
                                        }
                                        const p = data?.chargeSocDeltaPct;
                                        if (p != null && Number.isFinite(Number(p))) {
                                          setChargeSocDeltaPct(normalizeChargeSocDeltaPct(p));
                                        }
                                      } catch (err) {
                                        setLowDamChargeEnabled(prev);
                                        setChargeSocDeltaPct(prevPct);
                                        const m = err instanceof Error ? err.message : String(err);
                                        setDischarge2Feedback(`${t('lowDamChargeSaveError')}: ${m}`);
                                      }
                                      return;
                                    }
                                    setWritePinGate({
                                      kind: 'low',
                                      nextEnabled: v,
                                      nextPct: chargeSocDeltaPct,
                                    });
                                  }}
                                  aria-label={t('lowDamChargeToggleAria')}
                                />
                                <span className="pf-peak-dam-toggle-label" title={t('lowDamChargeToggleHint')}>
                                  {t('lowDamChargeToggle')}
                                </span>
                              </label>
                              <label className="pf-peak-dam-toggle pf-peak-dam-toggle--header">
                                <input
                                  type="checkbox"
                                  checked={nightChargeEnabled}
                                  disabled={deyeWritesHardBlocked}
                                  onChange={async e => {
                                    if (!remoteWriteConfigured) {
                                      setRemoteWriteNeedsPinOpen(true);
                                      return;
                                    }
                                    const v = e.target.checked;
                                    const sn = selInverterSn?.trim();
                                    if (!sn) return;
                                    const prevNight = nightChargeEnabled;
                                    const prevPeak = peakDamDischargeEnabled;
                                    const prevLow = lowDamChargeEnabled;
                                    const prevSc = selfConsumptionEnabled;
                                    const prevChargePct = chargeSocDeltaPct;
                                    if (peakPrefSaveTimerRef.current != null) {
                                      clearTimeout(peakPrefSaveTimerRef.current);
                                      peakPrefSaveTimerRef.current = null;
                                    }
                                    if (chargePrefSaveTimerRef.current != null) {
                                      clearTimeout(chargePrefSaveTimerRef.current);
                                      chargePrefSaveTimerRef.current = null;
                                    }
                                    const cached = readCachedInverterPin(sn);
                                    const pct = chargeSocDeltaPct;
                                    if (cached) {
                                      setNightChargeEnabled(v);
                                      if (v) {
                                        setPeakDamDischargeEnabled(false);
                                        setLowDamChargeEnabled(false);
                                        setSelfConsumptionEnabled(true);
                                      }
                                      setDischarge2Feedback('');
                                      try {
                                        const data = await saveNightChargePref(v, pct, cached);
                                        applyNightChargeToolbarSnap(data);
                                      } catch (err) {
                                        setNightChargeEnabled(prevNight);
                                        setPeakDamDischargeEnabled(prevPeak);
                                        setLowDamChargeEnabled(prevLow);
                                        setSelfConsumptionEnabled(prevSc);
                                        setChargeSocDeltaPct(prevChargePct);
                                        const m = err instanceof Error ? err.message : String(err);
                                        setDischarge2Feedback(`${t('nightChargeSaveError')}: ${m}`);
                                      }
                                      return;
                                    }
                                    if (selInverterEvportBound) {
                                      setNightChargeEnabled(v);
                                      if (v) {
                                        setPeakDamDischargeEnabled(false);
                                        setLowDamChargeEnabled(false);
                                        setSelfConsumptionEnabled(true);
                                      }
                                      setDischarge2Feedback('');
                                      try {
                                        const data = await saveNightChargePref(v, pct, '');
                                        applyNightChargeToolbarSnap(data);
                                      } catch (err) {
                                        setNightChargeEnabled(prevNight);
                                        setPeakDamDischargeEnabled(prevPeak);
                                        setLowDamChargeEnabled(prevLow);
                                        setSelfConsumptionEnabled(prevSc);
                                        setChargeSocDeltaPct(prevChargePct);
                                        const m = err instanceof Error ? err.message : String(err);
                                        setDischarge2Feedback(`${t('nightChargeSaveError')}: ${m}`);
                                      }
                                      return;
                                    }
                                    setWritePinGate({
                                      kind: 'nightCharge',
                                      nextEnabled: v,
                                      nextPct: pct,
                                    });
                                  }}
                                  aria-label={t('nightChargeToggleAria')}
                                />
                                <span className="pf-peak-dam-toggle-label" title={t('nightChargeToggleHint')}>
                                  {t('nightChargeToggle')}
                                </span>
                              </label>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </>
                )
              ) : null}
            </div>

            {dischargeFeedbackText ? (
              <div className="pf-discharge-feedback" role="status">
                <p>{dischargeFeedbackText}</p>
              </div>
            ) : null}

            <aside className="pf-ukraine-qr" aria-label={t('qrAsideAria')}>
              <a className="pf-ukraine-qr-link" href={QR_SUPPORT_URL} target="_blank" rel="noopener noreferrer">
                <img
                  className="pf-ukraine-qr-img"
                  src={`${qrBase}/static/power-flow/protect-ukraine-qr.png`}
                  width={120}
                  height={120}
                  alt={t('qrImageAlt')}
                  decoding="async"
                />
                <span className="pf-ukraine-qr-caption">{t('qrCaption')}</span>
              </a>
            </aside>

            {pageRestHydrationPending ? (
              <div className="pf-page-rest-pending-overlay" aria-hidden="true">
                <div className="pf-page-rest-pending-loader">
                  <img
                    className="pf-page-rest-pending-loader__logo"
                    src={VYRIY_EMS_LOGO_SRC}
                    alt=""
                    width={120}
                    height={120}
                    decoding="async"
                  />
                </div>
              </div>
            ) : null}

            <section
              className="pf-rdn-callback-section pf-rdn-callback-section--page-end"
              aria-label={t('rdnCallbackSectionAria')}
            >
              <RdnConsultationCallback t={t} />
            </section>
          </div>

          {nodePopup ? (
            <div className="pf-modal-backdrop pf-node-popup-backdrop" role="presentation" onClick={closeNodePopup}>
              <div
                className="pf-modal pf-node-popup-modal"
                role="dialog"
                aria-modal="true"
                aria-label={nodePopup.title || 'Node details'}
                onClick={e => e.stopPropagation()}
              >
                <div className="pf-node pf-node-popup-tile" dangerouslySetInnerHTML={{ __html: nodePopup.html }} />
                {nodePopup.actionHref ? (
                  <a
                    className="pf-modal-btn pf-modal-btn--primary pf-node-popup-link"
                    href={nodePopup.actionHref}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {nodePopup.actionLabel || nodePopup.actionHref}
                  </a>
                ) : null}
              </div>
            </div>
          ) : null}

          {dischargeConfirmOpen && essSocPercent != null && Number.isFinite(Number(essSocPercent)) ? (
            <div className="pf-modal-backdrop" role="presentation" onClick={cancelDischargeConfirm}>
              <div
                className="pf-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="pf-discharge-confirm-title"
                onClick={e => e.stopPropagation()}
              >
                <p id="pf-discharge-confirm-title" className="pf-modal-message">
                  {t('dischargeConfirmMessage', {
                    from: inverterSocFmt.format(Number(essSocPercent)),
                    to: inverterSocFmt.format(Math.round(Number(dischargeSocDeltaPct))),
                  })}
                </p>
                {selInverterPinRequired && !cachedWritePin ? (
                  <div className="pf-modal-pin-row">
                    <label htmlFor="pf-discharge-confirm-pin" className="pf-modal-pin-label">
                      {t('deyeWritePinLabel')}
                    </label>
                    <input
                      id="pf-discharge-confirm-pin"
                      type="password"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      className="pf-modal-pin-input"
                      value={dischargeConfirmPin}
                      onChange={e => setDischargeConfirmPin(e.target.value)}
                      aria-label={t('deyeWritePinLabel')}
                    />
                  </div>
                ) : null}
                <div className="pf-modal-actions">
                  <button
                    type="button"
                    className="pf-modal-btn pf-modal-btn--secondary"
                    onClick={cancelDischargeConfirm}
                  >
                    {t('dischargeConfirmCancel')}
                  </button>
                  <button
                    type="button"
                    className="pf-modal-btn pf-modal-btn--primary"
                    onClick={confirmDischargeFromModal}
                  >
                    {t('dischargeConfirmOk')}
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          {chargeConfirmOpen && essSocPercent != null && Number.isFinite(Number(essSocPercent)) ? (
            <div className="pf-modal-backdrop" role="presentation" onClick={cancelChargeConfirm}>
              <div
                className="pf-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="pf-charge-confirm-title"
                onClick={e => e.stopPropagation()}
              >
                <p id="pf-charge-confirm-title" className="pf-modal-message">
                  {t('chargeConfirmMessage', {
                    from: inverterSocFmt.format(Number(essSocPercent)),
                    to: inverterSocFmt.format(Math.min(100, Number(essSocPercent) + chargeSocDeltaPct)),
                  })}
                </p>
                {selInverterPinRequired && !cachedWritePin ? (
                  <div className="pf-modal-pin-row">
                    <label htmlFor="pf-charge-confirm-pin" className="pf-modal-pin-label">
                      {t('deyeWritePinLabel')}
                    </label>
                    <input
                      id="pf-charge-confirm-pin"
                      type="password"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      className="pf-modal-pin-input"
                      value={chargeConfirmPin}
                      onChange={e => setChargeConfirmPin(e.target.value)}
                      aria-label={t('deyeWritePinLabel')}
                    />
                  </div>
                ) : null}
                <div className="pf-modal-actions">
                  <button type="button" className="pf-modal-btn pf-modal-btn--secondary" onClick={cancelChargeConfirm}>
                    {t('chargeConfirmCancel')}
                  </button>
                  <button
                    type="button"
                    className="pf-modal-btn pf-modal-btn--primary pf-modal-btn--charge"
                    onClick={confirmChargeFromModal}
                  >
                    {t('chargeConfirmOk')}
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          {remoteWriteNeedsPinOpen ? (
            <div className="pf-modal-backdrop" role="presentation" onClick={closeRemoteWriteNeedsPinModal}>
              <div
                className="pf-modal pf-modal--remote-write-needs-pin"
                role="alertdialog"
                aria-modal="true"
                aria-labelledby="pf-remote-write-needs-pin-title"
                onClick={e => e.stopPropagation()}
              >
                <p id="pf-remote-write-needs-pin-title" className="pf-modal-message pf-modal-message--multiline">
                  {t('deyeRemoteWriteNeedsPin')}
                </p>
                <div className="pf-modal-actions">
                  <button
                    type="button"
                    className="pf-modal-btn pf-modal-btn--primary"
                    onClick={closeRemoteWriteNeedsPinModal}
                  >
                    {t('deyeRemoteWriteNeedsPinOk')}
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          {writePinGate ? (
            <div className="pf-modal-backdrop" role="presentation" onClick={cancelWritePinGate}>
              <div
                className="pf-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="pf-write-pin-title"
                onClick={e => e.stopPropagation()}
              >
                <p id="pf-write-pin-title" className="pf-modal-message">
                  {writePinGate.kind === 'peak'
                    ? t('deyeWritePinTitlePeak')
                    : writePinGate.kind === 'low'
                      ? t('deyeWritePinTitleLow')
                      : writePinGate.kind === 'peakPct'
                        ? t('deyeWritePinTitlePeakPct')
                        : writePinGate.kind === 'lowPct'
                          ? t('deyeWritePinTitleLowPct')
                          : writePinGate.kind === 'selfConsumption'
                            ? t('deyeWritePinTitleSelfConsumption')
                            : writePinGate.kind === 'nightCharge'
                              ? t('deyeWritePinTitleNightCharge')
                              : t('deyeWritePinTitleLowPct')}
                </p>
                <div className="pf-modal-pin-row">
                  <label htmlFor="pf-write-pin-input" className="pf-modal-pin-label">
                    {t('deyeWritePinLabel')}
                  </label>
                  <input
                    id="pf-write-pin-input"
                    type="password"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    className="pf-modal-pin-input"
                    value={writePinValue}
                    onChange={e => setWritePinValue(e.target.value)}
                    aria-label={t('deyeWritePinLabel')}
                  />
                </div>
                {writePinError ? (
                  <p className="pf-modal-pin-error" role="alert">
                    {writePinError}
                  </p>
                ) : null}
                <div className="pf-modal-actions">
                  <button type="button" className="pf-modal-btn pf-modal-btn--secondary" onClick={cancelWritePinGate}>
                    {t('dischargeConfirmCancel')}
                  </button>
                  <button
                    type="button"
                    className="pf-modal-btn pf-modal-btn--primary"
                    onClick={() => void submitWritePinGate()}
                  >
                    {t('deyeWritePinConfirm')}
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          {deyeCommandModal ? (
            <div
              className="pf-modal-backdrop"
              role="presentation"
              onClick={deyeCommandModal.phase === 'result' ? closeDeyeCommandModal : undefined}
            >
              <div
                className="pf-modal pf-modal--deye-command"
                role="dialog"
                aria-modal="true"
                aria-busy={deyeCommandModal.phase === 'loading' ? 'true' : 'false'}
                aria-labelledby={
                  deyeCommandModal.phase === 'loading'
                    ? 'pf-deye-command-loading-title'
                    : 'pf-deye-command-result-title'
                }
                onClick={e => e.stopPropagation()}
              >
                {deyeCommandModal.phase === 'loading' ? (
                  <>
                    <div className="pf-modal-loading" aria-live="polite">
                      <img
                        className="pf-modal-loader-logo"
                        src={VYRIY_EMS_LOGO_SRC}
                        alt=""
                        width={38}
                        height={38}
                        decoding="async"
                      />
                      <p id="pf-deye-command-loading-title" className="pf-modal-message">
                        {t('deyeCommandWaiting')}
                      </p>
                    </div>
                  </>
                ) : (
                  <>
                    <p
                      id="pf-deye-command-result-title"
                      className={`pf-modal-message pf-modal-message--multiline${
                        deyeCommandModal.ok ? '' : ' pf-modal-message--error'
                      }`}
                    >
                      {deyeCommandModal.message}
                    </p>
                    <div className="pf-modal-actions">
                      <button
                        type="button"
                        className="pf-modal-btn pf-modal-btn--primary"
                        onClick={closeDeyeCommandModal}
                      >
                        {t('deyeCommandResultClose')}
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : null}
        </div>
        <DeyeInverterMessengerModal open={deyeMessengerOpen} onClose={closeDeyeMessenger} t={t} />
        <PeakExportHourlyChartModal
          open={exportHourlyChartOpen}
          onClose={() => setExportHourlyChartOpen(false)}
          fetchUrl={peakHourlyChartFetchUrl}
          chartKind={peakHourlyChartKind}
          hourlyScope={exportHourlyScope}
          exportRevenueUah={
            landingExportMetricOffers.arbitrage && landingExportMetric === LANDING_EXPORT_METRIC.ARBITRAGE
          }
          t={t}
        />
        <MonthlyRetailTariffChartModal
          open={monthlyRatesChartOpen}
          onClose={() => setMonthlyRatesChartOpen(false)}
          fetchUrl={monthlyRatesChartFetchUrl}
          bcp47={bcp47}
          t={t}
          isDark={isDark}
        />
        <GridBalancingChartModal
          open={gridBalancingChartOpen}
          onClose={() => setGridBalancingChartOpen(false)}
          fetchUrl={gridBalancingChartFetchUrl}
          bcp47={bcp47}
          t={t}
          isDark={isDark}
        />
      </div>
    </KwhCalibrationProvider>
  );
}
