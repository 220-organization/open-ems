import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import './power-flow.css';
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

function initialTradeDay() {
  try {
    const q = new URLSearchParams(window.location.search).get('date');
    if (q && /^\d{4}-\d{2}-\d{2}$/.test(q)) return q;
  } catch {
    /* ignore */
  }
  return addCalendarDays(kyivCalendarIso(), -1);
}

export default function DamChartPage({
  t,
  getBcp47Locale,
  locale,
  SUPPORTED,
  LOCALE_NAMES,
  onLangSelectChange,
}) {
  const [tradeDay, setTradeDay] = useState(initialTradeDay);
  const [payload, setPayload] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);

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
    document.title = t('damPageTitle');
    document.documentElement.lang = locale === 'uk' ? 'uk' : locale;
  }, [t, locale]);

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
    if (!payload || !Array.isArray(payload.hourlyKwh220)) return [];
    const kwh = payload.hourlyKwh220;
    const dam = payload.hourlyPriceDamUahPerKwh || [];
    return Array.from({ length: 24 }, (_, i) => ({
      hour: i + 1,
      kwh220: kwh[i] != null && Number.isFinite(Number(kwh[i])) ? Number(kwh[i]) : null,
      damUahKwh: dam[i] != null && Number.isFinite(Number(dam[i])) ? Number(dam[i]) : null,
    }));
  }, [payload]);

  const onDateInput = (e) => {
    const v = e.target.value;
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) setTradeDay(v);
  };

  const goPrev = () => setTradeDay((d) => addCalendarDays(d, -1));
  const goNext = () => setTradeDay((d) => addCalendarDays(d, 1));

  return (
    <div className="pf-body dam-page">
      <div className="pf-root dam-root">
        <header className="pf-header dam-header">
          <div className="dam-header-left">
            <a className="pf-nav-link" href="/power-flow">
              {t('damNavToPowerFlow')}
            </a>
          </div>
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

        <div className="dam-chart-card">
          <h1 className="dam-title">{t('damChartHeading')}</h1>
          <p className="dam-subtitle">{t('damChartSubtitle')}</p>

          {loadError ? (
            <p className="dam-error" role="alert">
              {t('damError')}: {loadError}
            </p>
          ) : null}

          {loading && !rows.length ? (
            <p className="dam-loading">{t('damLoading')}</p>
          ) : null}

          {!loading && rows.length ? (
            <div className="dam-recharts-wrap">
              <ResponsiveContainer width="100%" height={420}>
                <ComposedChart data={rows} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
                  <CartesianGrid stroke="rgba(252, 1, 155, 0.12)" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="hour"
                    tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                    tickLine={false}
                    label={{ value: t('damHourAxis'), position: 'insideBottom', offset: -4, fill: 'rgba(255,248,252,0.55)', fontSize: 11 }}
                  />
                  <YAxis
                    yAxisId="left"
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
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fill: 'rgba(255,248,252,0.75)', fontSize: 11 }}
                    tickLine={false}
                    axisLine={{ stroke: 'rgba(252, 1, 155, 0.25)' }}
                    label={{
                      value: t('damVolumeAxis'),
                      angle: 90,
                      position: 'insideRight',
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
                      if (name === t('damSeriesDam')) return [`${fmt1.format(value)}`, name];
                      return [`${fmt1.format(value)}`, name];
                    }}
                    labelFormatter={(h) => `${t('damHourTooltip')} ${h}`}
                  />
                  <Legend
                    wrapperStyle={{ paddingTop: 16 }}
                    formatter={(value) => <span style={{ color: 'rgba(255,248,252,0.88)' }}>{value}</span>}
                  />
                  <Bar
                    yAxisId="right"
                    dataKey="kwh220"
                    name={t('damSeries220')}
                    fill="#a855f7"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={28}
                  />
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="damUahKwh"
                    name={t('damSeriesDam')}
                    stroke="#22c55e"
                    strokeWidth={2.2}
                    dot={{ r: 2.5, fill: '#22c55e' }}
                    connectNulls
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
