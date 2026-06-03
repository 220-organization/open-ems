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
import { useTheme } from './useTheme';

function pctFromBar(b) {
  const v = typeof b.balancingPct === 'number' ? b.balancingPct : Number(b.balancingPct);
  return Number.isFinite(v) ? v : null;
}

function monthOverMonthDeltaPp(current, previous) {
  if (current == null || previous == null) return null;
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return null;
  return current - previous;
}

function formatMomDeltaPp(delta, bcp47) {
  const n = Number(delta);
  if (!Number.isFinite(n) || Math.abs(n) < 0.05) return null;
  try {
    return new Intl.NumberFormat(bcp47, {
      signDisplay: 'exceptZero',
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }).format(n);
  } catch {
    const sign = n > 0 ? '+' : '';
    return `${sign}${n.toFixed(1)}`;
  }
}

function momDeltaFill(delta) {
  const n = Number(delta);
  if (!Number.isFinite(n) || Math.abs(n) < 0.05) return '#a0a0a0';
  return n > 0 ? '#4ade80' : '#f87171';
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

function formatPctLabel(pct, bcp47) {
  if (pct == null || !Number.isFinite(pct)) return '—';
  try {
    return `${new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1, minimumFractionDigits: 1 }).format(pct)}%`;
  } catch {
    return `${pct.toFixed(1)}%`;
  }
}

function buildChartRows(bars, bcp47) {
  const filtered = bars.filter(b => {
    const p = pctFromBar(b);
    return p != null && p > 1e-9;
  });
  return filtered.map((b, i) => {
    const pct = pctFromBar(b);
    const prevPct = i > 0 ? pctFromBar(filtered[i - 1]) : null;
    const momAbs = monthOverMonthDeltaPp(pct, prevPct);
    const momTop = momAbs != null ? formatMomDeltaPp(momAbs, bcp47) : null;
    const valueTop = formatPctLabel(pct, bcp47);
    const peakKwh =
      typeof b.peakWindowImportKwh === 'number' ? b.peakWindowImportKwh : Number(b.peakWindowImportKwh);
    const importTotal =
      typeof b.importTotalKwh === 'number' ? b.importTotalKwh : Number(b.importTotalKwh);
    return {
      barKey: `${b.monthLabel}-${i}`,
      xLabel: formatMonthXLabel(b.monthLabel, bcp47),
      balancingPct: pct != null ? pct : 0,
      valueTop,
      momAbs,
      momTop,
      momFill: momAbs != null ? momDeltaFill(momAbs) : '#a0a0a0',
      partialMonth: Boolean(b.partialMonth),
      peakWindowImportKwh: Number.isFinite(peakKwh) ? peakKwh : null,
      importTotalKwh: Number.isFinite(importTotal) ? importTotal : null,
      monthLabel: b.monthLabel,
      prevMonthLabel: i > 0 ? filtered[i - 1].monthLabel : null,
    };
  });
}

function GridBalancingBarTopLabel({ x, y, width, index, rows, rateFill }) {
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
      <text x={cx} y={rateY} textAnchor="middle" fill={rateFill} fontSize={10} fontWeight={600}>
        {row.valueTop}
      </text>
    </g>
  );
}

