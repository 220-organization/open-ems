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

function ProgressBar({ percent, color }) {
  const pct = Number.isFinite(Number(percent)) ? Math.max(0, Math.min(100, Number(percent))) : 0;
  return (
    <div className="hw-totals__bar-track">
      <div className="hw-totals__bar-fill" style={{ width: `${pct.toFixed(1)}%`, background: color }} />
    </div>
  );
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

export default function DeyeTotalsPanel({
  tradeDay,
  inverterSn,
  gridlabDeviceId,
  evPortsAcdc,
  apiUrl,
  t,
  getBcp47Locale,
  onTradeDayChange,
}) {
  const [activeTab, setActiveTab] = useState('day');
  const [selectedDate, setSelectedDate] = useState(tradeDay);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);
  const glId = String(gridlabDeviceId || '').trim();
  const deyeSn = String(inverterSn || '').trim();
  const evAcdc =
    evPortsAcdc === 'dc' || evPortsAcdc === 'ac' || evPortsAcdc === 'bb' ? evPortsAcdc : '';
  const deviceKey = glId
    ? `gridlab:${glId}`
    : evAcdc
      ? `ev:${evAcdc}`
      : deyeSn
        ? `deye:${deyeSn}`
        : '';

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
      if (!deviceKey) return;
      if (abortRef.current) abortRef.current.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setLoading(true);
      setError(null);
      try {
        let path;
        let q;
        if (glId) {
          path = '/api/gridlab/soc-history-totals';
          q = new URLSearchParams({
            deviceId: glId,
            period: getApiPeriod(tab),
            date: dateIso,
          });
        } else if (evAcdc) {
          path = '/api/b2b/ev-ports-totals';
          q = new URLSearchParams({
            acdc: evAcdc,
            period: getApiPeriod(tab),
            date: dateIso,
          });
        } else {
          path = '/api/deye/soc-history-totals';
          q = new URLSearchParams({
            deviceSn: deyeSn,
            period: getApiPeriod(tab),
            date: dateIso,
          });
        }
        const r = await fetch(apiUrl(`${path}?${q}`), {
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
        const openEms = kwhTriple(json);
        const deyeCloud = json?.deyeCloud && typeof json.deyeCloud === 'object' ? kwhTriple(json.deyeCloud) : null;
        const deyeCloudError = json?.deyeCloudError === true;
        const hasAny =
          openEms.consumptionKwh != null ||
          openEms.generationKwh != null ||
          openEms.importKwh != null ||
          deyeCloud?.consumptionKwh != null ||
          deyeCloud?.generationKwh != null ||
          deyeCloud?.importKwh != null;
        if (!hasAny && !deyeCloudError) {
          setData(null);
          setError('noDataYet');
          return;
        }
        setData({ openEms, deyeCloud, deyeCloudError });
        setError(null);
      } catch (e) {
        if (e?.name === 'AbortError') return;
        setData(null);
        setError('error');
      } finally {
        setLoading(false);
      }
    },
    [apiUrl, deviceKey, deyeSn, glId, evAcdc]
  );

  useEffect(() => {
    fetchTotals(activeTab, selectedDate);
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, [fetchTotals, activeTab, selectedDate]);

  const bcp47 = getBcp47Locale();
  const fmt = kwhFmt(bcp47);

  const showOrigins = Boolean(deyeSn) && !glId && !evAcdc;
  const openEms = useMemo(() => originPercents(data?.openEms), [data]);
  const deyeCloud = useMemo(() => originPercents(data?.deyeCloud), [data]);
  const hasCoreRows = openEms.hasRows || (showOrigins && (deyeCloud.hasRows || data?.deyeCloudError));

  const titleKey = glId
    ? 'gridlabEnergyTotalsTitle'
    : evAcdc === 'bb'
      ? 'evPortsEnergyTotalsTitleBb'
      : evAcdc === 'ac'
        ? 'evPortsEnergyTotalsTitleAc'
        : evAcdc === 'dc'
          ? 'evPortsEnergyTotalsTitleDc'
          : 'deyeTotalsTitle';
  const titleFallback = glId
    ? 'GridLab Energy'
    : evAcdc === 'bb'
      ? 'BB Energy'
      : evAcdc === 'ac'
        ? 'AC EV Energy'
        : evAcdc === 'dc'
          ? 'DC EV Energy'
          : 'Deye Energy';
  const titleRaw = String(t(titleKey) || '').trim();
  const title = !titleRaw || titleRaw === titleKey ? titleFallback : titleRaw;

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

      <div className={`hw-totals__body${loading ? ' hw-totals__body--loading' : ''}${showOrigins ? ' hw-totals__body--origins' : ''}`}>
        {loading && !hasCoreRows ? <p className="hw-totals__status">{t('huaweiTotalsLoading')}</p> : null}
        {!loading && error === 'notConfigured' ? (
          <p className="hw-totals__status">{t('huaweiTotalsNotConfigured')}</p>
        ) : null}
        {!loading && error === 'error' ? (
          <p className="hw-totals__status hw-totals__status--error">{t('huaweiTotalsError')}</p>
        ) : null}
        {!loading && !hasCoreRows ? <p className="hw-totals__status">{t('huaweiTotalsNoData')}</p> : null}
        {hasCoreRows && !showOrigins ? (
          <TotalsMetrics
            stats={openEms}
            fmt={fmt}
            t={t}
            note={t('kwhCalibrationPrecisionNote')}
          />
        ) : null}
        {hasCoreRows && showOrigins ? (
          <div className="hw-totals__origins">
            <OriginBlock title={t('deyeTotalsOriginOpenEms')}>
              {openEms.hasRows ? (
                <TotalsMetrics stats={openEms} fmt={fmt} t={t} note={t('kwhCalibrationPrecisionNote')} />
              ) : (
                <p className="hw-totals__status">{t('huaweiTotalsNoData')}</p>
              )}
            </OriginBlock>
            <OriginBlock title={t('deyeTotalsOriginDeyeCloud')} defaultOpen>
              {deyeCloud.hasRows ? (
                <TotalsMetrics stats={deyeCloud} fmt={fmt} t={t} exact />
              ) : (
                <p className={`hw-totals__status${data?.deyeCloudError ? ' hw-totals__status--error' : ''}`}>
                  {data?.deyeCloudError ? t('huaweiTotalsError') : t('huaweiTotalsNoData')}
                </p>
              )}
            </OriginBlock>
          </div>
        ) : null}
      </div>
    </div>
  );
}
