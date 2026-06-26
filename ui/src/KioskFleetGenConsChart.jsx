import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { inverterSelectShortLabel } from './deyeInverterDisplay';

const GEN_COLOR = '#22c55e';
const CONS_COLOR = '#fb923c';

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

function kwhFmt(bcp47) {
  try {
    return new Intl.NumberFormat(bcp47, { maximumFractionDigits: 1 });
  } catch {
    return new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 });
  }
}

function truncateLabel(label, max = 14) {
  const s = String(label || '').trim();
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}

async function fetchDeyeTotals(deviceSn, dateIso) {
  const q = new URLSearchParams({ deviceSn, period: 'day', date: dateIso });
  const r = await fetch(apiUrl(`/api/deye/soc-history-totals?${q}`), { cache: 'no-store' });
  const json = await r.json().catch(() => ({}));
  if (!r.ok || !json?.configured) return null;
  const hasAny =
    json?.consumptionKwh != null || json?.generationKwh != null || json?.importKwh != null;
  if (!hasAny) return null;
  return {
    generationKwh: json.generationKwh != null ? Number(json.generationKwh) : null,
    consumptionKwh: json.consumptionKwh != null ? Number(json.consumptionKwh) : null,
  };
}

async function fetchDeyeClusterTotals(clusterSns, dateIso) {
  const sns = (Array.isArray(clusterSns) ? clusterSns : []).map(s => String(s || '').trim()).filter(Boolean);
  if (!sns.length) return null;
  const parts = await Promise.all(sns.map(sn => fetchDeyeTotals(sn, dateIso)));
  let gen = 0;
  let cons = 0;
  let hasGen = false;
  let hasCons = false;
  for (const part of parts) {
    if (part?.generationKwh != null && Number.isFinite(part.generationKwh)) {
      gen += part.generationKwh;
      hasGen = true;
    }
    if (part?.consumptionKwh != null && Number.isFinite(part.consumptionKwh)) {
      cons += part.consumptionKwh;
      hasCons = true;
    }
  }
  if (!hasGen && !hasCons) return null;
  return {
    generationKwh: hasGen ? gen : null,
    consumptionKwh: hasCons ? cons : null,
  };
}

async function fetchHuaweiTotals(stationCode, dateIso) {
  const q = new URLSearchParams({ stationCodes: stationCode, period: 'day', date: dateIso });
  const r = await fetch(apiUrl(`/api/huawei/station-energy?${q}`), { cache: 'no-store' });
  const json = await r.json().catch(() => ({}));
  if (!json?.ok) return null;
  const item = json?.items?.[0];
  if (!item) return null;
  return {
    generationKwh: item.pvKwh != null ? Number(item.pvKwh) : null,
    consumptionKwh: item.consumptionKwh != null ? Number(item.consumptionKwh) : null,
  };
}

