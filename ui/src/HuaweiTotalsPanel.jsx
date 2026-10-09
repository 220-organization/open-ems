import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import KwhDisplay from './KwhDisplay';

/**
 * Displays Day / Month / Year energy totals from Huawei FusionSolar.
 *
 * Two origins from `GET /api/huawei/station-energy`:
 * Open EMS integrates `huawei_power_sample`; Huawei Cloud is FusionSolar KPI
 * (cached, refreshed from the API when stale). Cloud starts expanded.
 *
 * Props:
 *   stationCode  {string}  — FusionSolar plant code
 *   tradeDay     {string}  — YYYY-MM-DD calendar date (selects which period to show)
 *   apiUrl       {Function} — (path) => full URL helper (same as in DamChartPanel)
 *   t            {Function} — i18n translation helper
 *   getBcp47Locale {Function}
 */

const TABS = ['day', 'month', 'year'];

const BAR_COLORS = {
  pv: '#4ade80',
  cons: '#fb923c',
  import: '#60a5fa',
};

function kwhFmt(bcp47) {
  try {
    return new Intl.NumberFormat(bcp47, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  } catch {
    return new Intl.NumberFormat('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
}

function ProgressBar({ percent, color }) {
  const pct = Number.isFinite(Number(percent)) ? Math.max(0, Math.min(100, Number(percent))) : 0;
  return (
    <div className="hw-totals__bar-track">
      <div
        className="hw-totals__bar-fill"
        style={{ width: `${pct.toFixed(1)}%`, background: color }}
      />
    </div>
  );
}

function finiteKwh(value) {
  return value != null && Number.isFinite(Number(value)) ? Number(value) : null;
}

function kwhTriple(source) {
  return {
    consumptionKwh: finiteKwh(source?.consumptionKwh),
    generationKwh: finiteKwh(source?.generationKwh),
    importKwh: finiteKwh(source?.importKwh),
  };
}

function originPercents(triple) {
  const consKwh = triple?.consumptionKwh ?? null;
  const pvKwh = triple?.generationKwh ?? null;
  const gridKwh = triple?.importKwh ?? null;
  const consumptionBase = consKwh != null && consKwh > 0 ? consKwh : null;
  const pvPctRaw = consumptionBase != null && pvKwh != null ? (pvKwh / consumptionBase) * 100 : null;
  const gridPctRaw = consumptionBase != null && gridKwh != null ? (gridKwh / consumptionBase) * 100 : null;
  return {
    consKwh,
    pvKwh,
    gridKwh,
    consumptionPct: consumptionBase != null ? 100 : null,
    pvPct: pvPctRaw != null ? Math.max(0, pvPctRaw) : null,
    gridPct: gridPctRaw != null ? Math.max(0, gridPctRaw) : null,
    hasRows: consKwh != null || pvKwh != null || gridKwh != null,
  };
}

function OriginBlock({ title, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      className="hw-totals__origin"
      open={open}
      onToggle={event => setOpen(event.currentTarget.open)}
    >
      <summary className="hw-totals__origin-title">{title}</summary>
      <div className="hw-totals__origin-body">{children}</div>
    </details>
  );
}

function MetricRow({ label, value, unit, color, percent, fmt, exact = false }) {
  let percentText = '';
  if (percent != null && Number.isFinite(Number(percent))) {
    percentText = `(${fmt.format(Math.max(0, Number(percent)))}%)`;
  }
  return (
    <div className="hw-totals__row">
      <div className="hw-totals__row-header">
        <span className="hw-totals__swatch" style={{ background: color }} aria-hidden="true" />
        <span className="hw-totals__label">{label}</span>
        <span className="hw-totals__value">
          <KwhDisplay value={value} fmt={fmt} unit={unit} exact={exact} />
          {percentText ? ` ${percentText}` : ''}
        </span>
      </div>
      {value != null && percent != null && Number.isFinite(Number(percent)) ? (
        <ProgressBar percent={percent} color={color} />
      ) : null}
    </div>
  );
}

function TotalsMetrics({ stats, fmt, t, note, exact = false }) {
  return (
    <div className="hw-totals__metrics">
      {stats.consKwh != null ? (
        <MetricRow
          label={t('huaweiTotalsCons')}
          value={stats.consKwh}
          unit="kWh"
          color={BAR_COLORS.cons}
          percent={stats.consumptionPct}
          fmt={fmt}
          exact={exact}
        />
      ) : null}
      {stats.pvKwh != null ? (
        <MetricRow
          label={t('huaweiTotalsPvGen')}
          value={stats.pvKwh}
          unit="kWh"
          color={BAR_COLORS.pv}
          percent={stats.pvPct}
          fmt={fmt}
          exact={exact}
        />
      ) : null}
      {stats.gridKwh != null ? (
        <MetricRow
          label={t('huaweiTotalsGridImport')}
          value={stats.gridKwh}
          unit="kWh"
          color={BAR_COLORS.import}
          percent={stats.gridPct}
          fmt={fmt}
          exact={exact}
        />
      ) : null}
      {note ? (
        <p className="hw-totals__approx-note">
          <span aria-hidden="true">*</span> {note}
        </p>
      ) : null}
    </div>
  );
}

const TAB_LABEL_FALLBACK = {
  day: 'Day',
  month: 'Month',
  year: 'Year',
};

function shiftByPeriod(isoDate, period, delta) {
  const raw = String(isoDate || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  const d = new Date(`${raw}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return raw;
  if (period === 'month') d.setUTCMonth(d.getUTCMonth() + delta);
  else if (period === 'year') d.setUTCFullYear(d.getUTCFullYear() + delta);
  else d.setUTCDate(d.getUTCDate() + delta);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function monthValueFromIso(isoDate) {
  const raw = String(isoDate || '').trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw.slice(0, 7) : '';
}

function yearValueFromIso(isoDate) {
  const raw = String(isoDate || '').trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw.slice(0, 4) : '';
}

/** Today in local time as YYYY-MM-DD — used as the upper bound for date selection. */
function todayLocalIso() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/**
 * Clamp an ISO date to today's bound for a given period.
 * - day: must be ≤ today
 * - month: must be in a month ≤ current month
 * - year: must be in a year ≤ current year
 */
function clampToToday(isoDate, period) {
  const raw = String(isoDate || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  const today = todayLocalIso();
  if (period === 'day') {
    return raw > today ? today : raw;
  }
  if (period === 'month') {
    return raw.slice(0, 7) > today.slice(0, 7) ? today : raw;
  }
  // year
  return raw.slice(0, 4) > today.slice(0, 4) ? today : raw;
}

/** True if `isoDate` is already at or beyond today for the given period (next-step disabled). */
function isAtOrAfterToday(isoDate, period) {
  const raw = String(isoDate || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return false;
  const today = todayLocalIso();
  if (period === 'day') return raw >= today;
  if (period === 'month') return raw.slice(0, 7) >= today.slice(0, 7);
  return raw.slice(0, 4) >= today.slice(0, 4);
}

export default function HuaweiTotalsPanel({ stationCode, tradeDay, apiUrl, t, getBcp47Locale }) {
  const [activeTab, setActiveTab] = useState('day');
  const [selectedDate, setSelectedDate] = useState(tradeDay);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  const fetchTotals = useCallback(
    async (tab, dateIso) => {
      if (!stationCode) return;
      if (abortRef.current) abortRef.current.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      setLoading(true);
      setError(null);
      try {
        const q = new URLSearchParams({ stationCodes: stationCode, period: tab, date: dateIso });
        const r = await fetch(apiUrl(`/api/huawei/station-energy?${q}`), {
          cache: 'no-store',
          signal: ctrl.signal,
        });
        const json = await r.json();
        if (ctrl.signal.aborted) return;
        if (!json.ok) {
          if (json.northboundRateLimited) setError('rateLimited');
          else if (!json.configured) setError('notConfigured');
          else if (json.reason === 'no_data_yet') setError('noDataYet');
          else setError('error');
          setData(null);
        } else {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (e.name === 'AbortError') return;
        setError('error');
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [stationCode, apiUrl],
  );

  useEffect(() => {
    fetchTotals(activeTab, selectedDate);
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, [fetchTotals, activeTab, selectedDate]);

  useEffect(() => {
    if (data?.huaweiCloudRateLimited !== true) return undefined;
    const sec = Number(data.retryAfterSec);
    const waitMs = (Number.isFinite(sec) && sec > 0 ? Math.min(sec, 90) : 60) * 1000;
    const id = setTimeout(() => {
      fetchTotals(activeTab, selectedDate);
    }, waitMs);
    return () => clearTimeout(id);
  }, [data, activeTab, selectedDate, fetchTotals]);

  useEffect(() => {
    setSelectedDate(tradeDay);
  }, [tradeDay]);

  const bcp47 = getBcp47Locale();
  const fmt = kwhFmt(bcp47);

  const openEms = useMemo(() => originPercents(kwhTriple(data?.openEms)), [data]);
  const huaweiCloud = useMemo(() => originPercents(kwhTriple(data?.huaweiCloud)), [data]);
  const cloudRateLimited = data?.huaweiCloudRateLimited === true;
  const hasCoreRows =
    openEms.hasRows || huaweiCloud.hasRows || data?.huaweiCloudError === true || cloudRateLimited;

  function tabLabel(tab) {
    const key = tab === 'day' ? 'huaweiTotalsTabDay' : tab === 'month' ? 'huaweiTotalsTabMonth' : 'huaweiTotalsTabYear';
    const raw = String(t(key) || '').trim();
    if (!raw || raw === key) return TAB_LABEL_FALLBACK[tab];
    return raw;
  }

  const dateInputType = activeTab === 'day' ? 'date' : activeTab === 'month' ? 'month' : 'number';
  const dateInputValue = activeTab === 'day'
    ? selectedDate
    : activeTab === 'month'
      ? monthValueFromIso(selectedDate)
      : yearValueFromIso(selectedDate);

  // Upper bounds prevent picking a date in the future via the native picker.
  const today = todayLocalIso();
  const dateInputMax = activeTab === 'day'
    ? today
    : activeTab === 'month'
      ? today.slice(0, 7)
      : today.slice(0, 4);
  const dateInputMin = activeTab === 'year' ? '2000' : undefined;
  const nextDisabled = isAtOrAfterToday(selectedDate, activeTab);

  function handleDateInputChange(nextRaw) {
    const raw = String(nextRaw || '').trim();
    if (!raw) return;
    if (activeTab === 'day') {
      if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
        setSelectedDate(clampToToday(raw, 'day'));
      }
      return;
    }
    if (activeTab === 'month') {
      if (/^\d{4}-\d{2}$/.test(raw)) {
        setSelectedDate(clampToToday(`${raw}-01`, 'month'));
      }
      return;
    }
    if (/^\d{4}$/.test(raw)) {
      setSelectedDate(clampToToday(`${raw}-01-01`, 'year'));
    }
  }

  return (
    <div className="hw-totals">
      <div className="hw-totals__header">
        <span className="hw-totals__title">{t('huaweiTotalsTitle')}</span>
        <div className="hw-totals__controls">
          <div className="hw-totals__date-wrap">
            <button
              type="button"
              className="hw-totals__date-nav"
              aria-label={t('damPrevDay')}
              title={t('damPrevDay')}
              onClick={() => setSelectedDate(prev => shiftByPeriod(prev, activeTab, -1))}
            >
              <span aria-hidden="true">‹</span>
            </button>
            <input
              type={dateInputType}
              className="hw-totals__date-input"
              value={dateInputValue}
              aria-label={t('damDateLabel')}
              title={t('damOpenDatePickerAria')}
              onChange={(e) => handleDateInputChange(e.target.value)}
              min={dateInputMin}
              max={dateInputMax}
            />
            <button
              type="button"
              className="hw-totals__date-nav"
              aria-label={t('damNextDay')}
              title={t('damNextDay')}
              disabled={nextDisabled}
              aria-disabled={nextDisabled}
              onClick={() =>
                setSelectedDate(prev => clampToToday(shiftByPeriod(prev, activeTab, 1), activeTab))
              }
            >
              <span aria-hidden="true">›</span>
            </button>
          </div>
          <div className="hw-totals__tabs" role="tablist">
            {TABS.map((tab) => (
              <button
                type="button"
                key={tab}
                role="tab"
                aria-selected={activeTab === tab}
                className={`hw-totals__tab${activeTab === tab ? ' hw-totals__tab--active' : ''}`}
                onClick={() => setActiveTab(tab)}
              >
                {tabLabel(tab)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className={`hw-totals__body hw-totals__body--origins${loading ? ' hw-totals__body--loading' : ''}`}>
        {loading && !hasCoreRows ? <p className="hw-totals__status">{t('huaweiTotalsLoading')}</p> : null}
        {!loading && error === 'rateLimited' ? (
          <p className="hw-totals__status hw-totals__status--warn">{t('huaweiTotalsRateLimited')}</p>
        ) : null}
        {!loading && error === 'notConfigured' ? (
          <p className="hw-totals__status">{t('huaweiTotalsNotConfigured')}</p>
        ) : null}
        {!loading && error === 'error' ? (
          <p className="hw-totals__status hw-totals__status--error">{t('huaweiTotalsError')}</p>
        ) : null}
        {!loading && !hasCoreRows && (error == null || error === 'noDataYet') ? (
          <p className="hw-totals__status">{t('huaweiTotalsNoData')}</p>
        ) : null}
        {hasCoreRows ? (
          <div className="hw-totals__origins">
            <OriginBlock title={t('huaweiTotalsOriginOpenEms')}>
              {openEms.hasRows ? (
                <TotalsMetrics stats={openEms} fmt={fmt} t={t} note={t('kwhCalibrationPrecisionNote')} />
              ) : (
                <p className="hw-totals__status">{t('huaweiTotalsNoData')}</p>
              )}
            </OriginBlock>
            <OriginBlock title={t('huaweiTotalsOriginHuaweiCloud')} defaultOpen>
              {huaweiCloud.hasRows ? (
                <TotalsMetrics stats={huaweiCloud} fmt={fmt} t={t} exact />
              ) : cloudRateLimited ? (
                <p className="hw-totals__status hw-totals__status--warn">{t('huaweiTotalsRateLimited')}</p>
              ) : (
                <p className={`hw-totals__status${data?.huaweiCloudError ? ' hw-totals__status--error' : ''}`}>
                  {data?.huaweiCloudError ? t('huaweiTotalsError') : t('huaweiTotalsNoData')}
                </p>
              )}
            </OriginBlock>
          </div>
        ) : null}
      </div>
    </div>
  );
}
