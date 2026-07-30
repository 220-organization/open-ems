import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Live GridLab BESS status + physical meters (skips virtual rows).
 * Data from GET /api/gridlab/power-flow and GET /api/gridlab/meters.
 */

function kwhFmt(bcp47) {
  try {
    return new Intl.NumberFormat(bcp47, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  } catch {
    return new Intl.NumberFormat('en-GB', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  }
}

function kwFmt(bcp47) {
  try {
    return new Intl.NumberFormat(bcp47, { minimumFractionDigits: 1, maximumFractionDigits: 2 });
  } catch {
    return new Intl.NumberFormat('en-GB', { minimumFractionDigits: 1, maximumFractionDigits: 2 });
  }
}

function formatKw(w, fmt) {
  if (w == null || !Number.isFinite(Number(w))) return '—';
  return `${fmt.format(Number(w) / 1000)} kW`;
}

function formatAge(sec, t) {
  if (sec == null || !Number.isFinite(Number(sec))) return '';
  const s = Number(sec);
  if (s < 60) return t('gridlabAgeSeconds', { n: Math.round(s) });
  return t('gridlabAgeMinutes', { n: Math.round(s / 60) });
}

export default function GridLabTotalsPanel({ deviceId, apiUrl, t, getBcp47Locale }) {
  const [live, setLive] = useState(null);
  const [meters, setMeters] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);
  const hasLiveRef = useRef(false);
  const bcp47 = typeof getBcp47Locale === 'function' ? getBcp47Locale() : 'en-GB';
  const fmtKw = kwFmt(bcp47);
  const fmtKwh = kwhFmt(bcp47);

  useEffect(() => {
    hasLiveRef.current = false;
    setLive(null);
    setMeters([]);
    setError(null);
  }, [deviceId]);

  const fetchAll = useCallback(async () => {
    if (!deviceId) return;
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    // Silent background refresh after the first payload (avoid panel/page flash).
    if (!hasLiveRef.current) setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ deviceId: String(deviceId) });
      const [pfRes, mRes] = await Promise.all([
        fetch(apiUrl(`/api/gridlab/power-flow?${q}`), { cache: 'no-store', signal: ctrl.signal }),
        fetch(apiUrl('/api/gridlab/meters'), { cache: 'no-store', signal: ctrl.signal }),
      ]);
      const pf = await pfRes.json().catch(() => ({}));
      const md = await mRes.json().catch(() => ({}));
      if (ctrl.signal.aborted) return;
      if (!pf.ok) {
        if (!pf.configured) setError('notConfigured');
        else if (pf.reason === 'gridlab_login_failed') setError('authFailed');
        else setError('error');
        setLive(null);
        setMeters([]);
        hasLiveRef.current = false;
      } else {
        setLive(pf);
        setError(null);
        const list = Array.isArray(md.meters) ? md.meters.filter(m => !m.isVirtual) : [];
        setMeters(list);
        hasLiveRef.current = true;
      }
    } catch (e) {
      if (e.name === 'AbortError') return;
      setError('error');
      setLive(null);
      setMeters([]);
      hasLiveRef.current = false;
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, [deviceId, apiUrl]);

  useEffect(() => {
    void fetchAll();
    const id = setInterval(() => void fetchAll(), 30_000);
    return () => {
      clearInterval(id);
      if (abortRef.current) abortRef.current.abort();
    };
  }, [fetchAll]);

  if (!deviceId) return null;

  const gridW = live?.gridPowerW;
  const gridImport = gridW != null && gridW > 0 ? gridW : null;
  const gridExport = gridW != null && gridW < 0 ? Math.abs(gridW) : null;

  return (
    <div className="hw-totals gl-totals" aria-label={t('gridlabTotalsTitle')}>
      <div className="hw-totals__header">
        <h3 className="hw-totals__title">{t('gridlabTotalsTitle')}</h3>
        {live?.stale ? (
          <span className="gl-totals__stale" title={formatAge(live.dataAgeSeconds, t)}>
            {t('gridlabStale')}
          </span>
        ) : live?.dataAgeSeconds != null ? (
          <span className="gl-totals__age">{formatAge(live.dataAgeSeconds, t)}</span>
        ) : null}
      </div>

      {loading && !live ? (
        <p className="hw-totals__hint">{t('gridlabTotalsLoading')}</p>
      ) : error === 'notConfigured' ? (
        <p className="hw-totals__hint">{t('gridlabTotalsNotConfigured')}</p>
      ) : error === 'authFailed' ? (
        <p className="hw-totals__hint">{t('gridlabAuthFailedHint')}</p>
      ) : error ? (
        <p className="hw-totals__hint">{t('gridlabTotalsError')}</p>
      ) : (
        <>
          <div className="hw-totals__rows">
            <div className="hw-totals__row">
              <div className="hw-totals__row-header">
                <span className="hw-totals__swatch" style={{ background: '#4ade80' }} aria-hidden="true" />
                <span className="hw-totals__label">{t('gridlabMetricSoc')}</span>
                <span className="hw-totals__value">
                  {live?.socPercent != null ? `${fmtKwh.format(live.socPercent)}%` : '—'}
                </span>
              </div>
            </div>
            <div className="hw-totals__row">
              <div className="hw-totals__row-header">
                <span className="hw-totals__swatch" style={{ background: '#fbbf24' }} aria-hidden="true" />
                <span className="hw-totals__label">{t('gridlabMetricBattery')}</span>
                <span className="hw-totals__value">{formatKw(live?.batteryPowerW, fmtKw)}</span>
              </div>
            </div>
            <div className="hw-totals__row">
              <div className="hw-totals__row-header">
                <span className="hw-totals__swatch" style={{ background: '#60a5fa' }} aria-hidden="true" />
                <span className="hw-totals__label">{t('gridlabMetricGridImport')}</span>
                <span className="hw-totals__value">{formatKw(gridImport, fmtKw)}</span>
              </div>
            </div>
            <div className="hw-totals__row">
              <div className="hw-totals__row-header">
                <span className="hw-totals__swatch" style={{ background: '#38bdf8' }} aria-hidden="true" />
                <span className="hw-totals__label">{t('gridlabMetricGridExport')}</span>
                <span className="hw-totals__value">{formatKw(gridExport, fmtKw)}</span>
              </div>
            </div>
            <div className="hw-totals__row">
              <div className="hw-totals__row-header">
                <span className="hw-totals__swatch" style={{ background: '#facc15' }} aria-hidden="true" />
                <span className="hw-totals__label">{t('gridlabMetricPv')}</span>
                <span className="hw-totals__value">{formatKw(live?.pvPowerW, fmtKw)}</span>
              </div>
            </div>
            <div className="hw-totals__row">
              <div className="hw-totals__row-header">
                <span className="hw-totals__swatch" style={{ background: '#f472b6' }} aria-hidden="true" />
                <span className="hw-totals__label">{t('gridlabMetricLoad')}</span>
                <span className="hw-totals__value">{formatKw(live?.loadPowerW, fmtKw)}</span>
              </div>
            </div>
            {live?.evPowerW != null ? (
              <div className="hw-totals__row">
                <div className="hw-totals__row-header">
                  <span className="hw-totals__swatch" style={{ background: '#a78bfa' }} aria-hidden="true" />
                  <span className="hw-totals__label">{t('gridlabMetricEv')}</span>
                  <span className="hw-totals__value">{formatKw(live.evPowerW, fmtKw)}</span>
                </div>
              </div>
            ) : null}
          </div>

          {meters.length > 0 ? (
            <div className="gl-totals__meters">
              <h4 className="gl-totals__meters-title">{t('gridlabMetersTitle')}</h4>
              <table className="gl-totals__table">
                <thead>
                  <tr>
                    <th>{t('gridlabMeterName')}</th>
                    <th>{t('gridlabMeterRole')}</th>
                    <th>{t('gridlabMeterPower')}</th>
                    <th>{t('gridlabMeterAge')}</th>
                  </tr>
                </thead>
                <tbody>
                  {meters.map(m => (
                    <tr key={m.id} className={m.stale ? 'gl-totals__row--stale' : undefined}>
                      <td>
                        {m.name || `#${m.id}`}
                        {m.selectedAs ? (
                          <span className="gl-totals__selected"> · {m.selectedAs}</span>
                        ) : null}
                      </td>
                      <td>{m.role || '—'}</td>
                      <td>
                        {m.powerKw != null && Number.isFinite(Number(m.powerKw))
                          ? `${fmtKw.format(Number(m.powerKw))} kW`
                          : '—'}
                      </td>
                      <td>
                        {m.stale ? t('gridlabStale') : formatAge(m.dataAgeSeconds, t) || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
