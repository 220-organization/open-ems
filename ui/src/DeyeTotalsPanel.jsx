import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readCachedInverterPin, rememberInverterPin } from './deyeInverterPinCache';
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

function OriginBlock({ title, children, defaultOpen = false, action = null }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      className="hw-totals__origin"
      open={open}
      onToggle={event => setOpen(event.currentTarget.open)}
    >
      <summary className="hw-totals__origin-title">
        <span className="hw-totals__origin-title-text">{title}</span>
        {action ? (
          <span
            className="hw-totals__origin-action"
            onClick={e => {
              e.preventDefault();
              e.stopPropagation();
            }}
          >
            {action}
          </span>
        ) : null}
      </summary>
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
          {!exact ? (
            <>
              <span aria-hidden="true">*</span>{' '}
            </>
          ) : null}
          {note}
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
  const [backfillStatus, setBackfillStatus] = useState(null); // null | 'confirm' | 'pin' | 'paying' | 'running' | 'done' | 'error'
  const [backfillPin, setBackfillPin] = useState('');
  const [backfillAccessPassword, setBackfillAccessPassword] = useState('');
  const [backfillQuote, setBackfillQuote] = useState(null); // {daysCount, amountUah, uahPerDay}
  const [backfillPaymentId, setBackfillPaymentId] = useState('');
  const [backfillProgress, setBackfillProgress] = useState({ done: 0, total: 0 });
  const [backfillError, setBackfillError] = useState('');
  const abortRef = useRef(null);
  const backfillPollRef = useRef(null);
  const backfillPayPollRef = useRef(null);
  const backfillResumeRef = useRef(false);
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
        setData({
          openEms,
          deyeCloud,
          deyeCloudError,
          energyBackfilled: json?.energyBackfilled === true,
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
    [apiUrl, deviceKey, deyeSn, glId, evAcdc]
  );

  useEffect(() => {
    fetchTotals(activeTab, selectedDate);
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, [fetchTotals, activeTab, selectedDate]);

  useEffect(() => {
    return () => {
      if (backfillPollRef.current) {
        clearInterval(backfillPollRef.current);
        backfillPollRef.current = null;
      }
      if (backfillPayPollRef.current) {
        clearInterval(backfillPayPollRef.current);
        backfillPayPollRef.current = null;
      }
    };
  }, []);

  const stopBackfillPoll = useCallback(() => {
    if (backfillPollRef.current) {
      clearInterval(backfillPollRef.current);
      backfillPollRef.current = null;
    }
  }, []);

  const stopBackfillPayPoll = useCallback(() => {
    if (backfillPayPollRef.current) {
      clearInterval(backfillPayPollRef.current);
      backfillPayPollRef.current = null;
    }
  }, []);

  const loadBackfillQuote = useCallback(async () => {
    if (!deyeSn) return null;
    try {
      const q = new URLSearchParams({
        deviceSn: deyeSn,
        period: getApiPeriod(activeTab),
        date: selectedDate,
      });
      const r = await fetch(apiUrl(`/api/deye/energy-backfill/quote?${q}`), { cache: 'no-store' });
      const json = await r.json().catch(() => ({}));
      if (!r.ok) {
        setBackfillError(String(json?.detail || t('deyeBackfillError') || 'Backfill failed'));
        return null;
      }
      const quote = {
        daysCount: Number(json?.daysCount) || 0,
        amountUah: Number(json?.amountUah) || 0,
        uahPerDay: Number(json?.uahPerDay) || 22,
        // Prod always requires payment unless API explicitly allows free local backfill.
        paymentRequired: json?.paymentRequired !== false,
        localFreeEnabled: json?.localFreeEnabled === true || json?.paymentRequired === false,
      };
      setBackfillQuote(quote);
      return quote;
    } catch {
      setBackfillError(t('deyeBackfillError') || 'Backfill failed');
      return null;
    }
  }, [apiUrl, deyeSn, activeTab, selectedDate, t]);

  const openBackfillConfirm = useCallback(async () => {
    setBackfillError('');
    setBackfillAccessPassword('');
    setBackfillStatus('confirm');
    await loadBackfillQuote();
  }, [loadBackfillQuote]);

  const pollBackfillJob = useCallback(
    jobId => {
      stopBackfillPoll();
      const tick = async () => {
        try {
          const r = await fetch(apiUrl(`/api/deye/energy-backfill/job/${encodeURIComponent(jobId)}`), {
            cache: 'no-store',
          });
          const json = await r.json().catch(() => ({}));
          if (!r.ok) {
            setBackfillStatus('error');
            setBackfillError(String(json?.detail || t('deyeBackfillError') || 'Backfill failed'));
            stopBackfillPoll();
            return;
          }
          const done = Number(json?.daysDone) || 0;
          const total = Number(json?.daysTotal) || 0;
          setBackfillProgress({ done, total });
          const st = String(json?.status || '');
          if (st === 'done') {
            setBackfillStatus('done');
            setBackfillPaymentId('');
            stopBackfillPoll();
            fetchTotals(activeTab, selectedDate);
            try {
              window.dispatchEvent(
                new CustomEvent('deye-energy-backfill-done', {
                  detail: { deviceSn: deyeSn, date: selectedDate },
                })
              );
            } catch {
              /* ignore */
            }
            return;
          }
          if (st === 'error') {
            setBackfillStatus('error');
            setBackfillError(String(json?.error || t('deyeBackfillError') || 'Backfill failed'));
            stopBackfillPoll();
          }
        } catch {
          setBackfillStatus('error');
          setBackfillError(t('deyeBackfillError') || 'Backfill failed');
          stopBackfillPoll();
        }
      };
      tick();
      backfillPollRef.current = setInterval(tick, 2000);
    },
    [apiUrl, activeTab, selectedDate, deyeSn, fetchTotals, stopBackfillPoll, t]
  );

  const startBackfill = useCallback(
    async ({ pinOverride, paymentId, accessPassword } = {}) => {
      if (!deyeSn) return;
      const pin = String(pinOverride != null ? pinOverride : readCachedInverterPin(deyeSn) || '').trim();
      const payId = String(paymentId != null ? paymentId : backfillPaymentId || '').trim();
      const access = String(
        accessPassword != null ? accessPassword : backfillAccessPassword || ''
      ).trim();
      setBackfillError('');
      setBackfillStatus('running');
      setBackfillProgress({ done: 0, total: 0 });
      try {
        const body = {
          deviceSn: deyeSn,
          period: getApiPeriod(activeTab),
          date: selectedDate,
        };
        if (pin) body.pin = pin;
        if (access) body.accessPassword = access;
        else if (payId) body.paymentId = payId;
        const r = await fetch(apiUrl('/api/deye/energy-backfill'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          cache: 'no-store',
        });
        const json = await r.json().catch(() => ({}));
        if (r.status === 403) {
          setBackfillStatus('pin');
          setBackfillError(String(json?.detail || t('deyeWritePinLabel') || 'PIN required'));
          return;
        }
        if (r.status === 402) {
          setBackfillStatus('confirm');
          setBackfillError(String(json?.detail || t('deyeBackfillPaymentRequired') || 'Payment required'));
          await loadBackfillQuote();
          return;
        }
        if (!r.ok && r.status !== 202) {
          setBackfillStatus('error');
          setBackfillError(String(json?.detail || json?.error || t('deyeBackfillError') || 'Backfill failed'));
          return;
        }
        // Do not cache the special access password as the inverter write PIN.
        if (pin && !access) rememberInverterPin(deyeSn, pin);
        const jobId = String(json?.jobId || '').trim();
        if (!jobId) {
          setBackfillStatus('error');
          setBackfillError(t('deyeBackfillError') || 'Backfill failed');
          return;
        }
        setBackfillProgress({
          done: Number(json?.daysDone) || 0,
          total: Number(json?.daysTotal) || 0,
        });
        pollBackfillJob(jobId);
      } catch {
        setBackfillStatus('error');
        setBackfillError(t('deyeBackfillError') || 'Backfill failed');
      }
    },
    [
      apiUrl,
      deyeSn,
      activeTab,
      selectedDate,
      backfillPaymentId,
      backfillAccessPassword,
      pollBackfillJob,
      loadBackfillQuote,
      t,
    ]
  );

  const pollBackfillPayment = useCallback(
    paymentId => {
      stopBackfillPayPoll();
      setBackfillStatus('paying');
      setBackfillPaymentId(paymentId);
      const tick = async () => {
        try {
          const r = await fetch(
            apiUrl(`/api/deye/energy-backfill/pay/${encodeURIComponent(paymentId)}`),
            { cache: 'no-store' }
          );
          const json = await r.json().catch(() => ({}));
          if (!r.ok) {
            setBackfillStatus('error');
            setBackfillError(String(json?.detail || t('deyeBackfillError') || 'Backfill failed'));
            stopBackfillPayPoll();
            return;
          }
          const st = String(json?.status || '').toUpperCase();
          if (st === 'SUCCESS') {
            stopBackfillPayPoll();
            try {
              sessionStorage.removeItem('deyeBackfillPending');
            } catch {
              /* ignore */
            }
            startBackfill({ paymentId });
          }
        } catch {
          /* keep polling briefly */
        }
      };
      tick();
      backfillPayPollRef.current = setInterval(tick, 2000);
    },
    [apiUrl, startBackfill, stopBackfillPayPoll, t]
  );

  const startBackfillPayment = useCallback(async () => {
    if (!deyeSn) return;
    const pin = String(readCachedInverterPin(deyeSn) || '').trim();
    setBackfillError('');
    setBackfillStatus('paying');
    try {
      const redirectUrl = `${window.location.origin}${window.location.pathname}${window.location.search}`;
      const body = {
        deviceSn: deyeSn,
        period: getApiPeriod(activeTab),
        date: selectedDate,
        redirectUrl,
      };
      if (pin) body.pin = pin;
      const r = await fetch(apiUrl('/api/deye/energy-backfill/pay'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
      });
      const json = await r.json().catch(() => ({}));
      if (r.status === 403) {
        setBackfillStatus('pin');
        setBackfillError(String(json?.detail || t('deyeWritePinLabel') || 'PIN required'));
        return;
      }
      if (!r.ok) {
        setBackfillStatus('confirm');
        setBackfillError(String(json?.detail || t('deyeBackfillError') || 'Backfill failed'));
        return;
      }
      const paymentId = String(json?.paymentId || '').trim();
      const pageUrl = String(json?.pageUrl || '').trim();
      if (!paymentId || !pageUrl) {
        setBackfillStatus('confirm');
        setBackfillError(t('deyeBackfillError') || 'Backfill failed');
        return;
      }
      try {
        sessionStorage.setItem(
          'deyeBackfillPending',
          JSON.stringify({
            paymentId,
            deviceSn: deyeSn,
            period: getApiPeriod(activeTab),
            date: selectedDate,
          })
        );
      } catch {
        /* ignore */
      }
      window.location.assign(pageUrl);
    } catch {
      setBackfillStatus('confirm');
      setBackfillError(t('deyeBackfillError') || 'Backfill failed');
    }
  }, [apiUrl, deyeSn, activeTab, selectedDate, t]);

  const bcp47 = getBcp47Locale();
  const fmt = kwhFmt(bcp47);

  const showOrigins = Boolean(deyeSn) && !glId && !evAcdc;

  // Resume after Monobank redirect (?deyeBackfillPayment=…)
  useEffect(() => {
    if (!showOrigins || !deyeSn || backfillResumeRef.current) return;
    let paymentId = '';
    try {
      const params = new URLSearchParams(window.location.search);
      paymentId = String(params.get('deyeBackfillPayment') || '').trim();
      if (paymentId) {
        params.delete('deyeBackfillPayment');
        const next = `${window.location.pathname}?${params.toString()}`.replace(/\?$/, '');
        window.history.replaceState({}, '', next + window.location.hash);
      }
    } catch {
      paymentId = '';
    }
    if (!paymentId) {
      try {
        const raw = sessionStorage.getItem('deyeBackfillPending');
        if (raw) {
          const pending = JSON.parse(raw);
          if (pending && String(pending.deviceSn || '') === deyeSn) {
            paymentId = String(pending.paymentId || '').trim();
          }
        }
      } catch {
        /* ignore */
      }
    }
    if (!paymentId) return;
    backfillResumeRef.current = true;
    pollBackfillPayment(paymentId);
  }, [showOrigins, deyeSn, pollBackfillPayment]);
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
            exact={Boolean(data?.energyBackfilled)}
            note={
              data?.energyBackfilled ? t('damEnergyBackfillNote') : t('kwhCalibrationPrecisionNote')
            }
          />
        ) : null}
        {hasCoreRows && showOrigins ? (
          <div className="hw-totals__origins">
            <OriginBlock title={t('deyeTotalsOriginOpenEms')}>
              {openEms.hasRows ? (
                <TotalsMetrics
                  stats={openEms}
                  fmt={fmt}
                  t={t}
                  exact={Boolean(data?.energyBackfilled)}
                  note={
                    data?.energyBackfilled
                      ? t('damEnergyBackfillNote')
                      : t('kwhCalibrationPrecisionNote')
                  }
                />
              ) : (
                <p className="hw-totals__status">{t('huaweiTotalsNoData')}</p>
              )}
            </OriginBlock>
            <OriginBlock
              title={t('deyeTotalsOriginDeyeCloud')}
              defaultOpen
              action={
                <button
                  type="button"
                  className="hw-totals__backfill-btn"
                  disabled={backfillStatus === 'running' || backfillStatus === 'paying'}
                  onClick={e => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (backfillStatus === 'running' || backfillStatus === 'paying') return;
                    openBackfillConfirm();
                  }}
                >
                  {backfillStatus === 'running'
                    ? String(t('deyeBackfillProgress') || '{done}/{total} days')
                        .replace('{done}', String(backfillProgress.done))
                        .replace('{total}', String(backfillProgress.total))
                    : backfillStatus === 'paying'
                      ? t('deyeBackfillPaying') || 'Waiting for payment…'
                      : t('deyeBackfillButton') || 'Backfill'}
                </button>
              }
            >
              {backfillStatus === 'confirm' ? (
                <div className="hw-totals__backfill-panel">
                  <p className="hw-totals__status">{t('deyeBackfillConfirm')}</p>
                  {backfillQuote ? (
                    <p className="hw-totals__status">
                      {String(t('deyeBackfillPrice') || '{days} days × {uahPerDay} ₴ = {amount} ₴')
                        .replace('{days}', String(backfillQuote.daysCount))
                        .replace('{uahPerDay}', String(backfillQuote.uahPerDay))
                        .replace('{amount}', String(backfillQuote.amountUah))}
                    </p>
                  ) : null}
                  {backfillError ? (
                    <p className="hw-totals__status hw-totals__status--error">{backfillError}</p>
                  ) : null}
                  {backfillQuote && backfillQuote.paymentRequired === false ? (
                    <div className="hw-totals__backfill-actions">
                      <button
                        type="button"
                        className="hw-totals__backfill-btn hw-totals__backfill-btn--primary"
                        onClick={() => startBackfill()}
                      >
                        {t('deyeBackfillLocalBypass') || 'Local bypass (free)'}
                      </button>
                      <button
                        type="button"
                        className="hw-totals__backfill-btn"
                        onClick={() => {
                          setBackfillStatus(null);
                          setBackfillError('');
                        }}
                      >
                        {t('deyeBackfillCancel') || 'Cancel'}
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="hw-totals__backfill-actions">
                        <button
                          type="button"
                          className="hw-totals__backfill-btn hw-totals__backfill-btn--primary"
                          disabled={!backfillQuote || backfillQuote.amountUah < 1}
                          onClick={() => startBackfillPayment()}
                        >
                          {backfillQuote
                            ? `${t('deyeBackfillPay') || 'Pay'} ${backfillQuote.amountUah} ₴`
                            : t('deyeBackfillPay') || 'Pay'}
                        </button>
                        <button
                          type="button"
                          className="hw-totals__backfill-btn"
                          onClick={() => {
                            setBackfillStatus(null);
                            setBackfillError('');
                          }}
                        >
                          {t('deyeBackfillCancel') || 'Cancel'}
                        </button>
                      </div>
                      <div className="hw-totals__backfill-actions">
                        <input
                          type="password"
                          autoComplete="off"
                          className="hw-totals__backfill-pin"
                          value={backfillAccessPassword}
                          onChange={e => setBackfillAccessPassword(e.target.value)}
                          aria-label={t('deyeBackfillAccessPassword') || 'Access password'}
                          placeholder={t('deyeBackfillAccessPassword') || 'Access password'}
                        />
                        <button
                          type="button"
                          className="hw-totals__backfill-btn"
                          onClick={() => startBackfill({ accessPassword: backfillAccessPassword })}
                        >
                          {t('deyeBackfillUnlock') || 'Unlock'}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ) : null}
              {backfillStatus === 'pin' ? (
                <div className="hw-totals__backfill-panel">
                  <p className="hw-totals__status">{backfillError || t('deyeWritePinLabel')}</p>
                  <div className="hw-totals__backfill-actions">
                    <input
                      type="password"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      className="hw-totals__backfill-pin"
                      value={backfillPin}
                      onChange={e => setBackfillPin(e.target.value)}
                      aria-label={t('deyeWritePinLabel')}
                      placeholder={t('deyeWritePinLabel') || 'PIN'}
                    />
                    <button
                      type="button"
                      className="hw-totals__backfill-btn hw-totals__backfill-btn--primary"
                      onClick={() => {
                        const typed = String(backfillPin || '').trim();
                        startBackfill({
                          pinOverride: typed,
                          paymentId: backfillPaymentId,
                          // Allow AA9220YD typed into the PIN box to unlock without inverter PIN.
                          accessPassword: backfillAccessPassword || typed,
                        });
                      }}
                    >
                      {t('deyeBackfillButton') || 'Backfill'}
                    </button>
                    <button
                      type="button"
                      className="hw-totals__backfill-btn"
                      onClick={() => {
                        setBackfillStatus(null);
                        setBackfillPin('');
                      }}
                    >
                      {t('deyeBackfillCancel') || 'Cancel'}
                    </button>
                  </div>
                </div>
              ) : null}
              {backfillStatus === 'paying' ? (
                <p className="hw-totals__status">{t('deyeBackfillPaying') || 'Waiting for payment…'}</p>
              ) : null}
              {backfillStatus === 'running' ? (
                <p className="hw-totals__status">
                  {String(t('deyeBackfillProgress') || '{done}/{total} days')
                    .replace('{done}', String(backfillProgress.done))
                    .replace('{total}', String(backfillProgress.total))}
                </p>
              ) : null}
              {backfillStatus === 'done' ? (
                <p className="hw-totals__status">{t('deyeBackfillDone')}</p>
              ) : null}
              {backfillStatus === 'error' ? (
                <p className="hw-totals__status hw-totals__status--error">
                  {backfillError || t('deyeBackfillError')}
                </p>
              ) : null}
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
