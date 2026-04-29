import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Displays Day / Month / Year energy totals from Huawei FusionSolar.
 *
 * Reads from the Postgres-backed cache `huawei_station_energy_totals` via
 * `GET /api/huawei/station-energy`. The endpoint refreshes the cache lazily on
 * miss / stale row, and a background scheduler keeps rows fresh — UI never
 * hits FusionSolar directly.
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

function MetricRow({ label, value, unit, color, percent, fmt, isBase = false }) {
  const display = value != null ? `${fmt.format(value)} ${unit}` : '—';
  let percentText = '';
  if (percent != null && Number.isFinite(Number(percent))) {
    const raw = Number(percent);
    if (!isBase && raw >= 100) percentText = '(< 100%)';
    else percentText = `(${fmt.format(Math.max(0, raw))}%)`;
  }
  return (
    <div className="hw-totals__row">
      <div className="hw-totals__row-header">
        <span className="hw-totals__swatch" style={{ background: color }} aria-hidden="true" />
        <span className="hw-totals__label">{label}</span>
        <span className="hw-totals__value">
          {display}
          {percentText ? ` ${percentText}` : ''}
        </span>
      </div>
      {value != null && percent != null && Number.isFinite(Number(percent)) && (
        <ProgressBar percent={percent} color={color} />
      )}
    </div>
  );
}

const TAB_LABEL_FALLBACK = {
  day: 'Day',
  month: 'Month',
  year: 'Year',
};

function shiftIsoDate(isoDate, deltaDays) {
  const raw = String(isoDate || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  const d = new Date(`${raw}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return raw;
  d.setUTCDate(d.getUTCDate() + deltaDays);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

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
  const [loading, setLoading] = useState(false);
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
    setSelectedDate(tradeDay);
  }, [tradeDay]);

  const bcp47 = getBcp47Locale();
  const fmt = kwhFmt(bcp47);

  const item = data?.items?.[0] ?? null;
  const pvKwh = item?.pvKwh ?? null;
  const consKwh = item?.consumptionKwh ?? null;
  const importKwh = item?.gridImportKwh ?? null;
  const exportKwh = item?.gridExportKwh ?? null;

  // UX baseline: Consumption is always the 100% top line.
  const consumptionBase = consKwh != null && Number(consKwh) > 0 ? Number(consKwh) : null;
  const gridKwh = importKwh != null ? importKwh : exportKwh;
  const hasCoreRows = consumptionBase != null || pvKwh != null || gridKwh != null;
  const consumptionPct = consumptionBase != null ? 100 : null;
  const pvPctRaw = consumptionBase != null && pvKwh != null ? (Number(pvKwh) / consumptionBase) * 100 : null;
  const gridPctRaw = consumptionBase != null && gridKwh != null ? (Number(gridKwh) / consumptionBase) * 100 : null;
  const pvPct = pvPctRaw != null ? Math.min(99.9, Math.max(0, pvPctRaw)) : null;
  const gridPct = gridPctRaw != null ? Math.min(99.9, Math.max(0, gridPctRaw)) : null;

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

      <div className="hw-totals__body">
        {loading && <p className="hw-totals__status">{t('huaweiTotalsLoading')}</p>}

        {!loading && error === 'rateLimited' && (
          <p className="hw-totals__status hw-totals__status--warn">{t('huaweiTotalsRateLimited')}</p>
        )}
        {!loading && error === 'notConfigured' && (
          <p className="hw-totals__status">{t('huaweiTotalsNotConfigured')}</p>
        )}
        {!loading && error === 'error' && (
          <p className="hw-totals__status hw-totals__status--error">{t('huaweiTotalsError')}</p>
        )}
        {!loading && error === 'noDataYet' && (
          <p className="hw-totals__status">{t('huaweiTotalsNoData')}</p>
        )}
        {!loading && !error && item && pvKwh == null && consKwh == null && (
          <p className="hw-totals__status">{t('huaweiTotalsNoData')}</p>
        )}

        {!loading && !error && item && hasCoreRows && (
          <div className="hw-totals__metrics">
            {consKwh != null && (
              <MetricRow
                label={t('huaweiTotalsCons')}
                value={consKwh}
                unit="kWh"
                color={BAR_COLORS.cons}
                percent={consumptionPct}
                fmt={fmt}
                isBase
              />
            )}
            {pvKwh != null && (
              <MetricRow
                label={t('huaweiTotalsPvGen')}
                value={pvKwh}
                unit="kWh"
                color={BAR_COLORS.pv}
                percent={pvPct}
                fmt={fmt}
              />
            )}
            {gridKwh != null && (
              <MetricRow
                label={t('huaweiTotalsGridImport')}
                value={gridKwh}
                unit="kWh"
                color={BAR_COLORS.import}
                percent={gridPct}
                fmt={fmt}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
