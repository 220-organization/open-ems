import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import KwhDisplay from './KwhDisplay';

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

const TABS = ['day', 'month', 'year'];

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

function todayLocalIso() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function clampToToday(isoDate, period) {
  const raw = String(isoDate || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  const today = todayLocalIso();
  if (period === 'day') return raw > today ? today : raw;
  if (period === 'month') return raw.slice(0, 7) > today.slice(0, 7) ? today : raw;
  return raw.slice(0, 4) > today.slice(0, 4) ? today : raw;
}

function isAtOrAfterToday(isoDate, period) {
  const raw = String(isoDate || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return false;
  const today = todayLocalIso();
  if (period === 'day') return raw >= today;
  if (period === 'month') return raw.slice(0, 7) >= today.slice(0, 7);
  return raw.slice(0, 4) >= today.slice(0, 4);
}

function getApiPeriod(tab) {
  if (tab === 'month' || tab === 'year') return tab;
  return 'day';
}

function ProgressBar({ percent, color }) {
  const pct = Number.isFinite(Number(percent)) ? Math.max(0, Math.min(100, Number(percent))) : 0;
  return (
    <div className="hw-totals__bar-track">
      <div className="hw-totals__bar-fill" style={{ width: `${pct.toFixed(1)}%`, background: color }} />
    </div>
  );
}

function MetricRow({ label, value, unit, color, percent, fmt, isBase = false }) {
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
          <KwhDisplay value={value} fmt={fmt} unit={unit} />
          {percentText ? ` ${percentText}` : ''}
        </span>
      </div>
      {value != null && percent != null && Number.isFinite(Number(percent)) ? (
        <ProgressBar percent={percent} color={color} />
      ) : null}
    </div>
  );
}

export default function DeyeTotalsPanel({ tradeDay, inverterSn, apiUrl, t, getBcp47Locale, onTradeDayChange }) {
  const [activeTab, setActiveTab] = useState('day');
  const [selectedDate, setSelectedDate] = useState(tradeDay);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  useEffect(() => {
    setSelectedDate(tradeDay);
  }, [tradeDay]);

  const emitDateChange = useCallback(
    (nextIso, period) => {
      const clamped = clampToToday(nextIso, period);
      setSelectedDate(clamped);
      if (typeof onTradeDayChange === 'function') onTradeDayChange(clamped);
    },
    [onTradeDayChange]
  );

  const fetchTotals = useCallback(
    async (tab, dateIso) => {
      if (!inverterSn) return;
      if (abortRef.current) abortRef.current.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setLoading(true);
      setError(null);
      try {
        const q = new URLSearchParams({
          deviceSn: inverterSn,
          period: getApiPeriod(tab),
          date: dateIso,
        });
        const r = await fetch(apiUrl(`/api/deye/soc-history-totals?${q}`), {
          cache: 'no-store',
          signal: ctrl.signal,
        });
        const json = await r.json().catch(() => ({}));
        if (ctrl.signal.aborted) return;
        if (!r.ok || !json?.configured) {
          if (json?.configured === false) setError('notConfigured');
          else setError('error');
          setData(null);
          return;
        }
        const hasAny = json?.consumptionKwh != null || json?.generationKwh != null || json?.importKwh != null;
        if (!hasAny) {
          setData(null);
          setError('noDataYet');
          return;
        }
        setData({
          consumptionKwh: json?.consumptionKwh != null ? Number(json.consumptionKwh) : null,
          generationKwh: json?.generationKwh != null ? Number(json.generationKwh) : null,
          importKwh: json?.importKwh != null ? Number(json.importKwh) : null,
        });
        setError(null);
      } catch (e) {
        if (e?.name === 'AbortError') return;
        setData(null);
        setError('error');
      } finally {
        setLoading(false);
      }
    },
    [apiUrl, inverterSn]
  );

  useEffect(() => {
    fetchTotals(activeTab, selectedDate);
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, [fetchTotals, activeTab, selectedDate]);

  const bcp47 = getBcp47Locale();
  const fmt = kwhFmt(bcp47);

  const consKwh =
    data?.consumptionKwh != null && Number.isFinite(Number(data.consumptionKwh)) ? Number(data.consumptionKwh) : null;
  const pvKwh =
    data?.generationKwh != null && Number.isFinite(Number(data.generationKwh)) ? Number(data.generationKwh) : null;
  const gridKwhRaw = data?.importKwh ?? null;
  const gridKwh = gridKwhRaw != null && Number.isFinite(Number(gridKwhRaw)) ? Number(gridKwhRaw) : null;

  const consumptionBase = consKwh != null && consKwh > 0 ? consKwh : null;
  const consumptionPct = consumptionBase != null ? 100 : null;
  const pvPctRaw = consumptionBase != null && pvKwh != null ? (pvKwh / consumptionBase) * 100 : null;
  const gridPctRaw = consumptionBase != null && gridKwh != null ? (gridKwh / consumptionBase) * 100 : null;
  const pvPct = pvPctRaw != null ? Math.min(99.9, Math.max(0, pvPctRaw)) : null;
  const gridPct = gridPctRaw != null ? Math.min(99.9, Math.max(0, gridPctRaw)) : null;

  const hasCoreRows = useMemo(
    () => consumptionBase != null || pvKwh != null || gridKwh != null,
    [consumptionBase, pvKwh, gridKwh]
  );

  const titleRaw = String(t('deyeTotalsTitle') || '').trim();
  const title = !titleRaw || titleRaw === 'deyeTotalsTitle' ? 'Deye Energy' : titleRaw;

  const dateInputType = activeTab === 'day' ? 'date' : activeTab === 'month' ? 'month' : 'number';
  const dateInputValue =
    activeTab === 'day'
      ? selectedDate
      : activeTab === 'month'
        ? monthValueFromIso(selectedDate)
        : yearValueFromIso(selectedDate);
  const today = todayLocalIso();
  const dateInputMax = activeTab === 'day' ? today : activeTab === 'month' ? today.slice(0, 7) : today.slice(0, 4);
  const dateInputMin = activeTab === 'year' ? '2000' : undefined;
  const nextDisabled = isAtOrAfterToday(selectedDate, activeTab);

  function handleDateInputChange(nextRaw) {
    const raw = String(nextRaw || '').trim();
    if (!raw) return;
    if (activeTab === 'day') {
      if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) emitDateChange(raw, 'day');
      return;
    }
    if (activeTab === 'month') {
      if (/^\d{4}-\d{2}$/.test(raw)) emitDateChange(`${raw}-01`, 'month');
      return;
    }
    if (/^\d{4}$/.test(raw)) emitDateChange(`${raw}-01-01`, 'year');
  }

  function tabLabel(tab) {
    const key = tab === 'day' ? 'huaweiTotalsTabDay' : tab === 'month' ? 'huaweiTotalsTabMonth' : 'huaweiTotalsTabYear';
    const raw = String(t(key) || '').trim();
    if (!raw || raw === key) return TAB_LABEL_FALLBACK[tab];
    return raw;
  }

  return (
    <div className="hw-totals">
      <div className="hw-totals__header">
        <span className="hw-totals__title">{title}</span>
        <div className="hw-totals__controls">
          <div className="hw-totals__date-wrap">
            <button
              type="button"
              className="hw-totals__date-nav"
              aria-label={t('damPrevDay')}
              title={t('damPrevDay')}
              onClick={() => emitDateChange(shiftByPeriod(selectedDate, activeTab, -1), activeTab)}
            >
              <span aria-hidden="true">‹</span>
            </button>
            <input
              type={dateInputType}
              className="hw-totals__date-input"
              value={dateInputValue}
              aria-label={t('damDateLabel')}
              title={t('damOpenDatePickerAria')}
              onChange={e => handleDateInputChange(e.target.value)}
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
              onClick={() => emitDateChange(shiftByPeriod(selectedDate, activeTab, 1), activeTab)}
            >
              <span aria-hidden="true">›</span>
            </button>
          </div>
          <div className="hw-totals__tabs" role="tablist">
            {TABS.map(tab => (
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

      <div className={`hw-totals__body${loading ? ' hw-totals__body--loading' : ''}`}>
        {loading && !hasCoreRows ? <p className="hw-totals__status">{t('huaweiTotalsLoading')}</p> : null}
        {!loading && error === 'notConfigured' ? (
          <p className="hw-totals__status">{t('huaweiTotalsNotConfigured')}</p>
        ) : null}
        {!loading && error === 'error' ? (
          <p className="hw-totals__status hw-totals__status--error">{t('huaweiTotalsError')}</p>
        ) : null}
        {!loading && !hasCoreRows ? <p className="hw-totals__status">{t('huaweiTotalsNoData')}</p> : null}
        {hasCoreRows ? (
          <div className="hw-totals__metrics">
            {consKwh != null ? (
              <MetricRow
                label={t('huaweiTotalsCons')}
                value={consKwh}
                unit="kWh"
                color={BAR_COLORS.cons}
                percent={consumptionPct}
                fmt={fmt}
                isBase
              />
            ) : null}
            {pvKwh != null ? (
              <MetricRow
                label={t('huaweiTotalsPvGen')}
                value={pvKwh}
                unit="kWh"
                color={BAR_COLORS.pv}
                percent={pvPct}
                fmt={fmt}
              />
            ) : null}
            {gridKwh != null ? (
              <MetricRow
                label={t('huaweiTotalsGridImport')}
                value={gridKwh}
                unit="kWh"
                color={BAR_COLORS.import}
                percent={gridPct}
                fmt={fmt}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
