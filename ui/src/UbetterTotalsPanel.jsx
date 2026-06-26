import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Day / Month / Year energy totals from Ubetter EMS Open API (`GET /api/ubetter/energy`).
 */

const TABS = ['day', 'month', 'year'];

const BAR_COLORS = {
  charge: '#60a5fa',
  discharge: '#4ade80',
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

function sumEnergyItems(items) {
  let charge = 0;
  let discharge = 0;
  let hasCharge = false;
  let hasDischarge = false;
  for (const it of items || []) {
    const c = it?.totalChargeKwh;
    const d = it?.totalDischargeKwh;
    if (c != null && Number.isFinite(Number(c))) {
      charge += Number(c);
      hasCharge = true;
    }
    if (d != null && Number.isFinite(Number(d))) {
      discharge += Number(d);
      hasDischarge = true;
    }
  }
  return {
    chargeKwh: hasCharge ? charge : null,
    dischargeKwh: hasDischarge ? discharge : null,
  };
}

export default function UbetterTotalsPanel({ deviceSn, tradeDay, apiUrl, t, getBcp47Locale }) {
  const [activeTab, setActiveTab] = useState('day');
  const [selectedDate, setSelectedDate] = useState(tradeDay);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  const fetchTotals = useCallback(
    async (tab, dateIso) => {
      if (!deviceSn) return;
      if (abortRef.current) abortRef.current.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      setLoading(true);
      setError(null);
      try {
        const q = new URLSearchParams({ sn: deviceSn });
        const year = dateIso.slice(0, 4);
        const month = dateIso.slice(5, 7);
        if (tab === 'year') q.set('year', year);
        else {
          q.set('year', year);
          q.set('month', month);
        }
        const r = await fetch(apiUrl(`/api/ubetter/energy?${q}`), {
          cache: 'no-store',
          signal: ctrl.signal,
        });
        const json = await r.json();
        if (ctrl.signal.aborted) return;
        if (!json.ok) {
          if (!json.configured) setError('notConfigured');
          else if (json.reason === 'ubetter_login_failed') setError('authFailed');
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
    [deviceSn, apiUrl],
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
  const totals = sumEnergyItems(data?.items);
  const chargeKwh = totals.chargeKwh;
  const dischargeKwh = totals.dischargeKwh;
  const base = Math.max(chargeKwh || 0, dischargeKwh || 0) || null;
  const chargePct = base != null && chargeKwh != null ? (chargeKwh / base) * 100 : null;
  const dischargePct = base != null && dischargeKwh != null ? (dischargeKwh / base) * 100 : null;
  const hasRows = chargeKwh != null || dischargeKwh != null;

  function tabLabel(tab) {
    const key =
      tab === 'day' ? 'ubetterTotalsTabDay' : tab === 'month' ? 'ubetterTotalsTabMonth' : 'ubetterTotalsTabYear';
    const raw = String(t(key) || '').trim();
    if (!raw || raw === key) return TAB_LABEL_FALLBACK[tab];
    return raw;
  }

  const dateInputType = activeTab === 'day' ? 'date' : activeTab === 'month' ? 'month' : 'number';
  const dateInputValue =
    activeTab === 'day'
      ? selectedDate
      : activeTab === 'month'
        ? monthValueFromIso(selectedDate)
        : yearValueFromIso(selectedDate);

  const today = todayLocalIso();
  const dateInputMax =
    activeTab === 'day' ? today : activeTab === 'month' ? today.slice(0, 7) : today.slice(0, 4);
  const dateInputMin = activeTab === 'year' ? '2000' : undefined;
  const nextDisabled = isAtOrAfterToday(selectedDate, activeTab);

  function handleDateInputChange(nextRaw) {
    const raw = String(nextRaw || '').trim();
    if (!raw) return;
    if (activeTab === 'day') {
      if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) setSelectedDate(clampToToday(raw, 'day'));
      return;
    }
    if (activeTab === 'month') {
      if (/^\d{4}-\d{2}$/.test(raw)) setSelectedDate(clampToToday(`${raw}-01`, 'month'));
      return;
    }
    if (/^\d{4}$/.test(raw)) setSelectedDate(clampToToday(`${raw}-01-01`, 'year'));
  }

  return (
    <div className="hw-totals">
      <div className="hw-totals__header">
        <span className="hw-totals__title">{t('ubetterTotalsTitle')}</span>
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
              onClick={() =>
                setSelectedDate(prev => clampToToday(shiftByPeriod(prev, activeTab, 1), activeTab))
              }
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

      <div className="hw-totals__body">
        {loading && <p className="hw-totals__status">{t('ubetterTotalsLoading')}</p>}
        {!loading && error === 'authFailed' && (
          <p className="hw-totals__status hw-totals__status--warn">{t('ubetterAuthFailedHint')}</p>
        )}
        {!loading && error === 'notConfigured' && (
          <p className="hw-totals__status">{t('ubetterTotalsNotConfigured')}</p>
        )}
        {!loading && error === 'error' && (
          <p className="hw-totals__status hw-totals__status--error">{t('ubetterTotalsError')}</p>
        )}
        {!loading && !error && !hasRows && (
          <p className="hw-totals__status">{t('ubetterTotalsNoData')}</p>
        )}
        {!loading && !error && hasRows && (
          <div className="hw-totals__metrics">
            {chargeKwh != null && (
              <MetricRow
                label={t('ubetterTotalsCharge')}
                value={chargeKwh}
                unit="kWh"
                color={BAR_COLORS.charge}
                percent={chargePct}
                fmt={fmt}
                isBase={dischargeKwh == null}
              />
            )}
            {dischargeKwh != null && (
              <MetricRow
                label={t('ubetterTotalsDischarge')}
                value={dischargeKwh}
                unit="kWh"
                color={BAR_COLORS.discharge}
                percent={dischargePct}
                fmt={fmt}
                isBase={chargeKwh == null}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
