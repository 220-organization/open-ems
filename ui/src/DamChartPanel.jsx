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

const DAM_INDEX_KEYS = ['DAY', 'NIGHT', 'PEAK', 'HPEAK', 'BASE'];

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

function clampTradeDayIso(iso) {
  const cap = maxTradeDayKyivIso();
  return iso > cap ? cap : iso;
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
    const h = p?.hourlyPriceDamUahPerKwh;
    if (!Array.isArray(h)) continue;
    for (const x of h) {
      if (x != null && Number.isFinite(Number(x))) all.push(Number(x));
    }
  }
  if (!all.length) return null;
  return all.reduce((a, b) => a + b, 0) / all.length;
}

/** Compare DAM at Kyiv current hour vs previous hour; for other days compare last two hours of the day. */
function hourComparisonIndices(tradeDayIso) {
  const todayKyiv = kyivCalendarIso();
  if (tradeDayIso === todayKyiv) {
    const hi = kyivHourIndexNowForDate(tradeDayIso);
    if (hi === null) {
      return { currentIdx: 23, prevIdx: 22, needPrevDay: false };
    }
    return {
      currentIdx: hi,
      prevIdx: hi > 0 ? hi - 1 : null,
      needPrevDay: hi === 0,
    };
  }
  return { currentIdx: 23, prevIdx: 22, needPrevDay: false };
}

const DAM_COMPARE_DAY = 'day';
const DAM_COMPARE_HOUR = 'hour';
const DAM_COMPARE_MONTH = 'month';

function computeNeededCompareDates(tradeDay, mode) {
  if (mode === DAM_COMPARE_DAY) {
    return [addCalendarDays(tradeDay, -1)];
  }
  if (mode === DAM_COMPARE_HOUR) {
    const h = hourComparisonIndices(tradeDay);
    return h.needPrevDay ? [addCalendarDays(tradeDay, -1)] : [];
  }
  if (mode === DAM_COMPARE_MONTH) {
    const mtd = listDaysInclusive(monthStartIso(tradeDay), tradeDay);
    const prev = prevMonthRangeIso(tradeDay);
    const set = new Set([...mtd.filter(d => d !== tradeDay), ...prev]);
    return [...set];
  }
  return [];
}

