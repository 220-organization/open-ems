import { useCallback, useEffect, useMemo, useState } from 'react';
import { readCachedInverterPin, rememberInverterPin } from './deyeInverterPinCache';

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  if (!base) return path;
  return `${base}${path}`;
}

function roiConfigKey(deviceSn) {
  return `pf-roi-config-v1-${String(deviceSn || '').trim()}`;
}

/** Local calendar YYYY-MM-DD (browser timezone). */
function localYmdToday() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Kyiv calendar YYYY-MM-DD for an ISO instant (matches ROI period display). */
function isoToKyivYmd(startIso) {
  try {
    const d = new Date(startIso);
    if (Number.isNaN(d.getTime())) return localYmdToday();
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Europe/Kyiv',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(d);
    const y = parts.find(p => p.type === 'year')?.value;
    const mo = parts.find(p => p.type === 'month')?.value;
    const day = parts.find(p => p.type === 'day')?.value;
    if (y && mo && day) return `${y}-${mo}-${day}`;
  } catch {
    /* ignore */
  }
  return localYmdToday();
}

const NBU_USD_URL = 'https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=USD&json';
const USD_UAH_FALLBACK = 42;
const MIN_ELAPSED_MS_FOR_ROI = 6 * 60 * 60 * 1000;

async function fetchUahPerOneUsd() {
  try {
    const r = await fetch(NBU_USD_URL, { cache: 'no-store' });
    if (!r.ok) return null;
    const data = await r.json();
    const row = Array.isArray(data) ? data[0] : null;
    const rate = row && row.rate != null ? Number(String(row.rate).replace(',', '.')) : null;
    if (rate != null && Number.isFinite(rate) && rate > 0) return rate;
  } catch {
    /* ignore */
  }
  return null;
}

function readCachedUahPerUsd() {
  try {
    const raw = sessionStorage.getItem('pf-nbu-usd-rate');
    if (!raw) return null;
    const o = JSON.parse(raw);
    const day = o?.day;
    const rate = o?.rate;
    if (
      day !== new Date().toISOString().slice(0, 10) ||
      rate == null ||
      !Number.isFinite(Number(rate)) ||
      Number(rate) <= 0
    ) {
      return null;
    }
    return Number(rate);
  } catch {
    return null;
  }
}

function writeCachedUahPerUsd(rate) {
  try {
    sessionStorage.setItem('pf-nbu-usd-rate', JSON.stringify({ day: new Date().toISOString().slice(0, 10), rate }));
  } catch {
    /* ignore */
  }
}

