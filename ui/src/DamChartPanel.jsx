import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
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

/**
 * @param {'embedded' | 'fullpage'} variant — fullpage: URL ?date= sync + top nav; embedded: bottom of Power flow only.
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
}) {
  const [tradeDay, setTradeDay] = useState(() =>
    variant === 'fullpage' ? initialTradeDayFullPage() : kyivCalendarIso(),
  );
  const [payload, setPayload] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);

  const h = chartHeight ?? (variant === 'embedded' ? 300 : 420);

  const bcp47 = getBcp47Locale();
  const fmt1 = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 1,
      }),
    [bcp47],
  );

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

  const rows = useMemo(() => {
    if (!payload || !Array.isArray(payload.hourlyPriceDamUahPerKwh)) return [];
    const dam = payload.hourlyPriceDamUahPerKwh;
    return Array.from({ length: 24 }, (_, i) => ({
      hour: i + 1,
      damUahKwh: dam[i] != null && Number.isFinite(Number(dam[i])) ? Number(dam[i]) : null,
    }));
  }, [payload]);

  const onDateInput = (e) => {
    const v = e.target.value;
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) setTradeDay(v);
  };

  const goPrev = () => setTradeDay((d) => addCalendarDays(d, -1));
  const goNext = () => setTradeDay((d) => addCalendarDays(d, 1));

  const hasChart = Boolean(payload) && rows.length === 24;

  const dateBar = (
    <div className="dam-date-bar" role="group" aria-label={t('damDateLabel')}>
      <button type="button" className="dam-date-btn" onClick={goPrev} aria-label={t('damPrevDay')}>
        ‹
      </button>
      <input
        className="dam-date-input"
        type="date"
        value={tradeDay}
        onChange={onDateInput}
        aria-label={t('damDateLabel')}
      />
      <button type="button" className="dam-date-btn" onClick={goNext} aria-label={t('damNextDay')}>
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

        {!loading && hasChart ? (
          <div className="dam-recharts-wrap" style={{ minHeight: h }}>
            <ResponsiveContainer width="100%" height={h}>
              <LineChart data={rows} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
                <CartesianGrid stroke="rgba(252, 1, 155, 0.12)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="hour"
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                  tickLine={false}
                  label={{
                    value: t('damHourAxis'),
                    position: 'insideBottom',
                    offset: -4,
                    fill: 'rgba(255,248,252,0.55)',
                    fontSize: 11,
                  }}
                />
                <YAxis
                  tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                  tickLine={false}
                  axisLine={{ stroke: 'rgba(252, 1, 155, 0.25)' }}
                  label={{
                    value: t('damTariffAxis'),
                    angle: -90,
                    position: 'insideLeft',
                    style: { fill: 'rgba(255,248,252,0.55)', fontSize: 11 },
                  }}
                />
                <Tooltip
                  contentStyle={{
                    background: 'rgba(24, 8, 32, 0.94)',
                    border: '1px solid rgba(252, 1, 155, 0.35)',
                    borderRadius: 10,
                    color: '#fff',
                  }}
                  formatter={(value, name) => {
                    if (value == null || value === '') return ['—', name];
                    return [`${fmt1.format(value)}`, name];
                  }}
                  labelFormatter={(hour) => `${t('damHourTooltip')} ${hour}`}
                />
                <Legend
                  wrapperStyle={{ paddingTop: 16 }}
                  formatter={(value) => <span style={{ color: 'rgba(255,248,252,0.88)' }}>{value}</span>}
                />
                <Line
                  type="monotone"
                  dataKey="damUahKwh"
                  name={t('damSeriesDam')}
                  stroke="#22c55e"
                  strokeWidth={2.2}
                  dot={{ r: 2.5, fill: '#22c55e' }}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : null}
      </div>
    </>
  );
}