export default function KioskFleetGenConsChart({ deyeItems = [], huaweiItems = [], t, getBcp47Locale }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const tradeDay = useMemo(() => kyivCalendarIso(), []);
  const fmt = useMemo(() => kwhFmt(getBcp47Locale()), [getBcp47Locale]);

  const sourcesKey = useMemo(() => {
    const deye = deyeItems.map(r => r.representativeSn).join(',');
    const hw = huaweiItems.map(r => r.stationCode).join(',');
    return `${tradeDay}|${deye}|${hw}`;
  }, [deyeItems, huaweiItems, tradeDay]);

  useEffect(() => {
    let active = true;
    const deyeList = Array.isArray(deyeItems) ? deyeItems : [];
    const hwList = Array.isArray(huaweiItems) ? huaweiItems : [];
    if (!deyeList.length && !hwList.length) {
      setRows([]);
      setLoading(false);
      setError(false);
      return undefined;
    }

    setLoading(true);
    setError(false);

    (async () => {
      try {
        const tasks = [
          ...deyeList.map(async row => {
            const sns = row.clusterSns?.length ? row.clusterSns : [row.representativeSn];
            const totals = await fetchDeyeClusterTotals(sns, tradeDay);
            return {
              id: `deye-${row.representativeSn}`,
              label: truncateLabel(row.shortLabel || row.representativeSn),
              genKwh: totals?.generationKwh ?? 0,
              consKwh: totals?.consumptionKwh ?? 0,
              hasGen: totals?.generationKwh != null,
              hasCons: totals?.consumptionKwh != null,
            };
          }),
          ...hwList.map(async row => {
            const totals = await fetchHuaweiTotals(row.stationCode, tradeDay);
            const label = inverterSelectShortLabel(row.stationName, row.stationCode);
            return {
              id: `huawei-${row.stationCode}`,
              label: truncateLabel(label || row.stationCode),
              genKwh: totals?.generationKwh ?? 0,
              consKwh: totals?.consumptionKwh ?? 0,
              hasGen: totals?.generationKwh != null,
              hasCons: totals?.consumptionKwh != null,
            };
          }),
        ];
        const next = await Promise.all(tasks);
        if (!active) return;
        const sorted = next
          .filter(r => r.hasGen || r.hasCons)
          .sort((a, b) => Math.max(b.genKwh, b.consKwh) - Math.max(a.genKwh, a.consKwh));
        setRows(sorted);
        setError(sorted.length === 0);
      } catch {
        if (active) {
          setRows([]);
          setError(true);
        }
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [sourcesKey, deyeItems, huaweiItems, tradeDay]);

  const totals = useMemo(() => {
    let gen = 0;
    let cons = 0;
    let anyGen = false;
    let anyCons = false;
    for (const r of rows) {
      if (r.hasGen) {
        gen += r.genKwh;
        anyGen = true;
      }
      if (r.hasCons) {
        cons += r.consKwh;
        anyCons = true;
      }
    }
    return { gen: anyGen ? gen : null, cons: anyCons ? cons : null };
  }, [rows]);

  const chartH = Math.max(220, Math.min(rows.length * 34 + 48, 720));
  const unit = t('damEnergyKwhUnit');

  return (
    <aside className="pf-kiosk-gen-cons" aria-label={t('openEmsKioskFleetGenConsAria')}>
      <header className="pf-kiosk-gen-cons__header">
        <h2 className="pf-kiosk-gen-cons__title">{t('openEmsKioskFleetGenConsTitle')}</h2>
        <p className="pf-kiosk-gen-cons__date">{tradeDay}</p>
      </header>

      <ul className="pf-kiosk-gen-cons__totals" aria-label={t('damEnergyTotalsPvLoadAria')}>
        <li>
          <span className="pf-kiosk-gen-cons__swatch" style={{ background: GEN_COLOR }} aria-hidden />
          {t('damPvLoadTooltipGen')}:{' '}
          <strong>{totals.gen != null ? `${fmt.format(totals.gen)} ${unit}` : '—'}</strong>
        </li>
        <li>
          <span className="pf-kiosk-gen-cons__swatch" style={{ background: CONS_COLOR }} aria-hidden />
          {t('damPvLoadTooltipCons')}:{' '}
          <strong>{totals.cons != null ? `${fmt.format(totals.cons)} ${unit}` : '—'}</strong>
        </li>
      </ul>

      <div className={`pf-kiosk-gen-cons__chart${loading ? ' pf-kiosk-gen-cons__chart--loading' : ''}`}>
        {loading ? <p className="pf-kiosk-gen-cons__status">{t('huaweiTotalsLoading')}</p> : null}
        {!loading && error ? (
          <p className="pf-kiosk-gen-cons__status pf-kiosk-gen-cons__status--muted">{t('huaweiTotalsNoData')}</p>
        ) : null}
        {!loading && rows.length > 0 ? (
          <ResponsiveContainer width="100%" height={chartH}>
            <BarChart
              data={rows}
              layout="vertical"
              margin={{ top: 4, right: 8, left: 4, bottom: 4 }}
              barCategoryGap="18%"
              barGap={2}
            >
              <CartesianGrid stroke="rgba(32,28,40,0.08)" horizontal={false} />
              <XAxis
                type="number"
                tick={{ fill: 'rgba(32,28,40,0.55)', fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={v => fmt.format(v)}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={76}
                tick={{ fill: 'rgba(32,28,40,0.72)', fontSize: 10 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                formatter={(value, name) => [
                  `${fmt.format(Number(value))} ${unit}`,
                  name === 'genKwh' ? t('damPvLoadTooltipGen') : t('damPvLoadTooltipCons'),
                ]}
                labelFormatter={label => label}
                contentStyle={{
                  background: '#ffffff',
                  border: '1px solid rgba(32,28,40,0.12)',
                  borderRadius: 10,
                  fontSize: 12,
                }}
              />
              <Legend
                verticalAlign="top"
                align="right"
                iconType="square"
                iconSize={10}
                wrapperStyle={{ fontSize: 11, paddingBottom: 4 }}
                formatter={value =>
                  value === 'genKwh' ? t('damPvLoadTooltipGen') : t('damPvLoadTooltipCons')
                }
              />
              <Bar dataKey="genKwh" name="genKwh" fill={GEN_COLOR} radius={[0, 3, 3, 0]} maxBarSize={14} />
              <Bar dataKey="consKwh" name="consKwh" fill={CONS_COLOR} radius={[0, 3, 3, 0]} maxBarSize={14} />
            </BarChart>
          </ResponsiveContainer>
        ) : null}
      </div>
    </aside>
  );
}
