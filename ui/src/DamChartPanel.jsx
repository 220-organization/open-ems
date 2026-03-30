import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
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

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  if (!base) return path;
  return `${base}${path}`;
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
    const hp = parts.find((p) => p.type === 'hour');
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
    clampTradeDayIso(variant === 'fullpage' ? initialTradeDayFullPage() : kyivCalendarIso()),
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
    [bcp47],
  );

  const fmtGridKwTick = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }),
    [bcp47],
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
      return undefined;
    }
    let cancelled = false;
    const loadLive = async () => {
      try {
        const r = await fetch(
          apiUrl(`/api/deye/ess-power?deviceSn=${encodeURIComponent(effectiveInverterSn)}`),
          { cache: 'no-store' },
        );
        const d = await r.json();
        if (cancelled || !d?.ok || d?.configured === false) {
          if (!cancelled) {
            setLiveGridPowerW(null);
            setLiveLoadPowerW(null);
          }
          return;
        }
        const g = d.gridPowerW;
        const l = d.loadPowerW;
        if (!cancelled) {
          setLiveGridPowerW(g != null && Number.isFinite(Number(g)) ? Number(g) : null);
          setLiveLoadPowerW(l != null && Number.isFinite(Number(l)) ? Number(l) : null);
        }
      } catch {
        if (!cancelled) {
          setLiveGridPowerW(null);
          setLiveLoadPowerW(null);
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
      socPayload?.ok &&
      socPayload?.configured &&
      Array.isArray(socPayload.hourlySocPercent)
        ? socPayload.hourlySocPercent
        : null;
    const gridArr =
      socPayload?.ok &&
      socPayload?.configured &&
      Array.isArray(socPayload.hourlyGridPowerW)
        ? socPayload.hourlyGridPowerW
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
      return {
        hour: i + 1,
        damUahKwh: dam[i] != null && Number.isFinite(Number(dam[i])) ? Number(dam[i]) : null,
        socPercent,
        gridKw,
        gridKwLive: false,
        gridKwFromLoad: false,
      };
    });

    const liveGridKw =
      liveGridPowerW != null && Number.isFinite(Number(liveGridPowerW))
        ? Number(liveGridPowerW) / 1000
        : null;
    const liveLoadKw =
      liveLoadPowerW != null && Number.isFinite(Number(liveLoadPowerW))
        ? Number(liveLoadPowerW) / 1000
        : null;
    const hi = kyivHourIndexNowForDate(tradeDay);
    if (hi != null) {
      const hasAnyGrid = out.some((r) => r.gridKw != null && Number.isFinite(r.gridKw));
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
    return out;
  }, [payload, socPayload, tradeDay, liveGridPowerW, liveLoadPowerW]);

  const gridDomain = useMemo(() => {
    const vals = rows.map((r) => r.gridKw).filter((v) => v != null && Number.isFinite(v));
    if (!vals.length) return [-0.25, 0.25];
    const raw = Math.max(...vals.map((v) => Math.abs(v)), 0.25);
    const cap = niceSymmetricCap(raw);
    return [-cap, cap];
  }, [rows]);

  const gridYTicks = useMemo(() => fiveSymmetricTicks(gridDomain[0], gridDomain[1]), [gridDomain]);

  const onDateInput = (e) => {
    const v = e.target.value;
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) setTradeDay(clampTradeDayIso(v));
  };

  const goPrev = () => setTradeDay((d) => addCalendarDays(d, -1));
  const goNext = () =>
    setTradeDay((d) => {
      const next = addCalendarDays(d, 1);
      const cap = maxTradeDayKyivIso();
      return next > cap ? cap : next;
    });

  const hasChart = Boolean(payload) && rows.length === 24;
  const hasAnyDamPrice = useMemo(
    () => rows.some((r) => r.damUahKwh != null && Number.isFinite(Number(r.damUahKwh))),
    [rows],
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
            {SUPPORTED.map((code) => (
              <option key={code} value={code}>
                {LOCALE_NAMES[code] || code}
              </option>
            ))}
          </select>
        </header>
      ) : (
        <div className="dam-embedded-head">
          <h2 className="dam-title dam-title-embedded">{t('damChartHeading')}</h2>
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
        {variant === 'fullpage' ? <h1 className="dam-title">{t('damChartHeading')}</h1> : null}

        {loadError ? (
          <p className="dam-error" role="alert">
            {t('damError')}: {loadError}
          </p>
        ) : null}

        {loading && !hasChart ? (
          <p className="dam-loading">{t('damLoading')}</p>
        ) : null}

        {effectiveInverterSn && socLoading && !loading && hasChart ? (
          <p className="dam-loading dam-soc-loading">{t('damSocLoading')}</p>
        ) : null}

        {!loading && hasChart ? (
          <div className="dam-recharts-wrap" style={{ minHeight: h }}>
            <ResponsiveContainer width="100%" height={h}>
              <LineChart
                data={rows}
                syncId="dam-day"
                margin={{
                  top: 8,
                  right: effectiveInverterSn ? 52 : 16,
                  left: 8,
                  bottom: 6,
                }}
              >
                <CartesianGrid stroke="rgba(252, 1, 155, 0.12)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="hour"
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="dam"
                  width={DAM_LEFT_Y_AXIS_WIDTH}
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                  tickLine={false}
                  tickFormatter={(v) => fmt1.format(v)}
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
                    tickFormatter={(v) => fmt1.format(v)}
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
                    const socLabel = t('damSeriesSoc');
                    if (name === socLabel) return [`${fmt1.format(value)} %`, socLabel];
                    return [`${fmt1.format(value)}`, name];
                  }}
                  labelFormatter={(hour) => `${t('damHourTooltip')} ${hour}`}
                />
                <Legend
                  wrapperStyle={{ paddingTop: 16 }}
                  formatter={(value) => <span style={{ color: 'rgba(255,248,252,0.88)' }}>{value}</span>}
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
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : null}

        {!loading && hasChart && effectiveInverterSn ? (
          <div className="dam-grid-bars-wrap">
            <p className="dam-grid-bars-caption">{t('damGridBarsCaption')}</p>
            <ResponsiveContainer width="100%" height={gridBarH}>
              <ComposedChart
                data={rows}
                syncId="dam-day"
                margin={{ top: 6, right: 52, left: 8, bottom: 28 }}
              >
                <CartesianGrid
                  stroke="rgba(252, 1, 155, 0.08)"
                  strokeDasharray="3 3"
                  vertical={false}
                />
                <XAxis
                  dataKey="hour"
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
                  tickFormatter={(v) => fmtGridKwTick.format(v)}
                  label={{
                    value: t('damGridPowerAxis'),
                    angle: -90,
                    position: 'insideLeft',
                    offset: 10,
                    style: { fill: 'rgba(255,248,252,0.55)', fontSize: 10, textAnchor: 'end' },
                  }}
                />
                {/* Reserves the same width as the SoC axis on the line chart so X domains align. */}
                <YAxis
                  yAxisId="sync-right-margin"
                  orientation="right"
                  domain={[0, 100]}
                  width={DAM_RIGHT_Y_AXIS_WIDTH}
                  tick={false}
                  tickLine={false}
                  axisLine={false}
                />
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
                    const tag =
                      kw > 0 ? t('damGridImportTag') : kw < 0 ? t('damGridExportTag') : '';
                    const gridPayload = item?.payload ?? item;
                    const live = gridPayload?.gridKwLive ? ` — ${t('damGridLiveTag')}` : '';
                    const fromLoad = gridPayload?.gridKwFromLoad ? ` (${t('damGridFromLoadTag')})` : '';
                    const s = tag ? `${fmt1.format(kw)} kW (${tag})` : `${fmt1.format(kw)} kW`;
                    const gridLabel = t('damSeriesGrid');
                    return [`${s}${fromLoad}${live}`, gridLabel];
                  }}
                  labelFormatter={(hour) => `${t('damHourTooltip')} ${hour}`}
                />
                <Bar
                  dataKey="gridKw"
                  name={t('damSeriesGrid')}
                  maxBarSize={26}
                  minPointSize={8}
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
                  shape={(dotProps) => {
                    const { cx, cy, payload } = dotProps;
                    const v = payload?.gridKw;
                    if (v == null || !Number.isFinite(v) || cx == null || cy == null) return null;
                    const fill = v >= 0 ? '#f59e0b' : '#38bdf8';
                    return (
                      <circle
                        cx={cx}
                        cy={cy}
                        r={5.5}
                        fill={fill}
                        stroke="rgba(255,255,255,0.45)"
                        strokeWidth={1.2}
                      />
                    );
                  }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        ) : null}
      </div>
    </>
  );
}