/** BASE index is one value per trade day — no hourly comparison; skip extra fetches for hour mode. */
function computeNeededBaseIndexCompareDates(tradeDay, mode) {
  if (mode === DAM_COMPARE_HOUR) {
    return [];
  }
  return computeNeededCompareDates(tradeDay, mode);
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

function initialTradeDayFullPage() {
  try {
    const q = new URLSearchParams(window.location.search).get('date');
    if (q && /^\d{4}-\d{2}-\d{2}$/.test(q)) return q;
  } catch {
    /* ignore */
  }
  return kyivCalendarIso();
}

function replaceUrlDate(isoDate) {
  try {
    const u = new URL(window.location.href);
    u.searchParams.set('date', isoDate);
    window.history.replaceState({}, '', u);
  } catch {
    /* ignore */
  }
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
const DAM_LEFT_Y_AXIS_WIDTH = 56;

/** Right SoC / placeholder axis width — bottom chart uses a hidden right axis with the same width so plot areas match. */
const DAM_RIGHT_Y_AXIS_WIDTH = 48;

/** Right grid-frequency (Hz) axis — extra width for 2-decimal locale + unit (e.g. 49,99 Гц). */
const DAM_HZ_Y_AXIS_WIDTH = 72;

/** Hour index on X-axis (data uses 1–24): show even ticks only. */
const DAM_HOUR_X_TICKS = Object.freeze([2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24]);

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
  const [tradeDay, setTradeDay] = useState(() =>
    clampTradeDayIso(variant === 'fullpage' ? initialTradeDayFullPage() : kyivCalendarIso())
  );
  const [payload, setPayload] = useState(null);
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
  /** Grid frequency (Hz) line on DAM chart — off by default. */
  const [showGridFrequencyLine, setShowGridFrequencyLine] = useState(false);
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

  const effectiveInverterSn = (
    (inverterSnProp && String(inverterSnProp).trim()) ||
    (variant === 'fullpage' ? urlInverterOnce : '')
  ).trim();

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

  /** DAM index chart values are UAH/kWh (API stores UAH/MWh). */
  const fmtIndexKwh = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 3,
      }),
    [bcp47]
  );

  const maxTradeDay = maxTradeDayKyivIso();

  useEffect(() => {
    if (tradeDay > maxTradeDay) setTradeDay(maxTradeDay);
  }, [tradeDay, maxTradeDay]);

  useEffect(() => {
    if (variant !== 'fullpage') return;
    replaceUrlDate(tradeDay);
  }, [tradeDay, variant]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const q = new URLSearchParams({ date: tradeDay });
      const r = await fetch(apiUrl(`/api/dam/chart-day?${q}`), { cache: 'no-store' });
      if (!r.ok) throw new Error((await r.text()) || r.statusText);
      const data = await r.json();
      setPayload(data);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
      setPayload(null);
    } finally {
      setLoading(false);
    }
  }, [tradeDay]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
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
  }, [tradeDay]);

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
            const r = await fetch(apiUrl(`/api/dam/chart-day?${q}`), { cache: 'no-store' });
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
  }, [tradeDay, damCompareMode]);

  useEffect(() => {
    let cancelled = false;
    const need = computeNeededBaseIndexCompareDates(tradeDay, baseIndexCompareMode);
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
  }, [tradeDay, baseIndexCompareMode]);

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
    if (!payload || !Array.isArray(payload.hourlyPriceDamUahPerKwh)) return [];
    const dam = payload.hourlyPriceDamUahPerKwh;
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
      return {
        hour: i + 1,
        damUahKwh: dam[i] != null && Number.isFinite(Number(dam[i])) ? Number(dam[i]) : null,
        socPercent,
        gridKw,
        gridFreqHz,
        gridKwLive: false,
        gridKwFromLoad: false,
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
    return out;
  }, [
    payload,
    socPayload,
    tradeDay,
    liveGridPowerW,
    liveLoadPowerW,
    livePvPowerW,
    liveBatteryPowerW,
    effectiveInverterSn,
  ]);

  const gridDomain = useMemo(() => {
    const vals = rows.map(r => r.gridKw).filter(v => v != null && Number.isFinite(v));
    if (!vals.length) return [-0.25, 0.25];
    const raw = Math.max(...vals.map(v => Math.abs(v)), 0.25);
    const cap = niceSymmetricCap(raw);
    return [-cap, cap];
  }, [rows]);

  const gridYTicks = useMemo(() => fiveSymmetricTicks(gridDomain[0], gridDomain[1]), [gridDomain]);

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
    if (!effectiveInverterSn) return 16;
    if (showGridFrequencyLine) return DAM_RIGHT_Y_AXIS_WIDTH + DAM_HZ_Y_AXIS_WIDTH + 28;
    return 52;
  }, [effectiveInverterSn, showGridFrequencyLine]);

  /** Same horizontal gutters + matched right-axis bands so LineChart and ComposedChart X domains align. */
  const damLineChartMargin = useMemo(
    () => ({
      top: 8,
      right: lineChartRightMargin,
      left: 8,
      bottom: 10,
    }),
    [lineChartRightMargin]
  );

  const damComposedChartMargin = useMemo(
    () => ({
      top: 6,
      right: lineChartRightMargin,
      left: 8,
      bottom: 28,
    }),
    [lineChartRightMargin]
  );

  const onDateInput = e => {
    const v = e.target.value;
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) setTradeDay(clampTradeDayIso(v));
  };

  const goPrev = () => setTradeDay(d => addCalendarDays(d, -1));
  const goNext = () =>
    setTradeDay(d => {
      const next = addCalendarDays(d, 1);
      const cap = maxTradeDayKyivIso();
      return next > cap ? cap : next;
    });

  const hasChart = Boolean(payload) && rows.length === 24;
  const hasAnyDamPrice = useMemo(
    () => rows.some(r => r.damUahKwh != null && Number.isFinite(Number(r.damUahKwh))),
    [rows]
  );

  const damTrendPct = useMemo(() => {
    if (!payload?.ok || !Array.isArray(payload.hourlyPriceDamUahPerKwh)) return null;
    if (compareLoading) return null;
    const dam = payload.hourlyPriceDamUahPerKwh;

    if (damCompareMode === DAM_COMPARE_DAY) {
      const prev = extraByDate[addCalendarDays(tradeDay, -1)]?.hourlyPriceDamUahPerKwh;
      const a = avgDamFromHourly(dam);
      const b = avgDamFromHourly(prev);
      if (a == null || b == null || b === 0) return null;
      return ((a - b) / b) * 100;
    }

    if (damCompareMode === DAM_COMPARE_HOUR) {
      const h = hourComparisonIndices(tradeDay);
      const cur = dam[h.currentIdx];
      let prev;
      if (h.needPrevDay) {
        const pd = extraByDate[addCalendarDays(tradeDay, -1)]?.hourlyPriceDamUahPerKwh;
        prev = Array.isArray(pd) ? pd[23] : null;
      } else {
        prev = h.prevIdx != null ? dam[h.prevIdx] : null;
      }
      if (
        cur == null ||
        prev == null ||
        !Number.isFinite(Number(cur)) ||
        !Number.isFinite(Number(prev)) ||
        Number(prev) === 0
      ) {
        return null;
      }
      return ((Number(cur) - Number(prev)) / Number(prev)) * 100;
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

  const damTrendCaptionKey =
    damCompareMode === DAM_COMPARE_HOUR
      ? 'damTrendCaptionHour'
      : damCompareMode === DAM_COMPARE_MONTH
        ? 'damTrendCaptionMonth'
        : 'damTrendCaptionDay';

  const damIndexChart = useMemo(() => {
    if (!indexesPayload?.ok || !indexesPayload?.data) return { tradeDay: '', rows: [] };
    const zone = pickDamIndexesZone(indexesPayload.data);
    if (!zone) return { tradeDay: '', rows: [] };
    return buildDamIndexRows(zone, t);
  }, [indexesPayload, t]);

  const baseIndexTrendPct = useMemo(() => {
    if (!indexesPayload?.ok || !indexesPayload.data) return null;
    if (baseIndexCompareLoading || indexesLoading) return null;

    if (baseIndexCompareMode === DAM_COMPARE_HOUR) {
      return null;
    }

    if (baseIndexCompareMode === DAM_COMPARE_DAY) {
      const a = basePriceUahMwhFromDamindexesPayload(indexesPayload);
      const b = basePriceUahMwhFromDamindexesPayload(
        baseIndexExtraByDate[addCalendarDays(tradeDay, -1)]
      );
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
  }, [
    indexesPayload,
    baseIndexExtraByDate,
    tradeDay,
    baseIndexCompareMode,
    baseIndexCompareLoading,
    indexesLoading,
  ]);

  const baseIndexTrendCaptionKey =
    baseIndexCompareMode === DAM_COMPARE_HOUR
      ? 'damTrendCaptionHour'
      : baseIndexCompareMode === DAM_COMPARE_MONTH
        ? 'damTrendCaptionMonth'
        : 'damTrendCaptionDay';

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
        <option value={DAM_COMPARE_HOUR}>{t('damCompareOptionHour')}</option>
        <option value={DAM_COMPARE_DAY}>{t('damCompareOptionDay')}</option>
        <option value={DAM_COMPARE_MONTH}>{t('damCompareOptionMonth')}</option>
      </select>
      <div className="dam-trend-line" aria-live="polite">
        {compareLoading || loading ? (
          <span className="dam-trend-line--muted">…</span>
        ) : damTrendPct == null ? (
          <span className="dam-trend-line--muted">—</span>
        ) : (
          <>
            <span className={damTrendPct >= 0 ? 'dam-trend-line--up' : 'dam-trend-line--down'}>
              {fmtPct.format(damTrendPct)}%
            </span>
            <span className="dam-trend-line-caption"> {t(damTrendCaptionKey)}</span>
          </>
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

      {!payload?.oreeConfigured ? (
        <div className="dam-banner dam-banner-warn" role="status">
          {t('damOreeNotConfigured')}
        </div>
      ) : null}

      {payload?.syncTriggered ? (
        <div className="dam-banner dam-banner-info" role="status">
          {t('damSyncNote')}
        </div>
      ) : null}

      {payload?.lazyOree?.exhausted && !hasAnyDamPrice ? (
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

        {effectiveInverterSn && hasChart && !loading ? (
          <label className="dam-freq-toggle">
            <input
              type="checkbox"
              checked={showGridFrequencyLine}
              onChange={e => setShowGridFrequencyLine(e.target.checked)}
            />
            <span>{t('damShowGridFreq')}</span>
          </label>
        ) : null}

        {!loading && hasChart ? (
          <div className="dam-recharts-wrap dam-recharts-wrap--line-stack" style={{ minHeight: `calc(${h}px + 42px)` }}>
            <ResponsiveContainer width="100%" height={h}>
              <LineChart data={rows} syncId="dam-day" margin={damLineChartMargin}>
                <CartesianGrid stroke="rgba(252, 1, 155, 0.12)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="hour"
                  type="number"
                  domain={[1, 24]}
                  ticks={DAM_HOUR_X_TICKS}
                  allowDecimals={false}
                  padding={{ left: 0, right: 0 }}
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="dam"
                  width={DAM_LEFT_Y_AXIS_WIDTH}
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                  tickLine={false}
                  tickFormatter={v => fmt1.format(v)}
                  axisLine={{ stroke: 'rgba(252, 1, 155, 0.25)' }}
                  label={{
                    value: t('damTariffAxis'),
                    angle: -90,
                    position: 'insideLeft',
                    offset: 10,
                    style: { fill: 'rgba(255,248,252,0.55)', fontSize: 11, textAnchor: 'end' },
                  }}
                />
                {effectiveInverterSn ? (
                  <YAxis
                    yAxisId="soc"
                    orientation="right"
                    domain={[0, 100]}
                    width={DAM_RIGHT_Y_AXIS_WIDTH}
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
                {effectiveInverterSn && showGridFrequencyLine ? (
                  <YAxis
                    yAxisId="hz"
                    orientation="right"
                    domain={hzDomain}
                    width={DAM_HZ_Y_AXIS_WIDTH}
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
                  separator=": "
                  contentStyle={{
                    background: 'rgba(24, 8, 32, 0.94)',
                    border: '1px solid rgba(252, 1, 155, 0.35)',
                    borderRadius: 10,
                    color: '#fff',
                  }}
                  labelStyle={{ color: 'rgba(255, 248, 252, 0.95)' }}
                  itemStyle={{ color: 'rgba(255, 248, 252, 0.95)' }}
                  formatter={(value, name) => {
                    if (value == null || value === '') return ['—', name];
                    const damSeriesName = t('damSeriesDam');
                    if (name === damSeriesName) {
                      const n = Number(value);
                      if (!Number.isFinite(n)) return ['—', t('damTooltipDamLabel')];
                      return [`${fmtDamTooltip.format(n)} ${t('damTooltipDamUnit')}`, t('damTooltipDamLabel')];
                    }
                    const socLabel = t('damSeriesSoc');
                    if (name === socLabel) return [`${fmt1.format(value)} %`, socLabel];
                    const hzLabel = t('damSeriesGridFreq');
                    if (name === hzLabel) return [`${fmtHz.format(value)} Hz`, hzLabel];
                    return [`${fmt1.format(value)}`, name];
                  }}
                  labelFormatter={hour => `${t('damHourTooltip')} ${hour}`}
                />
                <Line
                  yAxisId="dam"
                  type="monotone"
                  dataKey="damUahKwh"
                  name={t('damSeriesDam')}
                  stroke="#22c55e"
                  strokeWidth={2.2}
                  dot={{ r: 2.5, fill: '#22c55e' }}
                  connectNulls
                />
                {effectiveInverterSn ? (
                  <Line
                    yAxisId="soc"
                    type="monotone"
                    dataKey="socPercent"
                    name={t('damSeriesSoc')}
                    stroke="#60a5fa"
                    strokeWidth={2}
                    dot={{ r: 2.2, fill: '#60a5fa' }}
                    connectNulls
                  />
                ) : null}
                {effectiveInverterSn && showGridFrequencyLine ? (
                  <Line
                    yAxisId="hz"
                    type="monotone"
                    dataKey="gridFreqHz"
                    name={t('damSeriesGridFreq')}
                    stroke="#facc15"
                    strokeWidth={1.85}
                    dot={{ r: 2, fill: '#facc15' }}
                    connectNulls
                  />
                ) : null}
              </LineChart>
            </ResponsiveContainer>
            <ul className="dam-line-legend" aria-label={t('damChartHeading')}>
              <li className="dam-line-legend-item">
                <i className="dam-line-legend-swatch" style={{ background: '#22c55e' }} aria-hidden />
                {t('damSeriesDam')}
              </li>
              {effectiveInverterSn ? (
                <li className="dam-line-legend-item">
                  <i className="dam-line-legend-swatch" style={{ background: '#60a5fa' }} aria-hidden />
                  {t('damSeriesSoc')}
                </li>
              ) : null}
              {effectiveInverterSn && showGridFrequencyLine ? (
                <li className="dam-line-legend-item">
                  <i className="dam-line-legend-swatch" style={{ background: '#facc15' }} aria-hidden />
                  {t('damSeriesGridFreq')}
                </li>
              ) : null}
            </ul>
          </div>
        ) : null}

        {!loading && hasChart && effectiveInverterSn ? (
          <div className="dam-grid-bars-wrap">
            <p className="dam-grid-bars-caption">{t('damGridBarsCaption')}</p>
            <ResponsiveContainer width="100%" height={gridBarH}>
              <ComposedChart data={rows} syncId="dam-day" margin={damComposedChartMargin}>
                <CartesianGrid stroke="rgba(252, 1, 155, 0.08)" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="hour"
                  type="number"
                  domain={[1, 24]}
                  ticks={DAM_HOUR_X_TICKS}
                  allowDecimals={false}
                  padding={{ left: 0, right: 0 }}
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                  tickLine={false}
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
                <YAxis
                  yAxisId="sync-right-margin"
                  orientation="right"
                  domain={[0, 100]}
                  width={DAM_RIGHT_Y_AXIS_WIDTH}
                  tick={false}
                  tickLine={false}
                  axisLine={false}
                />
                {showGridFrequencyLine ? (
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
                    const s = tag ? `${fmt1.format(kw)} kW (${tag})` : `${fmt1.format(kw)} kW`;
                    const gridLabel = t('damSeriesGrid');
                    return [`${s}${fromLoad}${live}`, gridLabel];
                  }}
                  labelFormatter={hour => `${t('damHourTooltip')} ${hour}`}
                />
                <Bar dataKey="gridKw" name={t('damSeriesGrid')} maxBarSize={26} minPointSize={8}>
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

        {(!indexesPayload || indexesPayload.configured !== false) ? (
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
                  <option value={DAM_COMPARE_HOUR}>{t('damCompareOptionHour')}</option>
                  <option value={DAM_COMPARE_DAY}>{t('damCompareOptionDay')}</option>
                  <option value={DAM_COMPARE_MONTH}>{t('damCompareOptionMonth')}</option>
                </select>
                <div className="dam-trend-line" aria-live="polite">
                  {baseIndexCompareLoading || indexesLoading ? (
                    <span className="dam-trend-line--muted">…</span>
                  ) : baseIndexTrendPct == null ? (
                    <span className="dam-trend-line--muted">—</span>
                  ) : (
                    <>
                      <span
                        className={baseIndexTrendPct >= 0 ? 'dam-trend-line--up' : 'dam-trend-line--down'}
                      >
                        {fmtPct.format(baseIndexTrendPct)}%
                      </span>
                      <span className="dam-trend-line-caption"> {t(baseIndexTrendCaptionKey)}</span>
                    </>
                  )}
                </div>
              </div>
            </div>
            {indexesLoading ? (
              <p className="dam-loading dam-indexes-loading">{t('damIndexesLoading')}</p>
            ) : null}
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
      </div>
    </>
  );
}
