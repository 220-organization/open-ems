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

const LOCAL_MONTHLY_RATES_DEMO_DEVICE_SN = '2410102121';

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

function formatSignedPercent(pct, bcp47) {
  const n = Number(pct);
  if (!Number.isFinite(n)) return null;
  try {
    return `${new Intl.NumberFormat(bcp47, {
      signDisplay: 'always',
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }).format(n)}%`;
  } catch {
    const sign = n > 0 ? '+' : '';
    return `${sign}${n.toFixed(1)}%`;
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

function MonthlyBarTopLabel({ x, y, width, index, rows, rateFill }) {
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

function shouldUseLocalMonthlyRatesDemo(fetchUrl) {
  if (typeof window === 'undefined') return false;
  const host = String(window.location.hostname || '').trim().toLowerCase();
  if (host !== 'localhost' && host !== '127.0.0.1') return false;
  const selected = new URLSearchParams(window.location.search || '');
  if (selected.get('market') !== 'oree' || selected.get('zone') !== 'ES') return false;
  if (selected.get('inverter') !== `deye:${LOCAL_MONTHLY_RATES_DEMO_DEVICE_SN}`) return false;
  try {
    const u = new URL(fetchUrl, window.location.origin);
    return u.searchParams.get('deviceSn') === LOCAL_MONTHLY_RATES_DEMO_DEVICE_SN;
  } catch {
    return false;
  }
}

function localMonthlyRatesDemoBars() {
  return [
    { monthLabel: '2025-06', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2025-07', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2025-08', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2025-09', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2025-10', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2025-11', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2025-12', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2026-01', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2026-02', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2026-03', retailUahPerKwh: 0.0, partialMonth: false, importWeighted: true, gridImportKwh: 0.0 },
    { monthLabel: '2026-04', retailUahPerKwh: 7.81, partialMonth: false, importWeighted: true, gridImportKwh: 1840.0 },
    { monthLabel: '2026-05', retailUahPerKwh: 9.52, partialMonth: true, importWeighted: true, gridImportKwh: 1325.0 },
  ];
}

export default function MonthlyRetailTariffChartModal({
  open,
  onClose,
  fetchUrl,
  t,
  bcp47 = 'en-GB',
  isDark,
}) {
  const [status, setStatus] = useState('idle');
  const [rows, setRows] = useState([]);
  const [chartScope, setChartScope] = useState('fleet_dam_avg');
  const { isDark: hookIsDark } = useTheme();
  const resolvedIsDark = typeof isDark === 'boolean' ? isDark : hookIsDark;

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
          if (shouldUseLocalMonthlyRatesDemo(fetchUrl)) {
            setChartScope('import_weighted_dam');
            setRows(buildChartRows(localMonthlyRatesDemoBars(), bcp47));
            setStatus('ready');
            return;
          }
          setStatus('error');
          return;
        }
        const bars = Array.isArray(data.bars) ? data.bars : [];
        if (bars.length === 0 && shouldUseLocalMonthlyRatesDemo(fetchUrl)) {
          setChartScope('import_weighted_dam');
          setRows(buildChartRows(localMonthlyRatesDemoBars(), bcp47));
          setStatus('ready');
          return;
        }
        setChartScope(data.scope === 'import_weighted_dam' ? 'import_weighted_dam' : 'fleet_dam_avg');
        setRows(buildChartRows(bars, bcp47));
        setStatus('ready');
      } catch {
        if (cancelled) return;
        if (shouldUseLocalMonthlyRatesDemo(fetchUrl)) {
          setChartScope('import_weighted_dam');
          setRows(buildChartRows(localMonthlyRatesDemoBars(), bcp47));
          setStatus('ready');
          return;
        }
        setStatus('error');
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
            barTop: '#c100b9',
            barBottom: '#6e00d4',
            grid: '#3d3d3d',
            axisTick: '#a0a0a0',
            axisLabel: '#fafafa',
            rateLabel: '#fafafa',
            barStroke: 'rgba(255, 255, 255, 0.14)',
          }
        : {
            barTop: '#ff4da9',
            barBottom: '#8b31ff',
            grid: 'rgba(120, 85, 145, 0.28)',
            axisTick: '#6b587b',
            axisLabel: '#4b2f63',
            rateLabel: '#4b2f63',
            barStroke: 'rgba(193, 0, 185, 0.16)',
          },
    [resolvedIsDark]
  );

  if (!open || typeof document === 'undefined') return null;

  const title =
    chartScope === 'import_weighted_dam'
      ? t('powerFlowMonthlyRatesChartTitleDevice')
      : t('powerFlowMonthlyRatesChartTitle');

  const node = (
    <div className="pf-messenger-scrim pf-messenger-scrim--220km" role="presentation" onClick={onClose}>
      <div
        className="pf-messenger-dialog pf-peak-hourly-chart-dialog pf-monthly-rates-chart-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pf-monthly-rates-chart-title"
        onClick={e => e.stopPropagation()}
      >
        <div className="pf-peak-hourly-chart-panel pf-monthly-rates-chart-panel">
          <div className="pf-peak-hourly-chart-head pf-monthly-rates-chart-head">
            <h2 id="pf-monthly-rates-chart-title" className="pf-peak-hourly-chart-title pf-monthly-rates-chart-title">
              {title}
            </h2>
            <button
              type="button"
              className="pf-peak-hourly-chart-close pf-monthly-rates-chart-close"
              onClick={onClose}
              aria-label={t('powerFlowMonthlyRatesChartCloseAria')}
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
              {t('powerFlowMonthlyRatesChartError')}
            </p>
          ) : null}
          {status === 'ready' && rows.length === 0 ? (
            <p className="pf-peak-hourly-chart-status pf-monthly-rates-chart-status">
              {t('powerFlowMonthlyRatesChartEmpty')}
            </p>
          ) : null}
          {status === 'ready' && rows.length > 0 ? (
            <div className="pf-peak-hourly-chart-scroll pf-monthly-rates-chart-scroll">
              <div className="pf-peak-hourly-chart-inner pf-monthly-rates-chart-inner" style={{ minWidth: chartWidth }}>
                <ResponsiveContainer width="100%" height={420}>
                  <BarChart
                    data={rows}
                    barCategoryGap="18%"
                    margin={{ top: 52, right: 12, left: 14, bottom: 48 }}
                  >
                    <defs>
                      <linearGradient id={barGradId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={palette.barTop} />
                        <stop offset="100%" stopColor={palette.barBottom} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="xLabel" tick={{ fill: palette.axisTick, fontSize: 11, fontWeight: 600 }} />
                    <YAxis
                      domain={[0, 'auto']}
                      tick={{ fill: palette.axisTick, fontSize: 11, fontWeight: 600 }}
                      tickFormatter={v => {
                        const n = Number(v);
                        return Number.isFinite(n) ? n.toFixed(2) : String(v);
                      }}
                      label={{
                        value: t('powerFlowMonthlyRatesChartYAxis'),
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
                        const rate =
                          p.retailUahPerKwh != null && Number.isFinite(p.retailUahPerKwh)
                            ? p.retailUahPerKwh.toFixed(3)
                            : '—';
                        return (
                          <div className="pf-peak-hourly-chart-tooltip pf-monthly-rates-chart-tooltip">
                            <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                              {p.monthLabel}
                            </div>
                            <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                              {t('powerFlowMonthlyRatesChartTooltipRate')}: {rate}
                            </div>
                            {p.momAbs != null && p.prevMonthLabel ? (
                              <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                                {t('powerFlowMonthlyRatesChartTooltipMom', {
                                  prevMonth: p.prevMonthLabel,
                                  delta:
                                    p.momTop ||
                                    (Number.isFinite(p.momAbs) ? p.momAbs.toFixed(2) : '—'),
                                  pct: p.momPct != null ? formatSignedPercent(p.momPct, bcp47) || '—' : '—',
                                })}
                              </div>
                            ) : null}
                            {p.importWeighted &&
                            p.gridImportKwh != null &&
                            Number.isFinite(p.gridImportKwh) ? (
                              <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                                {t('powerFlowMonthlyRatesChartTooltipImport', {
                                  kwh: p.gridImportKwh.toFixed(1),
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
                      dataKey="retailUahPerKwh"
                      fill={`url(#${barGradId})`}
                      radius={[18, 18, 0, 0]}
                      stroke={palette.barStroke}
                      strokeWidth={0.5}
                      isAnimationActive={false}
                    >
                      <LabelList
                        content={props => <MonthlyBarTopLabel {...props} rows={rows} rateFill={palette.rateLabel} />}
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
