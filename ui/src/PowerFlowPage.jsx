import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BINANCE_MINER_URL,
  EV_LIST_URL,
  SITE_220KM_HOME,
  FLOW_DOT_MOTION_DUR,
  computeSimulatedSources,
  computeWideGeometry,
  edgeInsetPx,
  flowMotionPath,
  formatPower,
  formatUsdt,
} from './powerFlowEngine';
import DamChartPanel from './DamChartPanel';
import './power-flow.css';
import './dam-chart.css';

const INVERTER_STORAGE = 'pf-deye-inverter';

/** Short language codes in header (saves horizontal space). */
const LANG_HEADER_CODE = {
  en: 'EN',
  uk: 'UK',
  pl: 'PL',
  cs: 'CS',
  nl: 'NL',
  bg: 'BG',
  fr: 'FR',
  es: 'ES',
};

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  if (!base) return path;
  return `${base}${path}`;
}

function MotionDot({ pathD }) {
  return (
    <circle r="5.8" fill="url(#pf-flow-dot-grad)" className="pf-flow-dot">
      <animateMotion
        dur={FLOW_DOT_MOTION_DUR}
        repeatCount="indefinite"
        calcMode="spline"
        keyTimes="0;1"
        keySplines="0.45 0 0.55 1"
        path={pathD}
      />
      <animate
        attributeName="opacity"
        values="0.98;0.98;0"
        keyTimes="0;0.82;1"
        dur={FLOW_DOT_MOTION_DUR}
        repeatCount="indefinite"
      />
    </circle>
  );
}

