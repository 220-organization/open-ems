import { useEffect, useId, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

function retailFromBar(b) {
  const retail =
    typeof b.retailUahPerKwh === 'number' ? b.retailUahPerKwh : Number(b.retailUahPerKwh);
  return Number.isFinite(retail) ? retail : null;
}

/** Month-over-month absolute UAH/kWh change vs previous bar (null when not comparable). */
function monthOverMonthDeltaUah(current, previous) {
  if (current == null || previous == null) return null;
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return null;
  if (current <= 1e-9 && previous <= 1e-9) return null;
  if (previous <= 1e-6) return null;
  return current - previous;
}

function formatMomDeltaUah(delta, bcp47) {
  const n = Number(delta);
  if (!Number.isFinite(n) || Math.abs(n) < 0.005) return null;
  try {
    return new Intl.NumberFormat(bcp47, {
      signDisplay: 'exceptZero',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    const sign = n > 0 ? '+' : '';
    return `${sign}${n.toFixed(2)}`;
  }
}

function momDeltaFill(delta) {
  const n = Number(delta);
  if (!Number.isFinite(n) || Math.abs(n) < 0.005) return '#a0a0a0';
  return n > 0 ? '#f87171' : '#4ade80';
}

function buildChartRows(bars, bcp47) {
  return bars.map((b, i) => {
    const retail = retailFromBar(b);
    const prevRetail = i > 0 ? retailFromBar(bars[i - 1]) : null;
    const momAbs = monthOverMonthDeltaUah(retail, prevRetail);
    const momTop = momAbs != null ? formatMomDeltaUah(momAbs, bcp47) : null;
    const rateTop = retail != null ? retail.toFixed(2) : '—';
    let momPct = null;
    if (momAbs != null && prevRetail != null && prevRetail > 1e-6) {
      momPct = (momAbs / prevRetail) * 100;
    }
    const importKwh =
      typeof b.gridImportKwh === 'number' ? b.gridImportKwh : Number(b.gridImportKwh);
    return {
      barKey: `${b.monthLabel}-${i}`,
      xLabel: formatMonthXLabel(b.monthLabel, bcp47),
      retailUahPerKwh: retail != null ? retail : 0,
      rateTop,
      momAbs,
      momPct,
      momTop,
      momFill: momAbs != null ? momDeltaFill(momAbs) : '#a0a0a0',
      partialMonth: Boolean(b.partialMonth),
      importWeighted: Boolean(b.importWeighted),
      gridImportKwh: Number.isFinite(importKwh) ? importKwh : null,
      monthLabel: b.monthLabel,
      prevMonthLabel: i > 0 ? bars[i - 1].monthLabel : null,
    };
  });
}

function MonthlyBarTopLabel({ x, y, width, index, rows }) {
  const row = rows?.[index];
  if (row == null || x == null || y == null || width == null) return null;
  const cx = Number(x) + Number(width) / 2;
  const rateY = Number(y) - 6;
  const momY = rateY - 11;
  return (
    <g className="pf-monthly-rates-bar-label">
      {row.momTop ? (
        <text x={cx} y={momY} textAnchor="middle" fill={row.momFill} fontSize={9} fontWeight={600}>
          {row.momTop}
        </text>
      ) : null}
      <text x={cx} y={rateY} textAnchor="middle" fill="#fafafa" fontSize={10}>
        {row.rateTop}
      </text>
    </g>
  );
}

function formatMonthXLabel(monthLabel, bcp47) {
  const raw = String(monthLabel || '').trim();
  const m = /^(\d{4})-(\d{2})$/.exec(raw);
  if (!m) return raw;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  if (!Number.isFinite(y) || mo < 1 || mo > 12) return raw;
  try {
    const short = new Intl.DateTimeFormat(bcp47, { month: 'short', timeZone: 'UTC' }).format(
      new Date(Date.UTC(y, mo - 1, 15, 12, 0, 0))
    );
    return short.length ? short.charAt(0).toUpperCase() + short.slice(1) : raw;
  } catch {
    return raw;
  }
}

export default function MonthlyRetailTariffChartModal({ open, onClose, fetchUrl, t, bcp47 = 'en-GB' }) {
  const [status, setStatus] = useState('idle');
  const [rows, setRows] = useState([]);
  const [chartScope, setChartScope] = useState('fleet_dam_avg');

  useEffect(() => {
    if (!open) {
      setStatus('idle');
      setRows([]);
      setChartScope('fleet_dam_avg');
      return undefined;
    }
    let cancelled = false;
    (async () => {
      setStatus('loading');
      setRows([]);
      try {
        const r = await fetch(fetchUrl, { cache: 'no-store' });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (!r.ok || !data.ok) {
          setStatus('error');
          return;
        }
        const bars = Array.isArray(data.bars) ? data.bars : [];
        setChartScope(data.scope === 'import_weighted_dam' ? 'import_weighted_dam' : 'fleet_dam_avg');
        setRows(buildChartRows(bars, bcp47));
        setStatus('ready');
      } catch {
        if (!cancelled) setStatus('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, fetchUrl, bcp47]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const barGradId = useId().replace(/:/g, '_');
  const chartWidth = useMemo(() => Math.max(480, rows.length * 52), [rows.length]);

  if (!open || typeof document === 'undefined') return null;

  const title =
    chartScope === 'import_weighted_dam'
      ? t('powerFlowMonthlyRatesChartTitleDevice')
      : t('powerFlowMonthlyRatesChartTitle');

  const node = (
    <div className="pf-messenger-scrim pf-messenger-scrim--220km" role="presentation" onClick={onClose}>
      <div
        className="pf-messenger-dialog pf-peak-hourly-chart-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pf-monthly-rates-chart-title"
        onClick={e => e.stopPropagation()}
      >
        <div className="pf-peak-hourly-chart-panel">
          <div className="pf-peak-hourly-chart-head">
            <h2 id="pf-monthly-rates-chart-title" className="pf-peak-hourly-chart-title">
              {title}
            </h2>
            <button
              type="button"
              className="pf-peak-hourly-chart-close"
              onClick={onClose}
              aria-label={t('powerFlowMonthlyRatesChartCloseAria')}
            >
              {t('powerFlowPeakHourlyChartClose')}
            </button>
          </div>
          {status === 'loading' ? (
            <p className="pf-peak-hourly-chart-status">{t('powerFlowPeakHourlyChartLoading')}</p>
          ) : null}
          {status === 'error' ? (
            <p className="pf-peak-hourly-chart-status pf-peak-hourly-chart-status--error">
              {t('powerFlowMonthlyRatesChartError')}
            </p>
          ) : null}
          {status === 'ready' && rows.length === 0 ? (
            <p className="pf-peak-hourly-chart-status">{t('powerFlowMonthlyRatesChartEmpty')}</p>
          ) : null}
          {status === 'ready' && rows.length > 0 ? (
            <div className="pf-peak-hourly-chart-scroll">
              <div className="pf-peak-hourly-chart-inner" style={{ minWidth: chartWidth }}>
                <ResponsiveContainer width="100%" height={420}>
                  <BarChart
                    data={rows}
                    barCategoryGap="18%"
                    margin={{ top: 52, right: 12, left: 14, bottom: 48 }}
                  >
                    <defs>
                      <linearGradient id={barGradId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#c100b9" />
                        <stop offset="100%" stopColor="#6e00d4" />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#3d3d3d" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="xLabel" tick={{ fill: '#a0a0a0', fontSize: 11 }} />
                    <YAxis
                      domain={[0, 'auto']}
                      tick={{ fill: '#a0a0a0', fontSize: 11 }}
                      tickFormatter={v => {
                        const n = Number(v);
                        return Number.isFinite(n) ? n.toFixed(2) : String(v);
                      }}
                      label={{
                        value: t('powerFlowMonthlyRatesChartYAxis'),
                        angle: -90,
                        position: 'insideLeft',
                        fill: '#fafafa',
                        fontSize: 12,
                      }}
                    />
                    <Tooltip
                      wrapperStyle={{ outline: 'none' }}
                      contentStyle={{
                        background: 'transparent',
                        border: 'none',
                        boxShadow: 'none',
                        padding: 0,
                      }}
                      content={({ active, payload: tipPayload }) => {
                        if (!active || !tipPayload?.length) return null;
                        const p = tipPayload[0].payload;
                        const rate =
                          p.retailUahPerKwh != null && Number.isFinite(p.retailUahPerKwh)
                            ? p.retailUahPerKwh.toFixed(3)
                            : '—';
                        return (
                          <div className="pf-peak-hourly-chart-tooltip">
                            <div className="pf-peak-hourly-chart-tooltip__line">{p.monthLabel}</div>
                            <div className="pf-peak-hourly-chart-tooltip__line">
                              {t('powerFlowMonthlyRatesChartTooltipRate')}: {rate}
                            </div>
                            {p.momAbs != null && p.prevMonthLabel ? (
                              <div className="pf-peak-hourly-chart-tooltip__line">
                                {t('powerFlowMonthlyRatesChartTooltipMom', {
                                  prevMonth: p.prevMonthLabel,
                                  delta:
                                    p.momTop ||
                                    (Number.isFinite(p.momAbs) ? p.momAbs.toFixed(2) : '—'),
                                  pct:
                                    p.momPct != null && Number.isFinite(p.momPct)
                                      ? `${p.momPct > 0 ? '+' : ''}${p.momPct.toFixed(1)}%`
                                      : '—',
                                })}
                              </div>
                            ) : null}
                            {p.importWeighted &&
                            p.gridImportKwh != null &&
                            Number.isFinite(p.gridImportKwh) ? (
                              <div className="pf-peak-hourly-chart-tooltip__line">
                                {t('powerFlowMonthlyRatesChartTooltipImport', {
                                  kwh: p.gridImportKwh.toFixed(1),
                                })}
                              </div>
                            ) : null}
                            {p.partialMonth ? (
                              <div className="pf-peak-hourly-chart-tooltip__line">
                                {t('powerFlowMonthlyRatesChartTooltipMtd')}
                              </div>
                            ) : null}
                          </div>
                        );
                      }}
                    />
                    <Bar
                      dataKey="retailUahPerKwh"
                      fill={`url(#${barGradId})`}
                      radius={[18, 18, 0, 0]}
                      stroke="rgba(255, 255, 255, 0.14)"
                      strokeWidth={0.5}
                      isAnimationActive={false}
                    >
                      <LabelList content={props => <MonthlyBarTopLabel {...props} rows={rows} />} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );

  return createPortal(node, document.body);
}
