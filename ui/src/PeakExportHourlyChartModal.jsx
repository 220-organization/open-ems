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

/** Kyiv calendar day + hour from API (no extra TZ conversion). */
function formatXLabel(dayIso, hour) {
  const tail = dayIso.length >= 10 ? dayIso.slice(5, 10) : dayIso;
  return `${tail} ${String(hour).padStart(2, '0')}:00`;
}

// When exportRevenueUah, bars use export kWh × DAM (same hourly series as total export).
export default function PeakExportHourlyChartModal({
  open,
  onClose,
  fetchUrl,
  t,
  hourlyScope = 'total',
  exportRevenueUah = false,
}) {
  const [status, setStatus] = useState('idle');
  const [rows, setRows] = useState([]);
  const [rangeDays, setRangeDays] = useState(7);

  useEffect(() => {
    if (!open) {
      setStatus('idle');
      setRows([]);
      setRangeDays(7);
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
        const d = typeof data.days === 'number' && data.days > 0 ? data.days : 7;
        setRangeDays(d);
        const chart = bars.map((b, i) => {
          const dam = b.damUahPerKwh;
          const ek = typeof b.exportKwh === 'number' ? b.exportKwh : Number(b.exportKwh);
          const damStr =
            dam != null && Number.isFinite(dam) ? dam.toFixed(2) : '—';
          const rev =
            dam != null && Number.isFinite(dam) && Number.isFinite(ek) ? ek * dam : null;
          const revenueTop =
            rev != null && Number.isFinite(rev) ? rev.toFixed(1) : '—';
          return {
            barKey: `${b.dayIso}-${b.hour}-${i}`,
            xLabel: formatXLabel(b.dayIso, b.hour),
            exportKwh: b.exportKwh,
            exportRevenueUah: rev != null && Number.isFinite(rev) ? rev : 0,
            damUahPerKwh: dam,
            damTop: damStr,
            revenueTop,
          };
        });
        setRows(chart);
        setStatus('ready');
      } catch {
        if (!cancelled) setStatus('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, fetchUrl]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  /** Avoid unreadable overlap when many bars; DAM stays in tooltip. */
  const showDamBarLabels = rows.length <= 40;
  /** Enough px per category so top labels (DAM / revenue) do not overlap on narrow viewports. */
  const chartWidth = useMemo(() => {
    const pxPerCategory = showDamBarLabels ? 38 : 22;
    return Math.max(560, rows.length * pxPerCategory);
  }, [rows.length, showDamBarLabels]);
  /** Stable SVG id for bar fill gradient (matches --km220-primary-gradient: #6e00d4 → #c100b9). */
  const barExportGradId = useId().replace(/:/g, '_');

  if (!open || typeof document === 'undefined') return null;

  const titleKey = exportRevenueUah
    ? 'powerFlowExportHourlyChartTitleArbitrage'
    : hourlyScope === 'peak'
      ? 'powerFlowExportHourlyChartTitlePeak'
      : hourlyScope === 'manual'
        ? 'powerFlowExportHourlyChartTitleManual'
        : 'powerFlowExportHourlyChartTitleTotal';
  const title = t(titleKey, { days: rangeDays });

  const node = (
    <div className="pf-messenger-scrim pf-messenger-scrim--220km" role="presentation" onClick={onClose}>
      <div
        className="pf-messenger-dialog pf-peak-hourly-chart-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pf-peak-hourly-chart-title"
        onClick={e => e.stopPropagation()}
      >
        <div className="pf-peak-hourly-chart-panel">
          <div className="pf-peak-hourly-chart-head">
            <h2 id="pf-peak-hourly-chart-title" className="pf-peak-hourly-chart-title">
              {title}
            </h2>
            <button
              type="button"
              className="pf-peak-hourly-chart-close"
              onClick={onClose}
              aria-label={t('powerFlowPeakHourlyChartCloseAria')}
            >
              {t('powerFlowPeakHourlyChartClose')}
            </button>
          </div>
          {status === 'loading' ? (
            <p className="pf-peak-hourly-chart-status">{t('powerFlowPeakHourlyChartLoading')}</p>
          ) : null}
          {status === 'error' ? (
            <p className="pf-peak-hourly-chart-status pf-peak-hourly-chart-status--error">
              {t('powerFlowPeakHourlyChartError')}
            </p>
          ) : null}
          {status === 'ready' && rows.length === 0 ? (
            <p className="pf-peak-hourly-chart-status">{t('powerFlowPeakHourlyChartEmpty')}</p>
          ) : null}
          {status === 'ready' && rows.length > 0 ? (
            <div className="pf-peak-hourly-chart-scroll">
              <div className="pf-peak-hourly-chart-inner" style={{ minWidth: chartWidth }}>
                <ResponsiveContainer width="100%" height={420}>
                  <BarChart
                    data={rows}
                    barCategoryGap="5%"
                    barGap="2%"
                    margin={{
                      top: showDamBarLabels ? 42 : 14,
                      right: 12,
                      left: 14,
                      bottom: 64,
                    }}
                  >
                    <defs>
                      <linearGradient id={barExportGradId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#c100b9" />
                        <stop offset="100%" stopColor="#6e00d4" />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#3d3d3d" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="xLabel"
                      tick={{ fill: '#a0a0a0', fontSize: 9 }}
                      interval={0}
                      angle={-55}
                      textAnchor="end"
                      height={70}
                    />
                    <YAxis
                      domain={[0, 'auto']}
                      tick={{ fill: '#a0a0a0', fontSize: 11 }}
                      tickFormatter={
                        exportRevenueUah
                          ? v => {
                              const n = Number(v);
                              if (!Number.isFinite(n)) return String(v);
                              return n >= 100 ? String(Math.round(n)) : n.toFixed(1);
                            }
                          : undefined
                      }
                      label={{
                        value: exportRevenueUah
                          ? t('powerFlowPeakHourlyChartYAxisUah')
                          : t('powerFlowPeakHourlyChartYAxis'),
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
                        const kwh =
                          typeof p.exportKwh === 'number'
                            ? p.exportKwh.toFixed(3)
                            : String(p.exportKwh ?? '');
                        const dam =
                          p.damUahPerKwh != null && Number.isFinite(p.damUahPerKwh)
                            ? p.damUahPerKwh.toFixed(3)
                            : '—';
                        const rev =
                          typeof p.exportRevenueUah === 'number' && Number.isFinite(p.exportRevenueUah)
                            ? p.exportRevenueUah.toFixed(2)
                            : null;
                        return (
                          <div className="pf-peak-hourly-chart-tooltip">
                            <div className="pf-peak-hourly-chart-tooltip__line">{p.xLabel}</div>
                            {exportRevenueUah ? (
                              <div className="pf-peak-hourly-chart-tooltip__line">
                                {t('powerFlowPeakHourlyChartTooltipRevenueUah')}:{' '}
                                {rev != null
                                  ? `${rev} ${t('roiValueUahUnit')}`
                                  : '—'}
                              </div>
                            ) : null}
                            <div className="pf-peak-hourly-chart-tooltip__line">
                              {t('powerFlowPeakHourlyChartTooltipKwh')}: {kwh}
                            </div>
                            <div className="pf-peak-hourly-chart-tooltip__line">
                              {t('powerFlowPeakHourlyChartTooltipDam')}: {dam}
                            </div>
                          </div>
                        );
                      }}
                    />
                    <Bar
                      dataKey={exportRevenueUah ? 'exportRevenueUah' : 'exportKwh'}
                      fill={`url(#${barExportGradId})`}
                      radius={[18, 18, 0, 0]}
                      stroke="rgba(255, 255, 255, 0.14)"
                      strokeWidth={0.5}
                      isAnimationActive={false}
                    >
                      {showDamBarLabels ? (
                        <LabelList
                          dataKey={exportRevenueUah ? 'revenueTop' : 'damTop'}
                          position="top"
                          offset={6}
                          fill="#fafafa"
                          fontSize={10}
                        />
                      ) : null}
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
