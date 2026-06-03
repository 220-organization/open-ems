import { useEffect, useId, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Bar, BarChart, CartesianGrid, LabelList, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useTheme } from './useTheme';

const LOCAL_MONTHLY_RATES_DEMO_DEVICE_SN = '2410102121';

function retailFromBar(b) {
  const retail = typeof b.retailUahPerKwh === 'number' ? b.retailUahPerKwh : Number(b.retailUahPerKwh);
  return Number.isFinite(retail) ? retail : null;
}

function fleetAvgFromBar(b) {
  const v =
    typeof b.fleetAvgRetailUahPerKwh === 'number' ? b.fleetAvgRetailUahPerKwh : Number(b.fleetAvgRetailUahPerKwh);
  return Number.isFinite(v) && v > 1e-9 ? v : null;
}

/** Month-over-month absolute UAH/kWh change vs previous bar (null when not comparable). */
function monthOverMonthDeltaUah(current, previous) {
  if (current == null || previous == null) return null;
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return null;
  if (current <= 1e-9 && previous <= 1e-9) return null;
  if (previous <= 1e-6) return null;
  return current - previous;
}

function vsFleetAvgDeltaPct(device, avg) {
  if (device == null || avg == null) return null;
  if (!Number.isFinite(device) || !Number.isFinite(avg) || avg <= 1e-6) return null;
  return ((device - avg) / avg) * 100;
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

function formatUahPerKwhLabel(value, bcp47, uahUnit, fractionDigits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  const unit = String(uahUnit || '').trim();
  try {
    const num = new Intl.NumberFormat(bcp47, {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(n);
    return unit ? `${num} ${unit}` : num;
  } catch {
    return unit ? `${n.toFixed(fractionDigits)} ${unit}` : n.toFixed(fractionDigits);
  }
}

function buildChartRows(bars, bcp47, uahUnit) {
  const showFleetAvg = bars.some(b => fleetAvgFromBar(b) != null);
  return bars.map((b, i) => {
    const retail = retailFromBar(b);
    const fleetAvg = fleetAvgFromBar(b);
    const prevRetail = i > 0 ? retailFromBar(bars[i - 1]) : null;
    const momAbs = monthOverMonthDeltaUah(retail, prevRetail);
    const rateTop = retail != null ? formatUahPerKwhLabel(retail, bcp47, uahUnit) : null;
    const fleetTop = fleetAvg != null ? formatUahPerKwhLabel(fleetAvg, bcp47, uahUnit) : null;
    let momPct = null;
    if (momAbs != null && prevRetail != null && prevRetail > 1e-6) {
      momPct = (momAbs / prevRetail) * 100;
    }
    const vsAvgPct = vsFleetAvgDeltaPct(retail, fleetAvg);
    const importKwh = typeof b.gridImportKwh === 'number' ? b.gridImportKwh : Number(b.gridImportKwh);
    return {
      barKey: `${b.monthLabel}-${i}`,
      xLabel: formatMonthXLabel(b.monthLabel, bcp47),
      retailUahPerKwh: retail != null && retail > 1e-9 ? retail : 0,
      fleetAvgRetailUahPerKwh: fleetAvg != null ? fleetAvg : 0,
      rateTop,
      fleetTop,
      momAbs,
      momPct,
      vsAvgPct,
      showFleetAvg,
      hasFleetAvg: fleetAvg != null,
      partialMonth: Boolean(b.partialMonth),
      importWeighted: Boolean(b.importWeighted),
      gridImportKwh: Number.isFinite(importKwh) ? importKwh : null,
      monthLabel: b.monthLabel,
      prevMonthLabel: i > 0 ? bars[i - 1].monthLabel : null,
    };
  });
}

function DeviceBarTopLabel({ x, y, width, index, rows, rateFill }) {
  const row = rows?.[index];
  if (row == null || x == null || y == null || width == null || !row.rateTop) return null;
  const cx = Number(x) + Number(width) / 2;
  return (
    <g className="pf-monthly-rates-bar-label">
      <text x={cx} y={Number(y) - 6} textAnchor="middle" fill={rateFill} fontSize={10} fontWeight={600}>
        {row.rateTop}
      </text>
    </g>
  );
}

function FleetBarTopLabel({ x, y, width, index, rows, rateFill }) {
  const row = rows?.[index];
  if (row == null || x == null || y == null || width == null || !row.fleetTop) return null;
  const cx = Number(x) + Number(width) / 2;
  const rateY = Number(y) - 6;
  return (
    <g className="pf-monthly-rates-bar-label">
      <text x={cx} y={rateY} textAnchor="middle" fill={rateFill} fontSize={10} fontWeight={600}>
        {row.fleetTop}
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
  const host = String(window.location.hostname || '')
    .trim()
    .toLowerCase();
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
    {
      monthLabel: '2026-04',
      retailUahPerKwh: 7.81,
      fleetAvgRetailUahPerKwh: 10.5,
      partialMonth: false,
      importWeighted: true,
      gridImportKwh: 1840.0,
    },
    {
      monthLabel: '2026-05',
      retailUahPerKwh: 9.52,
      fleetAvgRetailUahPerKwh: 10.1,
      partialMonth: true,
      importWeighted: true,
      gridImportKwh: 1325.0,
    },
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
    const uahUnit = t('powerFlowPeakHourlyChartYAxisUah');
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
            setRows(buildChartRows(localMonthlyRatesDemoBars(), bcp47, uahUnit));
            setStatus('ready');
            return;
          }
          setStatus('error');
          return;
        }
        const bars = (Array.isArray(data.bars) ? data.bars : []).filter(b => {
          const retail = retailFromBar(b);
          return retail != null && retail > 1e-9;
        });
        if (bars.length === 0 && shouldUseLocalMonthlyRatesDemo(fetchUrl)) {
          setChartScope('import_weighted_dam');
          setRows(
            buildChartRows(
              localMonthlyRatesDemoBars().filter(b => {
                const retail = retailFromBar(b);
                return retail != null && retail > 1e-9;
              }),
              bcp47,
              uahUnit
            )
          );
          setStatus('ready');
          return;
        }
        setChartScope(data.scope === 'import_weighted_dam' ? 'import_weighted_dam' : 'fleet_dam_avg');
        setRows(buildChartRows(bars, bcp47, uahUnit));
        setStatus('ready');
      } catch {
        if (cancelled) return;
        if (shouldUseLocalMonthlyRatesDemo(fetchUrl)) {
          setChartScope('import_weighted_dam');
          setRows(buildChartRows(localMonthlyRatesDemoBars(), bcp47, uahUnit));
          setStatus('ready');
          return;
        }
        setStatus('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, fetchUrl, bcp47, t]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const deviceGradId = useId().replace(/:/g, '_');
  const fleetGradId = useId().replace(/:/g, '_');
  const showFleetAvg = rows.length > 0 && rows[0].showFleetAvg;
  const chartWidth = useMemo(() => Math.max(480, rows.length * (showFleetAvg ? 88 : 52)), [rows.length, showFleetAvg]);
  const palette = useMemo(
    () =>
      resolvedIsDark
        ? {
            deviceTop: '#c100b9',
            deviceBottom: '#6e00d4',
            fleetTop: '#64748b',
            fleetBottom: '#475569',
            grid: '#3d3d3d',
            axisTick: '#a0a0a0',
            axisLabel: '#fafafa',
            rateLabel: '#fafafa',
            fleetLabel: '#94a3b8',
            barStroke: 'rgba(255, 255, 255, 0.14)',
            fleetStroke: 'rgba(255, 255, 255, 0.1)',
          }
        : {
            deviceTop: '#ff4da9',
            deviceBottom: '#8b31ff',
            fleetTop: '#94a3b8',
            fleetBottom: '#64748b',
            grid: 'rgba(120, 85, 145, 0.28)',
            axisTick: '#6b587b',
            axisLabel: '#4b2f63',
            rateLabel: '#4b2f63',
            fleetLabel: '#64748b',
            barStroke: 'rgba(193, 0, 185, 0.16)',
            fleetStroke: 'rgba(100, 116, 139, 0.2)',
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
            <div className="pf-monthly-rates-chart-head-text">
              <h2 id="pf-monthly-rates-chart-title" className="pf-peak-hourly-chart-title pf-monthly-rates-chart-title">
                {title}
              </h2>
            </div>
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
                    barCategoryGap={showFleetAvg ? '22%' : '18%'}
                    barGap={showFleetAvg ? 4 : 0}
                    margin={{ top: 44, right: 12, left: 14, bottom: showFleetAvg ? 56 : 48 }}
                  >
                    <defs>
                      <linearGradient id={deviceGradId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={palette.deviceTop} />
                        <stop offset="100%" stopColor={palette.deviceBottom} />
                      </linearGradient>
                      <linearGradient id={fleetGradId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={palette.fleetTop} />
                        <stop offset="100%" stopColor={palette.fleetBottom} />
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
                    {showFleetAvg ? (
                      <Legend
                        verticalAlign="bottom"
                        wrapperStyle={{ fontSize: 11, fontWeight: 600, paddingTop: 8 }}
                        formatter={value =>
                          value === 'retailUahPerKwh'
                            ? t('powerFlowMonthlyRatesChartLegendDevice')
                            : t('powerFlowMonthlyRatesChartLegendFleetAvg')
                        }
                      />
                    ) : null}
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
                        const uahUnit = t('powerFlowPeakHourlyChartYAxisUah');
                        const rate =
                          p.retailUahPerKwh != null && Number.isFinite(p.retailUahPerKwh)
                            ? formatUahPerKwhLabel(p.retailUahPerKwh, bcp47, uahUnit, 3)
                            : null;
                        return (
                          <div className="pf-peak-hourly-chart-tooltip pf-monthly-rates-chart-tooltip">
                            <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                              {p.monthLabel}
                            </div>
                            <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                              {t('powerFlowMonthlyRatesChartTooltipRate')}: {rate ?? '—'}
                            </div>
                            {p.momPct != null && p.prevMonthLabel ? (
                              <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                                {t('powerFlowMonthlyRatesChartTooltipMom', {
                                  prevMonth: p.prevMonthLabel,
                                  pct: formatSignedPercent(p.momPct, bcp47) || '—',
                                })}
                              </div>
                            ) : null}
                            {p.vsAvgPct != null && p.hasFleetAvg ? (
                              <div className="pf-peak-hourly-chart-tooltip__line pf-monthly-rates-chart-tooltip__line">
                                {t('powerFlowMonthlyRatesChartTooltipVsAvg', {
                                  pct: formatSignedPercent(p.vsAvgPct, bcp47) || '—',
                                })}
                              </div>
                            ) : null}
                            {p.importWeighted && p.gridImportKwh != null && Number.isFinite(p.gridImportKwh) ? (
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
                      name="retailUahPerKwh"
                      dataKey="retailUahPerKwh"
                      fill={`url(#${deviceGradId})`}
                      radius={[14, 14, 0, 0]}
                      stroke={palette.barStroke}
                      strokeWidth={0.5}
                      isAnimationActive={false}
                    >
                      <LabelList
                        content={props => <DeviceBarTopLabel {...props} rows={rows} rateFill={palette.rateLabel} />}
                      />
                    </Bar>
                    {showFleetAvg ? (
                      <Bar
                        name="fleetAvgRetailUahPerKwh"
                        dataKey="fleetAvgRetailUahPerKwh"
                        fill={`url(#${fleetGradId})`}
                        radius={[14, 14, 0, 0]}
                        stroke={palette.fleetStroke}
                        strokeWidth={0.5}
                        isAnimationActive={false}
                      >
                        <LabelList
                          content={props => <FleetBarTopLabel {...props} rows={rows} rateFill={palette.fleetLabel} />}
                        />
                      </Bar>
                    ) : null}
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