export default function PowerFlowPage({
  t,
  getBcp47Locale,
  locale,
  SUPPORTED,
  LOCALE_NAMES,
  onLangSelectChange,
}) {
  const graphRef = useRef(null);
  const [graphWidth, setGraphWidth] = useState(400);
  const [stationFilter, setStationFilter] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get('station') || '';
    } catch {
      return '';
    }
  });
  const [loadError, setLoadError] = useState('');
  const [realtimePower, setRealtimePower] = useState(null);
  const [minerSnap, setMinerSnap] = useState(null);
  const [inverterRows, setInverterRows] = useState({
    loading: true,
    configured: false,
    items: [],
    error: false,
  });
  const [chargingPorts, setChargingPorts] = useState({
    loading: true,
    ok: true,
    items: [],
  });
  const [simTick, setSimTick] = useState(0);

  const bcp47 = getBcp47Locale();
  const inverterSocFmt = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 1,
      }),
    [bcp47],
  );

  const geoForPortsRef = useRef(null);
  const geoRequestedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const readGeoOnce = () =>
      new Promise((resolve) => {
        if (typeof navigator === 'undefined' || !navigator.geolocation) {
          resolve(null);
          return;
        }
        navigator.geolocation.getCurrentPosition(
          (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
          () => resolve(null),
          { maximumAge: 300_000, timeout: 8_000 },
        );
      });

    const load = async () => {
      setChargingPorts((s) => ({ ...s, loading: true }));
      try {
        if (!geoRequestedRef.current) {
          geoRequestedRef.current = true;
          geoForPortsRef.current = await readGeoOnce();
        }
        const geo = geoForPortsRef.current;
        const params = new URLSearchParams();
        if (geo) {
          params.set('lat', String(geo.lat));
          params.set('lon', String(geo.lon));
        }
        const qs = params.toString();
        const r = await fetch(apiUrl(`/api/b2b/charging-ports${qs ? `?${qs}` : ''}`), {
          cache: 'no-store',
        });
        const data = await r.json();
        if (cancelled) return;
        const items = Array.isArray(data?.items) ? data.items : [];
        setChargingPorts({
          loading: false,
          ok: data?.ok !== false,
          items,
        });
      } catch {
        if (!cancelled) {
          setChargingPorts({ loading: false, ok: false, items: [] });
        }
      }
    };

    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    document.title = t('pageTitle');
    document.documentElement.lang = locale === 'uk' ? 'uk' : locale;
  }, [t, locale]);

  useEffect(() => {
    const el = graphRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => {
      setGraphWidth(el.offsetWidth || 400);
    });
    ro.observe(el);
    setGraphWidth(el.offsetWidth || 400);
    return () => ro.disconnect();
  }, []);

  const fetchRealtime = useCallback(async () => {
    const q = stationFilter.trim() ? `?station=${encodeURIComponent(stationFilter.trim())}` : '';
    const r = await fetch(apiUrl(`/api/b2b/realtime-power${q}`), { cache: 'no-store' });
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    return r.json();
  }, [stationFilter]);

  const fetchMiner = useCallback(async () => {
    const r = await fetch(apiUrl('/api/b2b/miner-power'), { cache: 'no-store' });
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    return r.json();
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchRealtime();
        if (!cancelled) {
          setRealtimePower(data);
          setLoadError('');
        }
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
      }
    })();
    const id = setInterval(async () => {
      try {
        const data = await fetchRealtime();
        setRealtimePower(data);
        setLoadError('');
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : String(e));
      }
    }, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [fetchRealtime]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchMiner();
        if (!cancelled) setMinerSnap(data);
      } catch {
        /* keep previous */
      }
    })();
    const id = setInterval(async () => {
      try {
        const data = await fetchMiner();
        if (!cancelled) setMinerSnap(data);
      } catch {
        /* keep */
      }
    }, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [fetchMiner]);

  useEffect(() => {
    let cancelled = false;
    const loadInverters = async () => {
      try {
        const r = await fetch(apiUrl('/api/deye/inverters'), { cache: 'no-store' });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (!r.ok) {
          setInverterRows({ loading: false, configured: false, items: [], error: true });
        } else {
          setInverterRows({
            loading: false,
            configured: !!data.configured,
            items: data.items || [],
            error: false,
          });
        }
      } catch {
        if (!cancelled) {
          setInverterRows({ loading: false, configured: false, items: [], error: true });
        }
      }
    };
    loadInverters();
    const id = setInterval(loadInverters, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const [inverterValue, setInverterValue] = useState('');

  useEffect(() => {
    if (inverterRows.loading || !inverterRows.configured || inverterRows.error) return;
    let want = '';
    try {
      want = new URLSearchParams(window.location.search).get('inverter') || '';
      if (!want) want = localStorage.getItem(INVERTER_STORAGE) || '';
    } catch {
      /* ignore */
    }
    if (want && inverterRows.items.some((r) => r.deviceSn === want)) {
      setInverterValue(want);
    }
  }, [inverterRows]);

  const onInverterChange = useCallback((e) => {
    const v = e.target.value.trim();
    setInverterValue(v);
    try {
      if (v) localStorage.setItem(INVERTER_STORAGE, v);
      else localStorage.removeItem(INVERTER_STORAGE);
    } catch {
      /* ignore */
    }
    const u = new URL(window.location.href);
    if (v) u.searchParams.set('inverter', v);
    else u.searchParams.delete('inverter');
    window.history.replaceState({}, '', u);
  }, []);

  const selInverterSn = inverterValue.trim();

  const [socBySn, setSocBySn] = useState({});
  const [socListLoading, setSocListLoading] = useState(false);
  /** Deye live metrics when an inverter is selected: battery, load, PV, grid. */
  const [deyeLive, setDeyeLive] = useState(null);
  const [deyeLiveLoading, setDeyeLiveLoading] = useState(false);

  const inverterSnsKey = useMemo(
    () =>
      inverterRows.items
        .map((r) => r.deviceSn)
        .filter(Boolean)
        .sort()
        .join(','),
    [inverterRows.items],
  );

  useEffect(() => {
    if (!inverterRows.configured || inverterRows.items.length === 0) {
      setSocBySn({});
      setSocListLoading(false);
      return undefined;
    }
    const sns = inverterRows.items.map((r) => r.deviceSn).filter(Boolean);
    if (sns.length === 0) {
      setSocBySn({});
      return undefined;
    }
    let cancelled = false;
    const loadSocs = async () => {
      setSocListLoading(true);
      try {
        const r = await fetch(apiUrl('/api/deye/inverter-socs'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ deviceSns: sns }),
          cache: 'no-store',
        });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        const next = {};
        if (r.ok && data.ok && Array.isArray(data.items)) {
          for (const it of data.items) {
            const sn = it.deviceSn != null ? String(it.deviceSn) : '';
            if (!sn) continue;
            const p = it.socPercent;
            next[sn] =
              p != null && Number.isFinite(Number(p)) ? Number(p) : null;
          }
        }
        setSocBySn(next);
      } catch {
        if (!cancelled) setSocBySn({});
      } finally {
        if (!cancelled) setSocListLoading(false);
      }
    };
    loadSocs();
    const id = setInterval(loadSocs, 300_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- inverterSnsKey tracks deviceSn set; avoids interval reset on new [] ref
  }, [inverterRows.configured, inverterSnsKey]);

  useEffect(() => {
    if (!selInverterSn || !inverterRows.configured || inverterRows.error) {
      setDeyeLive(null);
      setDeyeLiveLoading(false);
      return undefined;
    }
    let cancelled = false;
    const loadLive = async () => {
      setDeyeLiveLoading(true);
      try {
        const q = new URLSearchParams({ deviceSn: selInverterSn });
        const r = await fetch(`${apiUrl('/api/deye/ess-power')}?${q}`, { cache: 'no-store' });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (r.ok && data.ok && data.configured) {
          const bat = data.batteryPowerW;
          const loadW = data.loadPowerW;
          const pvW = data.pvPowerW;
          const gridW = data.gridPowerW;
          setDeyeLive({
            batteryPowerW:
              bat != null && Number.isFinite(Number(bat)) ? Number(bat) : null,
            loadPowerW:
              loadW != null && Number.isFinite(Number(loadW)) ? Number(loadW) : null,
            pvPowerW:
              pvW != null && Number.isFinite(Number(pvW)) ? Math.max(0, Number(pvW)) : null,
            gridPowerW:
              gridW != null && Number.isFinite(Number(gridW)) ? Number(gridW) : null,
          });
        } else {
          setDeyeLive(null);
        }
      } catch {
        if (!cancelled) setDeyeLive(null);
      } finally {
        if (!cancelled) setDeyeLiveLoading(false);
      }
    };
    loadLive();
    const id = setInterval(loadLive, 20_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selInverterSn, inverterRows.configured, inverterRows.error]);

  const onStationChange = useCallback(
    (e) => {
      const v = e.target.value;
      setStationFilter(v);
      const u = new URL(window.location.href);
      const t = v.trim();
      if (t) u.searchParams.set('station', t);
      else u.searchParams.delete('station');
      window.history.replaceState({}, '', u);
    },
    [],
  );

  const portSelectOptions = useMemo(() => {
    const base = chargingPorts.items;
    const s = stationFilter.trim();
    if (!s || base.some((x) => String(x.number) === s)) {
      return base;
    }
    return [...base, { number: s, label: s, distanceMeters: null, powerWt: null }];
  }, [chargingPorts.items, stationFilter]);

  const consumptionMw = realtimePower?.powerMw ?? 0;
  const liveMinerW =
    minerSnap?.configured && minerSnap.powerW != null && Number.isFinite(minerSnap.powerW)
      ? Math.max(0, minerSnap.powerW)
      : null;

  /* simTick triggers a periodic re-render so Kyiv-time simulation updates */
  void simTick;
  const sim = computeSimulatedSources(consumptionMw, liveMinerW);

  const { solarW, gridW, essW, minerW, consumptionW } = sim;
  const useLivePv =
    Boolean(selInverterSn) &&
    deyeLive?.pvPowerW != null &&
    Number.isFinite(deyeLive.pvPowerW);
  const displaySolarW = selInverterSn
    ? useLivePv
      ? Math.max(0, deyeLive.pvPowerW)
      : null
    : solarW;
  /** Aggregate EV charging (B2B) is misleading next to a single Deye site — hide when an inverter is selected. */
  const showEvAggregate = !selInverterSn;
  const useLiveGrid =
    Boolean(selInverterSn) &&
    deyeLive?.gridPowerW != null &&
    Number.isFinite(deyeLive.gridPowerW);
  const effectiveGridW = selInverterSn ? (useLiveGrid ? deyeLive.gridPowerW : null) : gridW;
  const useLiveEss =
    Boolean(selInverterSn) &&
    deyeLive?.batteryPowerW != null &&
    Number.isFinite(deyeLive.batteryPowerW);
  const displayEssW = useLiveEss ? deyeLive.batteryPowerW : essW;
  const displayEssCharging = displayEssW < 0;
  const displayLoadW =
    Boolean(selInverterSn) &&
    deyeLive?.loadPowerW != null &&
    Number.isFinite(deyeLive.loadPowerW)
      ? Math.max(0, deyeLive.loadPowerW)
      : null;
  const loadFlowActive = displayLoadW != null && displayLoadW > 0;
  const solarFlowActive = displaySolarW != null && displaySolarW > 0;
  const gridFlowActive = effectiveGridW != null && Math.abs(effectiveGridW) > 0;
  const gridSelling = effectiveGridW != null && effectiveGridW < 0;
  const hasFlow =
    (showEvAggregate && consumptionW > 0) ||
    minerW > 0 ||
    displayEssW !== 0 ||
    gridFlowActive ||
    loadFlowActive;
  const geom = useMemo(() => computeWideGeometry(graphWidth), [graphWidth]);
  const graphAnchorPct = useMemo(
    () => (edgeInsetPx(graphWidth) / Math.max(graphWidth, 1)) * 100,
    [graphWidth],
  );

  const gBuy = geom.gridLine;
  const gSell = geom.gridLineSelling;

  const gridLineCoords = gridSelling
    ? { ...gSell, active: hasFlow && gridFlowActive }
    : { ...gBuy, active: hasFlow && gridFlowActive };

  const gridDotPath = gridSelling
    ? flowMotionPath(gSell.start.x, gSell.start.y, gSell.end.x, gSell.end.y)
    : flowMotionPath(gBuy.start.x, gBuy.start.y, gBuy.end.x, gBuy.end.y);

  const essActive = hasFlow && Math.abs(displayEssW) > 0;
  /** Motion dots that travel *into* the hub (line ends at EMS): solar, grid import, ESS discharge. */
  const hubLogoInboundFlow =
    solarFlowActive ||
    (!gridSelling && gridLineCoords.active) ||
    (essActive && !displayEssCharging);
  const essCoords = displayEssCharging ? geom.essLineCharging : geom.essLine;
  const essPath = displayEssCharging
    ? flowMotionPath(
        geom.essLineCharging.start.x,
        geom.essLineCharging.start.y,
        geom.essLineCharging.end.x,
        geom.essLineCharging.end.y,
      )
    : flowMotionPath(geom.essLine.start.x, geom.essLine.start.y, geom.essLine.end.x, geom.essLine.end.y);

  const usdt = formatUsdt(minerSnap?.minedUsdtToday, bcp47);
  const tf = minerSnap?.tariffUahPerKwh;
  let minerLabel = t('nodeMiner');
  if (
    minerSnap?.configured &&
    minerSnap.workersActive != null &&
    minerSnap.workersTotal != null
  ) {
    minerLabel += ` (${minerSnap.workersActive}/${minerSnap.workersTotal})`;
  }

  const evBusy = showEvAggregate && realtimePower == null && loadError === '';
  const evFlowActive = showEvAggregate && consumptionW > 0;
  const qrBase = process.env.PUBLIC_URL || '';

  const essSocHasKey =
    Boolean(selInverterSn) && Object.prototype.hasOwnProperty.call(socBySn, selInverterSn);
  const essSocPercent = essSocHasKey ? socBySn[selInverterSn] : undefined;
  const essSocPending = Boolean(selInverterSn && !essSocHasKey && socListLoading);

  useEffect(() => {
    const id = setInterval(() => setSimTick((n) => n + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="pf-body">
      <div className="pf-root">
        <header className="pf-header">
          <div className="pf-station-field pf-inverter-field">
            <select
              id="pf-inverter"
              className="pf-inverter-select pf-header-select--inverter"
              aria-label={t('inverterSelectAria')}
              title={t('inverterSelectAria')}
              value={inverterRows.loading ? '' : inverterValue}
              onChange={onInverterChange}
            >
              {inverterRows.loading ? (
                <option value="" disabled>
                  …
                </option>
              ) : inverterRows.error ? (
                <option value="" disabled>
                  {t('inverterLoadError')}
                </option>
              ) : !inverterRows.configured ? (
                <option value="" disabled>
                  {t('inverterNotConfigured')}
                </option>
              ) : (
                <>
                  <option value="">{t('inverterOptionNone')}</option>
                  {inverterRows.items.map((row) => {
                    const p = socBySn[row.deviceSn];
                    const socSuffix =
                      p != null && Number.isFinite(p)
                        ? ` · ${inverterSocFmt.format(p)}%`
                        : '';
                    const rawLabel = String(row.label || '').trim();
                    const shortLabel = rawLabel
                      ? rawLabel.split(' — ')[0].trim() || rawLabel
                      : String(row.deviceSn || '').trim();
                    return (
                      <option key={row.deviceSn} value={row.deviceSn}>
                        {shortLabel + socSuffix}
                      </option>
                    );
                  })}
                </>
              )}
            </select>
          </div>
          <div className="pf-station-field">
            <select
              id="pf-station"
              className="pf-inverter-select pf-header-select--port"
              aria-label={t('stationLabel')}
              title={t('stationPlaceholder')}
              value={stationFilter}
              onChange={onStationChange}
            >
              <option value="">
                {chargingPorts.loading ? '…' : t('stationPlaceholder')}
              </option>
              {portSelectOptions.map((row) => {
                const num = String(row.number);
                return (
                  <option key={num} value={num}>
                    {num}
                  </option>
                );
              })}
            </select>
          </div>
          <select
            id="pf-lang"
            className="pf-lang-select pf-header-select--lang"
            aria-label={t('langSelectAria')}
            title={t('langSelectAria')}
            value={locale}
            onChange={onLangSelectChange}
          >
            {SUPPORTED.map((code) => (
              <option key={code} value={code} title={LOCALE_NAMES[code] || code}>
                {LANG_HEADER_CODE[code] || String(code).toUpperCase().slice(0, 2)}
              </option>
            ))}
          </select>
        </header>

        <div className="pf-graph-wrap">
          <div
            id="pf-graph"
            ref={graphRef}
            className="pf-graph"
            style={{ '--pf-graph-anchor-pct': `${graphAnchorPct}%` }}
            aria-label={t('graphAriaLabel')}
          >
            <div className="pf-graph-sizer" aria-hidden="true" />
            <svg
              id="pf-svg"
              className="pf-flow-svg"
              viewBox="0 0 400 400"
              preserveAspectRatio="xMidYMid meet"
            >
              <defs>
                <radialGradient
                  id="pf-flow-dot-grad"
                  cx="40%"
                  cy="40%"
                  r="65%"
                  gradientUnits="objectBoundingBox"
                >
                  <stop offset="0%" stopColor="#fdf4ff" />
                  <stop offset="60%" stopColor="#e879f9" />
                  <stop offset="100%" stopColor="#a855f7" />
                </radialGradient>
              </defs>
              <g id="pf-lines">
                <line
                  id="pf-line-solar"
                  className="pf-line"
                  data-active={solarFlowActive ? 'true' : 'false'}
                  x1={geom.solarLine.start.x}
                  y1={geom.solarLine.start.y}
                  x2={geom.solarLine.end.x}
                  y2={geom.solarLine.end.y}
                />
                <line
                  id="pf-line-grid"
                  className="pf-line"
                  data-active={gridLineCoords.active ? 'true' : 'false'}
                  x1={gridLineCoords.start.x}
                  y1={gridLineCoords.start.y}
                  x2={gridLineCoords.end.x}
                  y2={gridLineCoords.end.y}
                />
                <line
                  id="pf-line-load"
                  className="pf-line"
                  data-active={loadFlowActive ? 'true' : 'false'}
                  x1={geom.loadLine.start.x}
                  y1={geom.loadLine.start.y}
                  x2={geom.loadLine.end.x}
                  y2={geom.loadLine.end.y}
                />
                <line
                  id="pf-line-ess"
                  className="pf-line"
                  data-active={essActive ? 'true' : 'false'}
                  x1={essCoords.start.x}
                  y1={essCoords.start.y}
                  x2={essCoords.end.x}
                  y2={essCoords.end.y}
                />
                <line
                  id="pf-line-miner"
                  className="pf-line"
                  data-active={hasFlow && minerW > 0 ? 'true' : 'false'}
                  x1={geom.minerLine.start.x}
                  y1={geom.minerLine.start.y}
                  x2={geom.minerLine.end.x}
                  y2={geom.minerLine.end.y}
                />
                <line
                  id="pf-line-cons"
                  className="pf-line"
                  data-active={evFlowActive ? 'true' : 'false'}
                  x1={geom.consumptionLine.start.x}
                  y1={geom.consumptionLine.start.y}
                  x2={geom.consumptionLine.end.x}
                  y2={geom.consumptionLine.end.y}
                />
              </g>
              <g id="pf-dots">
                <g
                  id="pf-dot-solar"
                  style={{ display: solarFlowActive ? undefined : 'none' }}
                >
                  <MotionDot
                    pathD={flowMotionPath(
                      geom.solarLine.start.x,
                      geom.solarLine.start.y,
                      geom.solarLine.end.x,
                      geom.solarLine.end.y,
                    )}
                  />
                </g>
                <g id="pf-dot-grid" style={{ display: gridLineCoords.active ? undefined : 'none' }}>
                  <MotionDot pathD={gridDotPath} />
                </g>
                <g
                  id="pf-dot-load"
                  style={{ display: loadFlowActive ? undefined : 'none' }}
                >
                  <MotionDot
                    pathD={flowMotionPath(
                      geom.loadLine.start.x,
                      geom.loadLine.start.y,
                      geom.loadLine.end.x,
                      geom.loadLine.end.y,
                    )}
                  />
                </g>
                <g id="pf-dot-ess" style={{ display: essActive ? undefined : 'none' }}>
                  <MotionDot pathD={essPath} />
                </g>
                <g
                  id="pf-dot-miner"
                  style={{ display: hasFlow && minerW > 0 ? undefined : 'none' }}
                >
                  <MotionDot
                    pathD={flowMotionPath(
                      geom.minerLine.start.x,
                      geom.minerLine.start.y,
                      geom.minerLine.end.x,
                      geom.minerLine.end.y,
                    )}
                  />
                </g>
                <g
                  id="pf-dot-cons"
                  style={{ display: evFlowActive ? undefined : 'none' }}
                >
                  <MotionDot
                    pathD={flowMotionPath(
                      geom.consumptionLine.start.x,
                      geom.consumptionLine.start.y,
                      geom.consumptionLine.end.x,
                      geom.consumptionLine.end.y,
                    )}
                  />
                </g>
              </g>
            </svg>

            <div id="pf-nodes">
              <div
                className="pf-node"
                data-pos="left-top"
                id="pf-node-solar"
                data-active={solarFlowActive ? 'true' : 'false'}
              >
                <span className="pf-node-icon" aria-hidden>
                  ☀️
                </span>
                <span className="pf-node-label">{t('nodeSolar')}</span>
                <span className="pf-node-value" id="pf-val-solar">
                  {formatPower(displaySolarW, t, bcp47)}
                </span>
              </div>
              <button
                type="button"
                className="pf-node"
                data-pos="left-center"
                id="pf-node-grid"
                data-active={hasFlow && gridFlowActive ? 'true' : 'false'}
              >
                <span className="pf-node-icon" aria-hidden>
                  ⚡
                </span>
                <span className="pf-node-label">{t('nodeGrid')}</span>
                <span className="pf-node-value" id="pf-val-grid">
                  {gridSelling
                    ? `↓ ${formatPower(Math.abs(effectiveGridW), t, bcp47)}`
                    : formatPower(effectiveGridW, t, bcp47)}
                </span>
                <span className="pf-ess-status" id="pf-grid-selling" hidden={!gridSelling}>
                  {t('gridSelling')}
                </span>
              </button>
              <div
                className="pf-node"
                data-pos="left-bottom"
                id="pf-node-load"
                data-active={loadFlowActive ? 'true' : 'false'}
              >
                <span className="pf-node-icon" aria-hidden>
                  🏠
                </span>
                <span className="pf-node-label">{t('nodeLoad')}</span>
                <span className="pf-node-value" id="pf-val-load">
                  {!selInverterSn
                    ? formatPower(null, t, bcp47)
                    : deyeLiveLoading
                      ? '…'
                      : displayLoadW != null
                        ? formatPower(displayLoadW, t, bcp47)
                        : formatPower(null, t, bcp47)}
                </span>
              </div>
              <div className="pf-hub" id="pf-hub">
                <a
                  className={
                    hubLogoInboundFlow ? 'pf-hub-brand pf-hub-brand--flow-ends-here' : 'pf-hub-brand'
                  }
                  href={SITE_220KM_HOME}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={t('hubBrandLinkAria')}
                >
                  <img
                    className="pf-hub-logo"
                    src={`${qrBase}/static/220-km-logo.svg`}
                    alt=""
                    width="40"
                    height="40"
                    loading="lazy"
                    decoding="async"
                  />
                </a>
                <span className="pf-hub-label">{t('hubLabel')}</span>
              </div>
              <button
                type="button"
                className="pf-node"
                data-pos="right-top"
                id="pf-node-ess"
                data-active={essActive ? 'true' : 'false'}
              >
                <span className="pf-node-icon" id="pf-ess-icon" aria-hidden>
                  {displayEssCharging ? '🔌' : '🔋'}
                </span>
                <span className="pf-node-label">{t('nodeEss')}</span>
                <span className="pf-node-value" id="pf-val-ess">
                  {formatPower(Math.abs(displayEssW), t, bcp47)}
                </span>
                {selInverterSn &&
                essSocPercent != null &&
                Number.isFinite(essSocPercent) ? (
                  <span className="pf-node-sub pf-ess-soc" id="pf-ess-soc">
                    {t('essSoc', {
                      value: inverterSocFmt.format(essSocPercent),
                    })}
                  </span>
                ) : null}
                {essSocPending ? (
                  <span className="pf-node-sub pf-ess-soc pf-ess-soc-loading" id="pf-ess-soc-loading">
                    {t('essSocLoading')}
                  </span>
                ) : null}
              </button>
              <a
                className="pf-node"
                data-pos="right-center"
                id="pf-node-miner"
                href={BINANCE_MINER_URL}
                target="_blank"
                rel="noopener noreferrer"
                data-active={hasFlow && minerW > 0 ? 'true' : 'false'}
              >
                <span className="pf-node-icon" aria-hidden>
                  💠
                </span>
                <span className="pf-node-label" id="pf-miner-label">
                  {minerLabel}
                </span>
                <span className="pf-node-value" id="pf-val-miner">
                  {formatPower(minerW, t, bcp47)}
                </span>
                <div className="pf-node-sub" id="pf-miner-usdt">
                  {usdt ? `${usdt} ${t('usdtSuffix')}` : ''}
                </div>
                <div className="pf-node-meta" id="pf-miner-tariff">
                  {tf != null && Number.isFinite(tf)
                    ? t('tariffKwh', {
                        value: new Intl.NumberFormat(bcp47, {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        }).format(Math.max(0, tf)),
                      })
                    : ''}
                </div>
              </a>
              {showEvAggregate ? (
                <a
                  className="pf-node"
                  data-pos="right-bottom"
                  id="pf-node-ev"
                  href={EV_LIST_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-active={evFlowActive ? 'true' : 'false'}
                >
                  <span className="pf-node-icon" aria-hidden>
                    🚗
                  </span>
                  <span className="pf-node-label">{t('nodeEv')}</span>
                  <span className="pf-node-value" id="pf-val-ev">
                    {evBusy ? '…' : formatPower(consumptionW, t, bcp47)}
                  </span>
                </a>
              ) : (
                <div
                  className="pf-node pf-node-ev-disabled"
                  data-pos="right-bottom"
                  id="pf-node-ev"
                  data-active="false"
                  title={t('evHiddenByInverter')}
                >
                  <span className="pf-node-icon" aria-hidden>
                    🚗
                  </span>
                  <span className="pf-node-label">{t('nodeEv')}</span>
                  <span className="pf-node-value" id="pf-val-ev">
                    {formatPower(null, t, bcp47)}
                  </span>
                </div>
              )}
            </div>
          </div>
          <div id="pf-error" className="pf-error" hidden={!loadError}>
            {loadError}
          </div>
        </div>

        <aside className="pf-ukraine-qr" aria-label={t('qrAsideAria')}>
          <a
            className="pf-ukraine-qr-link"
            href="https://u24.gov.ua/"
            target="_blank"
            rel="noopener noreferrer"
          >
            <img
              className="pf-ukraine-qr-img"
              src={`${qrBase}/static/power-flow/protect-ukraine-qr.png`}
              width={120}
              height={120}
              alt={t('qrImageAlt')}
              decoding="async"
            />
            <span className="pf-ukraine-qr-caption">{t('qrCaption')}</span>
          </a>
        </aside>

        <section className="pf-dam-section" aria-label={t('damChartHeading')}>
          <DamChartPanel variant="embedded" t={t} getBcp47Locale={getBcp47Locale} chartHeight={320} />
        </section>
      </div>
    </div>
  );
}