export default function GridBalancingChartModal({ open, onClose, fetchUrl, t, bcp47 = 'en-GB', isDark }) {
  const [status, setStatus] = useState('idle');
  const [rows, setRows] = useState([]);
  const { isDark: hookIsDark } = useTheme();
  const resolvedIsDark = typeof isDark === 'boolean' ? isDark : hookIsDark;

  useEffect(() => {
    if (!open) {
      setStatus('idle');
      setRows([]);
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
  const palette = useMemo(
    () =>
      resolvedIsDark
        ? {
            barTop: '#22c55e',
            barBottom: '#15803d',
            grid: '#3d3d3d',
            axisTick: '#a0a0a0',
            axisLabel: '#fafafa',
            rateLabel: '#fafafa',
            barStroke: 'rgba(255, 255, 255, 0.14)',
          }
        : {
            barTop: '#4ade80',
            barBottom: '#16a34a',
            grid: 'rgba(80, 140, 100, 0.28)',
            axisTick: '#4a6b55',
            axisLabel: '#1e4d2e',
            rateLabel: '#1e4d2e',
            barStroke: 'rgba(22, 163, 74, 0.16)',
          },
    [resolvedIsDark]
  );

  if (!open || typeof document === 'undefined') return null;

  const node = (
    <div className="pf-messenger-scrim pf-messenger-scrim--220km" role="presentation" onClick={onClose}>
      <div
        className="pf-messenger-dialog pf-peak-hourly-chart-dialog pf-monthly-rates-chart-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pf-grid-balancing-chart-title"
        onClick={e => e.stopPropagation()}
      >
        <div className="pf-peak-hourly-chart-panel pf-monthly-rates-chart-panel">
          <div className="pf-peak-hourly-chart-head pf-monthly-rates-chart-head">
            <h2
              id="pf-grid-balancing-chart-title"
              className="pf-peak-hourly-chart-title pf-monthly-rates-chart-title"
            >
              {t('powerFlowGridBalancingChartTitle')}
            </h2>
            <button
              type="button"
              className="pf-peak-hourly-chart-close pf-monthly-rates-chart-close"
              onClick={onClose}
              aria-label={t('powerFlowGridBalancingChartCloseAria')}
            >
              {t('powerFlowPeakHourlyChartClose')}
            </button>
          </div>
          {status === 'loading' ? (
            <p className="pf-peak-hourly-chart-status pf-monthly-rates-chart-status">
              {t('powerFlowPeakHourlyChartLoading')}
            </p>
          ) : null}
          {status === 'error' ? (
            <p className="pf-peak-hourly-chart-status pf-peak-hourly-chart-status--error pf-monthly-rates-chart-status">
              {t('powerFlowGridBalancingChartError')}
            </p>
          ) : null}
          {status === 'ready' && rows.length === 0 ? (
            <p className="pf-peak-hourly-chart-status pf-monthly-rates-chart-status">
              {t('powerFlowGridBalancingChartEmpty')}
            </p>
          ) : null}
          {status === 'ready' && rows.length > 0 ? (
            <div className="pf-peak-hourly-chart-scroll pf-monthly-rates-chart-scroll">
              <div className="pf-peak-hourly-chart-inner pf-monthly-rates-chart-inner" style={{ minWidth: chartWidth }}>
                <ResponsiveContainer width="100%" height={420}>
                  <BarChart data={rows} barCategoryGap="18%" margin={{ top: 52, right: 12, left: 14, bottom: 48 }}>
                    <defs>
                      <linearGradient id={barGradId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={palette.barTop} />
                        <stop offset="100%" stopColor={palette.barBottom} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="xLabel" tick={{ fill: palette.axisTick, fontSize: 11, fontWeight: 600 }} />
                    <YAxis
                      domain={[0, 100]}
                      tick={{ fill: palette.axisTick, fontSize: 11, fontWeight: 600 }}
                      tickFormatter={v => {
                        const n = Number(v);
                        return Number.isFinite(n) ? `${Math.round(n)}%` : String(v);
                      }}
                      label={{
                        value: t('powerFlowGridBalancingChartYAxis'),
                        angle: -90,
                        position: 'insideLeft',
                        fill: palette.axisLabel,
                        fontSize: 12,
                        fontWeight: 700,
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
                        const pct =
                          p.balancingPct != null && Number.isFinite(p.balancingPct)
                            ? formatPctLabel(p.balancingPct, bcp47)
                            : '—';
                        return (
                          <div className="pf-peak-hourly-chart-tooltip pf-monthly-rates-chart-tooltip">
                            <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                              {p.monthLabel}
                            </div>
                            <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                              {t('powerFlowGridBalancingChartTooltipPct')}: {pct}
                            </div>
                            {p.momAbs != null && p.prevMonthLabel ? (
                              <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                                {t('powerFlowGridBalancingChartTooltipMom', {
                                  prevMonth: p.prevMonthLabel,
                                  delta: p.momTop || formatMomDeltaPp(p.momAbs, bcp47) || '—',
                                })}
                              </div>
                            ) : null}
                            {p.peakWindowImportKwh != null && Number.isFinite(p.peakWindowImportKwh) ? (
                              <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                                {t('powerFlowGridBalancingChartTooltipPeakImport', {
                                  kwh: p.peakWindowImportKwh.toFixed(1),
                                })}
                              </div>
                            ) : null}
                            {p.importTotalKwh != null && Number.isFinite(p.importTotalKwh) ? (
                              <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                                {t('powerFlowGridBalancingChartTooltipTotalImport', {
                                  kwh: p.importTotalKwh.toFixed(1),
                                })}
                              </div>
                            ) : null}
                            {p.partialMonth ? (
                              <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                                {t('powerFlowMonthlyRatesChartTooltipMtd')}
                              </div>
                            ) : null}
                          </div>
                        );
                      }}
                    />
                    <Bar
                      dataKey="balancingPct"
                      fill={`url(#${barGradId})`}
                      radius={[18, 18, 0, 0]}
                      stroke={palette.barStroke}
                      strokeWidth={0.5}
                      isAnimationActive={false}
                    >
                      <LabelList
                        content={props => (
                          <GridBalancingBarTopLabel {...props} rows={rows} rateFill={palette.rateLabel} />
                        )}
                      />
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