export default function RoiStackStatistics({
  t,
  bcp47,
  selInverterSn,
  inverterHeaderOk,
  inverterListPending = false,
  pinRequired,
  cachedPin,
  pinCacheBust,
  onPinRemembered,
  onRoiCapexSaved,
}) {
  const [setupOpen, setSetupOpen] = useState(false);
  const [capexInput, setCapexInput] = useState('');
  const [startDateInput, setStartDateInput] = useState(() => localYmdToday());
  const [pinInput, setPinInput] = useState('');
  const [setupPinError, setSetupPinError] = useState('');
  const [config, setConfig] = useState(null);
  const [roiStats, setRoiStats] = useState({
    loading: false,
    error: false,
    totalPvKwh: null,
    totalConsumptionKwh: null,
    totalValueUah: null,
    effectiveRateUahPerKwh: null,
    missingDamSlices: 0,
    detail: null,
    previousMonth: null,
  });
  const [uahPerUsd, setUahPerUsd] = useState(() => readCachedUahPerUsd() || USD_UAH_FALLBACK);

  const sn = String(selInverterSn || '').trim();

  /** POST CAPEX from legacy localStorage when PIN is available — does not GET /roi-settings (avoids overwriting CAPEX). */
  const tryMigrateRoiFromLocalStorage = useCallback(async () => {
    if (!sn) return false;
    try {
      const raw = localStorage.getItem(roiConfigKey(sn));
      if (!raw) return false;
      const o = JSON.parse(raw);
      const capex = o?.capexUsd;
      if (!pinRequired || capex == null || !Number.isFinite(Number(capex)) || Number(capex) <= 0) {
        return false;
      }
      const migPin = readCachedInverterPin(sn);
      if (!migPin?.trim()) return false;
      const pr = await fetch(apiUrl('/api/deye/roi-settings'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          deviceSn: sn,
          capexUsd: Number(capex),
          pin: migPin.trim(),
          periodStartDate: localYmdToday(),
        }),
      });
      const pd = await pr.json().catch(() => ({}));
      if (pr.ok && pd.ok && pd.periodStartIso) {
        try {
          localStorage.removeItem(roiConfigKey(sn));
        } catch {
          /* ignore */
        }
        setConfig({ capexUsd: Number(capex), startIso: String(pd.periodStartIso) });
        return true;
      }
    } catch {
      /* ignore */
    }
    return false;
  }, [sn, pinRequired]);

  const loadConfigFromServer = useCallback(async () => {
    if (!sn) {
      setConfig(null);
      return;
    }
    try {
      const q = new URLSearchParams({ deviceSn: sn });
      const r = await fetch(apiUrl(`/api/deye/roi-settings?${q}`), { cache: 'no-store' });
      const data = await r.json().catch(() => ({}));
      if (r.ok && data.ok && data.configured !== false && data.hasRow && data.capexUsd != null && data.periodStartIso) {
        setConfig({ capexUsd: Number(data.capexUsd), startIso: String(data.periodStartIso) });
        return;
      }
      if (await tryMigrateRoiFromLocalStorage()) return;
      try {
        const raw = localStorage.getItem(roiConfigKey(sn));
        if (raw) {
          const r2 = await fetch(apiUrl(`/api/deye/roi-settings?${q}`), { cache: 'no-store' });
          const d2 = await r2.json().catch(() => ({}));
          if (r2.ok && d2.hasRow && d2.capexUsd != null && d2.periodStartIso) {
            setConfig({ capexUsd: Number(d2.capexUsd), startIso: String(d2.periodStartIso) });
            return;
          }
        }
      } catch {
        /* ignore */
      }
      setConfig(null);
    } catch {
      setConfig(null);
    }
  }, [sn, tryMigrateRoiFromLocalStorage]);

  useEffect(() => {
    void loadConfigFromServer();
  }, [loadConfigFromServer]);

  /** After PIN is remembered (bust &gt; 0), migrate localStorage only — do not re-fetch GET /roi-settings (would overwrite CAPEX). */
  useEffect(() => {
    if (pinCacheBust === 0) return;
    void tryMigrateRoiFromLocalStorage();
  }, [tryMigrateRoiFromLocalStorage, pinCacheBust]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cached = readCachedUahPerUsd();
      if (cached != null) {
        setUahPerUsd(cached);
        return;
      }
      const r = await fetchUahPerOneUsd();
      if (cancelled) return;
      if (r != null) {
        writeCachedUahPerUsd(r);
        setUahPerUsd(r);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!config?.startIso || !sn) {
      setRoiStats(s => ({
        ...s,
        loading: false,
        totalPvKwh: null,
        totalConsumptionKwh: null,
        totalValueUah: null,
        effectiveRateUahPerKwh: null,
        detail: null,
        previousMonth: null,
      }));
      return undefined;
    }

    let cancelled = false;

    const load = async () => {
      setRoiStats(s => ({ ...s, loading: true, error: false }));
      try {
        const q = new URLSearchParams({ deviceSn: sn, startIso: config.startIso });
        const r = await fetch(apiUrl(`/api/deye/roi-stats?${q}`), { cache: 'no-store' });
        const data = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (!r.ok || !data?.ok) {
          setRoiStats({
            loading: false,
            error: true,
            totalPvKwh: null,
            totalConsumptionKwh: null,
            totalValueUah: null,
            effectiveRateUahPerKwh: null,
            missingDamSlices: 0,
            detail: data?.detail || 'request_failed',
            previousMonth: null,
          });
          return;
        }
        setRoiStats({
          loading: false,
          error: false,
          totalPvKwh: data.totalPvKwh != null && Number.isFinite(Number(data.totalPvKwh)) ? Number(data.totalPvKwh) : 0,
          totalConsumptionKwh:
            data.totalConsumptionKwh != null && Number.isFinite(Number(data.totalConsumptionKwh))
              ? Number(data.totalConsumptionKwh)
              : null,
          totalValueUah:
            data.totalValueUah != null && Number.isFinite(Number(data.totalValueUah)) ? Number(data.totalValueUah) : 0,
          effectiveRateUahPerKwh:
            data.effectiveRateUahPerKwh != null && Number.isFinite(Number(data.effectiveRateUahPerKwh))
              ? Number(data.effectiveRateUahPerKwh)
              : null,
          missingDamSlices:
            data.missingDamSlices != null && Number.isFinite(Number(data.missingDamSlices))
              ? Number(data.missingDamSlices)
              : 0,
          detail: data.detail ?? null,
          previousMonth: data.previousMonth && typeof data.previousMonth === 'object' ? data.previousMonth : null,
        });
      } catch {
        if (!cancelled) {
          setRoiStats({
            loading: false,
            error: true,
            totalPvKwh: null,
            totalConsumptionKwh: null,
            totalValueUah: null,
            effectiveRateUahPerKwh: null,
            missingDamSlices: 0,
            detail: 'network',
            previousMonth: null,
          });
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [config?.startIso, sn]);

  const fmtUsd = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 0,
        minimumFractionDigits: 0,
      }),
    [bcp47]
  );

  const fmtKwh = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 1,
      }),
    [bcp47]
  );

  const fmtRoi = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 1,
        maximumFractionDigits: 2,
      }),
    [bcp47]
  );

  const fmtUah = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }),
    [bcp47]
  );

  const startDateLabel = useMemo(() => {
    if (!config?.startIso) return '';
    try {
      const d = new Date(config.startIso);
      if (Number.isNaN(d.getTime())) return '';
      return new Intl.DateTimeFormat(bcp47, {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        timeZone: 'Europe/Kyiv',
      }).format(d);
    } catch {
      return '';
    }
  }, [bcp47, config?.startIso]);

  const elapsedMs = useMemo(() => {
    if (!config?.startIso) return 0;
    try {
      const t0 = new Date(config.startIso).getTime();
      if (!Number.isFinite(t0)) return 0;
      return Math.max(0, Date.now() - t0);
    } catch {
      return 0;
    }
  }, [config?.startIso]);

  const elapsedYears = elapsedMs > 0 ? elapsedMs / (365.25 * 24 * 60 * 60 * 1000) : 0;

  const consumptionKwh =
    roiStats.totalConsumptionKwh != null && Number.isFinite(Number(roiStats.totalConsumptionKwh))
      ? Number(roiStats.totalConsumptionKwh)
      : roiStats.totalPvKwh != null && Number.isFinite(Number(roiStats.totalPvKwh))
        ? Number(roiStats.totalPvKwh)
        : 0;

  const totalValueUah = roiStats.totalValueUah != null ? roiStats.totalValueUah : 0;

  const annualValueUah = elapsedYears > 0 ? totalValueUah / elapsedYears : 0;
  const annualSavingsUsd =
    uahPerUsd > 0 && Number.isFinite(annualValueUah) && annualValueUah > 0 ? annualValueUah / uahPerUsd : null;

  const roiYears =
    config &&
    annualSavingsUsd != null &&
    annualSavingsUsd > 0 &&
    config.capexUsd > 0 &&
    elapsedMs >= MIN_ELAPSED_MS_FOR_ROI
      ? config.capexUsd / annualSavingsUsd
      : null;

  const pm = roiStats.previousMonth;

  const roiYearsPrevMonth = useMemo(() => {
    if (!config || !pm || pm.detail != null) return null;
    const days = pm.daysInMonth;
    const tv = pm.totalValueUah;
    if (
      days == null ||
      days <= 0 ||
      tv == null ||
      !Number.isFinite(Number(tv)) ||
      Number(tv) <= 0 ||
      uahPerUsd <= 0 ||
      !Number.isFinite(config.capexUsd) ||
      config.capexUsd <= 0
    ) {
      return null;
    }
    const annualValueUah = (Number(tv) * 365.25) / Number(days);
    const annualSavingsUsd = annualValueUah / uahPerUsd;
    if (!annualSavingsUsd || annualSavingsUsd <= 0) return null;
    return config.capexUsd / annualSavingsUsd;
  }, [config, pm, uahPerUsd]);

  const fmtDeltaPct = useMemo(
    () =>
      new Intl.NumberFormat(bcp47, {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }),
    [bcp47]
  );

  /** % change of payback years: last full month vs whole ROI period (same CAPEX). */
  const roiPrevMonthDeltaPct = useMemo(() => {
    if (
      roiYears == null ||
      !Number.isFinite(roiYears) ||
      roiYears <= 0 ||
      roiYearsPrevMonth == null ||
      !Number.isFinite(roiYearsPrevMonth)
    ) {
      return null;
    }
    return ((roiYearsPrevMonth - roiYears) / roiYears) * 100;
  }, [roiYears, roiYearsPrevMonth]);

  const closeSetupModal = useCallback(() => {
    setSetupOpen(false);
    setSetupPinError('');
  }, []);

  const onOpenSetup = () => {
    setCapexInput(config ? String(Math.round(config.capexUsd)) : '');
    setStartDateInput(config?.startIso ? isoToKyivYmd(config.startIso) : localYmdToday());
    setPinInput(String(cachedPin || '').trim());
    setSetupPinError('');
    setSetupOpen(true);
  };

  const onSaveSetup = async () => {
    const n = Number(String(capexInput).replace(',', '.').trim());
    if (!sn || !Number.isFinite(n) || n <= 0) return;
    const pin = String(pinInput || cachedPin || '').trim();
    if (!pin) {
      setSetupPinError(t('deyeWritePinMissing'));
      return;
    }
    setSetupPinError('');
    const ymd = String(startDateInput || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(ymd)) {
      setSetupPinError(t('roiStartDateInvalid'));
      return;
    }
    try {
      const r = await fetch(apiUrl('/api/deye/roi-settings'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deviceSn: sn, capexUsd: n, pin, periodStartDate: ymd }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok || !data.periodStartIso) {
        const detail = data?.detail;
        setSetupPinError(
          typeof detail === 'string' && detail.trim()
            ? detail
            : r.status === 403
              ? t('roiSetupPinForbidden')
              : t('roiSetupSaveError')
        );
        return;
      }
      try {
        rememberInverterPin(sn, pin);
        onPinRemembered?.();
      } catch {
        /* ignore */
      }
      try {
        localStorage.removeItem(roiConfigKey(sn));
      } catch {
        /* ignore */
      }
      setConfig({ capexUsd: n, startIso: String(data.periodStartIso) });
      closeSetupModal();
      onRoiCapexSaved?.();
    } catch {
      setSetupPinError(t('roiSetupSaveError'));
    }
  };

  if (inverterListPending) {
    return (
      <div className="pf-roi-stack pf-roi-stack--list-pending" aria-busy="true">
        <div className="pf-roi-card pf-roi-card--skeleton" aria-hidden>
          <div className="pf-roi-meta">
            <div className="pf-roi-meta-col">
              <span className="pf-skeleton-line pf-skeleton-line--long" />
              <span className="pf-skeleton-line pf-skeleton-line--medium" />
            </div>
            <div className="pf-roi-meta-col pf-roi-meta-right">
              <span className="pf-skeleton-line pf-skeleton-line--long" />
              <span className="pf-skeleton-line pf-skeleton-line--medium" />
            </div>
          </div>
          <div className="pf-roi-stack-bar">
            <div className="pf-roi-stack-seg pf-roi-stack-seg--skeleton" />
            <div className="pf-roi-stack-seg pf-roi-stack-seg--skeleton" />
            <div className="pf-roi-stack-seg pf-roi-stack-seg--skeleton" />
            <div className="pf-roi-stack-seg pf-roi-stack-seg--skeleton" />
          </div>
        </div>
      </div>
    );
  }

  const showPanel = inverterHeaderOk && sn && (pinRequired || config);
  if (!showPanel) return null;

  const samplesHint =
    roiStats.detail === 'insufficient_load_samples'
      ? t('roiLoadSamplesHint')
      : roiStats.detail === 'insufficient_samples' || roiStats.detail === 'no_samples'
        ? t('roiSamplesHint')
        : null;

  return (
    <div className="pf-roi-stack">
      {pinRequired ? (
        <button type="button" className="pf-add-deye-btn pf-roi-setup-btn" onClick={onOpenSetup}>
          {t('roiSetupButton')}
        </button>
      ) : null}

      {config ? (
        <div className="pf-roi-card">
          <div className="pf-roi-meta">
            <div className="pf-roi-meta-col">
              <span className="pf-roi-meta-line">
                {t('roiCapexLabel')}: {fmtUsd.format(config.capexUsd)}
              </span>
              <span className="pf-roi-meta-line pf-roi-meta-muted">
                {t('roiStartLabel')}: {startDateLabel || '—'}
              </span>
            </div>
            <div className="pf-roi-meta-col pf-roi-meta-right">
              <span className="pf-roi-meta-line">
                <span className="pf-roi-years-neon">
                  {t('roiYearsLabel')}:{' '}
                  {roiStats.loading
                    ? '…'
                    : roiYears != null && Number.isFinite(roiYears)
                      ? (
                          <>
                            {fmtRoi.format(roiYears)} {t('roiYearsUnit')}
                          </>
                        )
                      : '—'}
                </span>
                {!roiStats.loading &&
                roiPrevMonthDeltaPct != null &&
                Number.isFinite(roiPrevMonthDeltaPct) &&
                roiYearsPrevMonth != null &&
                !roiStats.error ? (
                  <span className="pf-roi-prev-month-delta">
                    {' '}
                    {t('roiPrevMonthDeltaPct', {
                      delta:
                        roiPrevMonthDeltaPct >= 0
                          ? `+${fmtDeltaPct.format(roiPrevMonthDeltaPct)}`
                          : fmtDeltaPct.format(roiPrevMonthDeltaPct),
                    })}
                  </span>
                ) : null}
              </span>
              <span className="pf-roi-meta-line pf-roi-meta-muted">
                {roiStats.loading
                  ? '…'
                  : roiStats.error
                    ? '—'
                    : t('roiArbitrageTotalLine', {
                        total: fmtUah.format(totalValueUah),
                        unit: t('roiValueUahUnit'),
                      })}
              </span>
            </div>
          </div>

          {elapsedMs < MIN_ELAPSED_MS_FOR_ROI ? <p className="pf-roi-hint">{t('roiCollectingHint')}</p> : null}
          {samplesHint ? <p className="pf-roi-hint">{samplesHint}</p> : null}
          {roiStats.missingDamSlices > 0 ? (
            <p className="pf-roi-hint">{t('roiMissingDamHint', { n: roiStats.missingDamSlices })}</p>
          ) : null}

          <div className="pf-roi-stack-bar" role="img" aria-label={t('roiStackAria')}>
            <div className="pf-roi-stack-seg pf-roi-stack-seg--load pf-roi-stack-seg--head-inline">
              <span className="pf-roi-stack-seg-title">{t('roiCatLoad')}</span>
              <span className="pf-roi-stack-seg-sub">
                {roiStats.loading ? '…' : `${fmtKwh.format(consumptionKwh)} kWh`}
              </span>
            </div>
            <div className="pf-roi-stack-seg pf-roi-stack-seg--placeholder">
              <span className="pf-roi-stack-seg-title">{t('roiCatEv')}</span>
              <span className="pf-roi-stack-seg-sub">{t('roiUnderDevelopment')}</span>
            </div>
            <div className="pf-roi-stack-seg pf-roi-stack-seg--placeholder">
              <span className="pf-roi-stack-seg-title">{t('roiCatDam')}</span>
              <span className="pf-roi-stack-seg-sub">{t('roiUnderDevelopment')}</span>
            </div>
            <div className="pf-roi-stack-seg pf-roi-stack-seg--placeholder">
              <span className="pf-roi-stack-seg-title">{t('roiCatMining')}</span>
              <span className="pf-roi-stack-seg-sub">{t('roiUnderDevelopment')}</span>
            </div>
          </div>
        </div>
      ) : null}

      {setupOpen ? (
        <div className="pf-messenger-scrim" role="presentation" onClick={closeSetupModal}>
          <div
            className="pf-messenger-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="pf-roi-setup-title"
            onClick={e => e.stopPropagation()}
          >
            <div className="pf-messenger-panel">
              <h2 id="pf-roi-setup-title" className="pf-messenger-title">
                {t('roiSetupTitle')}
              </h2>
              <label className="pf-roi-modal-label" htmlFor="pf-roi-capex">
                {t('roiCapexPrompt')}
              </label>
              <input
                id="pf-roi-capex"
                type="number"
                min="1"
                step="1"
                className="pf-roi-modal-input"
                value={capexInput}
                onChange={e => setCapexInput(e.target.value)}
                autoComplete="off"
              />
              <label className="pf-roi-modal-label" htmlFor="pf-roi-start-date">
                {t('roiStartDatePrompt')}
              </label>
              <input
                id="pf-roi-start-date"
                type="date"
                className="pf-roi-modal-input"
                value={startDateInput}
                onChange={e => {
                  setStartDateInput(e.target.value);
                  setSetupPinError('');
                }}
                autoComplete="off"
              />
              <label className="pf-roi-modal-label" htmlFor="pf-roi-pin">
                {t('deyeWritePinLabel')}
              </label>
              <input
                id="pf-roi-pin"
                type="password"
                inputMode="numeric"
                autoComplete="off"
                className="pf-roi-modal-input"
                value={pinInput}
                onChange={e => {
                  setPinInput(e.target.value);
                  setSetupPinError('');
                }}
              />
              {setupPinError ? <p className="pf-roi-modal-error">{setupPinError}</p> : null}
              <div className="pf-roi-modal-actions">
                <button type="button" className="pf-roi-modal-btn pf-roi-modal-btn--primary" onClick={onSaveSetup}>
                  {t('roiSetupSave')}
                </button>
                <button type="button" className="pf-roi-modal-btn" onClick={closeSetupModal}>
                  {t('roiSetupCancel')}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
