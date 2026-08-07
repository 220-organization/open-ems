import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BUSINESS_TYPES,
  CUSTOM_PRESET_ID,
  DISCOUNT_UNITS,
  INVERTERS,
  BATTERY_MODELS,
  PRESETS,
  allowedKwhOptions,
  buildCustomBom,
  computeBiomSavings,
  kwhRangeLabel,
  unitPriceUsd,
} from './orderBess/presets';
import { downloadOrderBessOfferPng } from './orderBess/offerPdf';
import { buildB2bTelegramUrl, buildB2bWhatsAppUrl } from './messengerContactUrls';
import SharePageModal from './SharePageModal';
import { buildSharePageModalPayload } from './sharePageQr';
import './order-bess.css';

const BESS_OFFER_HASHTAG = '#OrderBessOffer';
const BESS_DISCOUNT_HASHTAG = '#OrderBessDiscount';

const VALID_BIZ = new Set(BUSINESS_TYPES.map(b => b.id));
const VALID_PRESETS = new Set([...PRESETS.map(p => p.id), CUSTOM_PRESET_ID]);

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  return base ? `${base}${path}` : path;
}

function fmtUsd(n) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtUah(n) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function normArticle(a) {
  return String(a || '')
    .toUpperCase()
    .replace(/\s+/g, '');
}

function findItem(items, article) {
  const key = normArticle(article);
  return (items || []).find(it => normArticle(it.article) === key) || null;
}

function findBatteryKey(raw) {
  const key = normArticle(raw);
  return Object.keys(BATTERY_MODELS).find(a => normArticle(a) === key) || null;
}

function readOrderBessFromUrl() {
  if (typeof window === 'undefined') return {};
  try {
    const u = new URLSearchParams(window.location.search);
    const out = {};
    const biz = (u.get('biz') || '').trim();
    if (VALID_BIZ.has(biz)) out.businessType = biz;
    const preset = (u.get('preset') || '').trim();
    if (VALID_PRESETS.has(preset)) out.presetId = preset;
    const inv = (u.get('inv') || '').trim();
    if (INVERTERS[inv]) out.customInv = inv;
    const bat = findBatteryKey(u.get('bat') || '');
    if (bat) out.customBat = bat;
    const kwhRaw = u.get('kwh');
    if (kwhRaw != null && kwhRaw !== '') {
      const kwh = Number(kwhRaw);
      if (Number.isFinite(kwh) && kwh > 0) out.customKwh = kwh;
    }
    const unitsRaw = u.get('units');
    if (unitsRaw != null && unitsRaw !== '') {
      const units = Number.parseInt(unitsRaw, 10);
      if (DISCOUNT_UNITS.includes(units)) out.discountUnits = units;
    }
    return out;
  } catch {
    return {};
  }
}

function writeOrderBessToUrl(state) {
  if (typeof window === 'undefined') return;
  try {
    const u = new URL(window.location.href);
    u.searchParams.set('biz', state.businessType);
    u.searchParams.set('preset', state.presetId);
    if (state.presetId === CUSTOM_PRESET_ID) {
      u.searchParams.set('inv', state.customInv);
      u.searchParams.set('bat', state.customBat);
      u.searchParams.set('kwh', String(state.customKwh));
    } else {
      u.searchParams.delete('inv');
      u.searchParams.delete('bat');
      u.searchParams.delete('kwh');
    }
    u.searchParams.set('units', String(state.discountUnits));
    const next = `${u.pathname}${u.search}${u.hash}`;
    const cur = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next !== cur) window.history.replaceState({}, '', next);
  } catch {
    /* ignore */
  }
}

function ShareIcon({ className }) {
  return (
    <svg
      className={className}
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </svg>
  );
}

export default function OrderBessPage({ t }) {
  const initialUrl = useMemo(() => readOrderBessFromUrl(), []);

  const [businessType, setBusinessType] = useState(initialUrl.businessType || 'cash');
  const [presetId, setPresetId] = useState(initialUrl.presetId || 'hv-50-60');
  const [priceList, setPriceList] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);

  // Custom builder state
  const [customInv, setCustomInv] = useState(initialUrl.customInv || 'SUN-50K-SG01HP3-EU-BM4');
  const [customBat, setCustomBat] = useState(initialUrl.customBat || 'BAHV-100512-LFP');
  const [customKwh, setCustomKwh] = useState(
    initialUrl.customKwh != null ? initialUrl.customKwh : 61.44
  );

  const [discountUnits, setDiscountUnits] = useState(initialUrl.discountUnits || 2);
  const [contactName, setContactName] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [contactFormError, setContactFormError] = useState('');
  const [discountStatus, setDiscountStatus] = useState(''); // '', 'ok', 'err'
  const [discountBusy, setDiscountBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [contactBusy, setContactBusy] = useState(''); // '' | 'offer:telegram' | …
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareModalUrl, setShareModalUrl] = useState('');
  const [shareModalCopied, setShareModalCopied] = useState(false);
  const [shareModalCopyFailed, setShareModalCopyFailed] = useState(false);

  const loadPrices = useCallback(async (refresh = false) => {
    setLoading(true);
    setLoadError('');
    try {
      const q = refresh ? '?refresh=true' : '';
      const res = await fetch(apiUrl(`/api/bess-order/price-list${q}`), { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPriceList(data);
    } catch (e) {
      setLoadError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPrices(false);
  }, [loadPrices]);

  useEffect(() => {
    writeOrderBessToUrl({
      businessType,
      presetId,
      customInv,
      customBat,
      customKwh,
      discountUnits,
    });
  }, [businessType, presetId, customInv, customBat, customKwh, discountUnits]);

  const handleShare = useCallback(async () => {
    writeOrderBessToUrl({
      businessType,
      presetId,
      customInv,
      customBat,
      customKwh,
      discountUnits,
    });
    const payload = await buildSharePageModalPayload();
    if (!payload) return;
    setShareModalUrl(payload.url);
    setShareModalCopied(payload.copied);
    setShareModalCopyFailed(payload.copyFailed);
    setShareModalOpen(true);
  }, [businessType, presetId, customInv, customBat, customKwh, discountUnits]);

  const invMeta = INVERTERS[customInv];
  const voltageClass = invMeta?.voltage === 'hv' ? 'hv' : 'lv';

  const batteryChoices = useMemo(() => {
    return Object.entries(BATTERY_MODELS)
      .filter(([, m]) => {
        if (voltageClass === 'lv') return m.voltage === 'lv';
        return m.voltage === 'hv1' || m.voltage === 'hv3';
      })
      .map(([article, m]) => ({ article, ...m }));
  }, [voltageClass]);

  useEffect(() => {
    // Keep battery model compatible when inverter voltage class changes
    if (!batteryChoices.some(b => b.article === customBat)) {
      setCustomBat(batteryChoices[0]?.article || '');
    }
  }, [batteryChoices, customBat]);

  const kwhOptions = useMemo(() => {
    if (!customBat) return [];
    return allowedKwhOptions(customBat, voltageClass);
  }, [customBat, voltageClass]);

  useEffect(() => {
    if (!kwhOptions.length) return;
    if (!kwhOptions.some(o => Math.abs(o.kwh - customKwh) < 0.01)) {
      setCustomKwh(kwhOptions[0].kwh);
    }
  }, [kwhOptions, customKwh]);

  const activeBom = useMemo(() => {
    if (presetId === CUSTOM_PRESET_ID) {
      return buildCustomBom(customInv, customBat, customKwh);
    }
    const p = PRESETS.find(x => x.id === presetId);
    if (!p) return { lines: [], kwh: 0, kw: 0, voltageClass: '' };
    return { lines: p.lines, kwh: p.kwh, kw: p.kw, voltageClass: p.group, meta: {} };
  }, [presetId, customInv, customBat, customKwh]);

  const pricedLines = useMemo(() => {
    const items = priceList?.items || [];
    return (activeBom.lines || []).map(l => {
      const item = findItem(items, l.article);
      const unit = unitPriceUsd(item, businessType);
      const lineTotal = unit == null ? null : Math.round(unit * l.qty * 100) / 100;
      const availability =
        businessType === 'cash'
          ? item?.availabilityInstaller || item?.availability || ''
          : item?.availability || item?.availabilityInstaller || '';
      return {
        ...l,
        name: item?.name || l.article,
        brand: item?.brand || '',
        code: item?.code || '',
        unit,
        lineTotal,
        availability,
        missing: !item || unit == null,
      };
    });
  }, [activeBom, priceList, businessType]);

  const totalUsd = useMemo(() => {
    if (pricedLines.some(l => l.lineTotal == null)) return null;
    return Math.round(pricedLines.reduce((s, l) => s + (l.lineTotal || 0), 0) * 100) / 100;
  }, [pricedLines]);

  const fx = priceList?.fxRate || 45.3;
  const totalUah = totalUsd == null ? null : Math.round(totalUsd * fx * 100) / 100;

  const bizMeta = BUSINESS_TYPES.find(b => b.id === businessType);
  const priceColLabel = t(bizMeta?.priceLabelKey || 'orderBessPriceUsd');

  const offerTitle = useMemo(() => {
    const kw = activeBom.kw || 0;
    const kwh = activeBom.kwh || 0;
    return t('orderBessOfferTitle', { kw, kwh: Math.round(kwh) });
  }, [activeBom, t]);

  const biomSavings = useMemo(() => {
    if (presetId !== CUSTOM_PRESET_ID) return null;
    return computeBiomSavings({
      inverterArticle: customInv,
      batteryArticle: customBat,
      targetKwh: customKwh,
      businessType,
      priceItems: priceList?.items || [],
      findItemFn: findItem,
    });
  }, [presetId, customInv, customBat, customKwh, businessType, priceList]);

  const kitPayload = useMemo(
    () => ({
      kw: activeBom.kw,
      kwh: activeBom.kwh,
      ...(presetId === CUSTOM_PRESET_ID
        ? { inv: customInv, bat: customBat, inverter: customInv, battery: customBat }
        : {}),
      lines: pricedLines.map(l => ({
        article: l.article,
        qty: l.qty,
        unit: l.unit,
        lineTotal: l.lineTotal,
      })),
    }),
    [activeBom, pricedLines, presetId, customInv, customBat]
  );

  const orderBessPageUrl = useMemo(() => {
    if (typeof window === 'undefined') return '';
    try {
      return window.location.href;
    } catch {
      return '';
    }
  }, [businessType, presetId, customInv, customBat, customKwh, discountUnits]);

  const trimmedName = contactName.trim();
  const trimmedPhone = contactPhone.trim();
  const canContact = trimmedName.length >= 1 && trimmedPhone.length >= 5;

  const buildContactMessage = intent => {
    const isDiscount = intent === 'discount';
    const pageLink =
      typeof window !== 'undefined' ? window.location.href : orderBessPageUrl;
    const lines = [
      t(isDiscount ? 'orderBessContactMessageDiscountIntro' : 'orderBessContactMessageOfferIntro'),
      `${t('orderBessContactName')}: ${trimmedName}`,
      `${t('orderBessContactPhone')}: ${trimmedPhone}`,
      `${t('orderBessSummaryKit')}: ${activeBom.kw} кВт + ${activeBom.kwh} кВт·год`,
      totalUsd == null
        ? null
        : isDiscount
          ? `${t('orderBessSummaryTotal')}: $${fmtUsd(totalUsd)} × ${discountUnits} = $${fmtUsd(totalUsd * discountUnits)} (${priceColLabel})`
          : `${t('orderBessSummaryTotal')}: $${fmtUsd(totalUsd)} (${priceColLabel})`,
      isDiscount ? `${t('orderBessDiscountUnits')}: ${discountUnits}` : null,
      pageLink || null,
      '',
      isDiscount ? BESS_DISCOUNT_HASHTAG : BESS_OFFER_HASHTAG,
    ].filter(Boolean);
    return lines.join('\n');
  };

  const openContact = async (channel, intent = 'offer') => {
    if (contactBusy) return;
    if (!canContact) {
      setContactFormError(t('orderBessContactNeedNamePhone'));
      return;
    }
    setContactFormError('');
    setContactBusy(`${intent}:${channel}`);
    try {
      // Notify support chat first (best-effort), then open messenger for the user
      try {
        await fetch(apiUrl('/api/bess-order/contact'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            channel,
            intent,
            preset_id: presetId,
            business_type: businessType,
            units: intent === 'discount' ? discountUnits : null,
            total_usd: totalUsd,
            name: trimmedName,
            phone: trimmedPhone,
            contact: `${trimmedName} / ${trimmedPhone}`,
            kit: kitPayload,
            page_url: typeof window !== 'undefined' ? window.location.href : orderBessPageUrl,
          }),
        });
      } catch {
        /* ignore — still open messenger */
      }
      const msg = buildContactMessage(intent);
      const url = channel === 'telegram' ? buildB2bTelegramUrl(msg) : buildB2bWhatsAppUrl(msg);
      window.open(url, '_blank', 'noopener,noreferrer');
    } finally {
      setContactBusy('');
    }
  };

  const submitDiscount = async () => {
    if (!canContact) {
      setContactFormError(t('orderBessContactNeedNamePhone'));
      return;
    }
    setContactFormError('');
    setDiscountBusy(true);
    setDiscountStatus('');
    try {
      const res = await fetch(apiUrl('/api/bess-order/discount-request'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          preset_id: presetId,
          business_type: businessType,
          units: discountUnits,
          total_usd: totalUsd,
          name: trimmedName,
          phone: trimmedPhone,
          contact: `${trimmedName} / ${trimmedPhone}`,
          kit: kitPayload,
          page_url: typeof window !== 'undefined' ? window.location.href : orderBessPageUrl,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDiscountStatus('ok');
    } catch {
      setDiscountStatus('err');
    } finally {
      setDiscountBusy(false);
    }
  };

  const downloadPng = async () => {
    if (totalUsd == null || pdfBusy) return;
    setPdfBusy(true);
    try {
      await downloadOrderBessOfferPng({
        kw: activeBom.kw,
        kwh: activeBom.kwh,
        lines: pricedLines,
        totalUsd,
        totalUah,
        fxRate: fx,
        priceLabel: priceColLabel,
      });
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('Order BESS PNG failed', e);
    } finally {
      setPdfBusy(false);
    }
  };

  return (
    <div className="order-bess-page">
      <div className="order-bess-page__inner">
        <header className="order-bess-hero">
          <h1 className="order-bess-hero__title">{t('orderBessPageTitle')}</h1>
          <p className="order-bess-hero__sub">{t('orderBessPageSubtitle')}</p>
        </header>

        <section className="order-bess-card" aria-labelledby="order-bess-biz">
          <h2 id="order-bess-biz" className="order-bess-card__title">
            {t('orderBessBusinessType')}
          </h2>
          <div className="order-bess-seg" role="radiogroup" aria-label={t('orderBessBusinessType')}>
            {BUSINESS_TYPES.map(b => (
              <button
                key={b.id}
                type="button"
                role="radio"
                aria-checked={businessType === b.id}
                className={`order-bess-seg__btn${businessType === b.id ? ' order-bess-seg__btn--active' : ''}`}
                onClick={() => setBusinessType(b.id)}
              >
                {t(b.labelKey)}
              </button>
            ))}
          </div>
        </section>

        <section className="order-bess-card" aria-labelledby="order-bess-preset">
          <h2 id="order-bess-preset" className="order-bess-card__title">
            {t('orderBessPreset')}
          </h2>
          <div className="order-bess-presets">
            <div className="order-bess-presets__group">
              <div className="order-bess-presets__label">{t('orderBessPresetLv')}</div>
              <div className="order-bess-chips">
                {PRESETS.filter(p => p.group === 'lv').map(p => (
                  <button
                    key={p.id}
                    type="button"
                    className={`order-bess-chip${presetId === p.id ? ' order-bess-chip--active' : ''}`}
                    onClick={() => setPresetId(p.id)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="order-bess-presets__group">
              <div className="order-bess-presets__label">{t('orderBessPresetHv')}</div>
              <div className="order-bess-chips">
                {PRESETS.filter(p => p.group === 'hv').map(p => (
                  <button
                    key={p.id}
                    type="button"
                    className={`order-bess-chip${presetId === p.id ? ' order-bess-chip--active' : ''}`}
                    onClick={() => setPresetId(p.id)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="order-bess-presets__group">
              <div className="order-bess-presets__label">{t('orderBessPresetCustom')}</div>
              <button
                type="button"
                className={`order-bess-chip${presetId === CUSTOM_PRESET_ID ? ' order-bess-chip--active' : ''}`}
                onClick={() => setPresetId(CUSTOM_PRESET_ID)}
              >
                {t('orderBessCustomBtn')}
              </button>
            </div>
          </div>

          {presetId === CUSTOM_PRESET_ID ? (
            <div className="order-bess-custom">
              <label className="order-bess-field">
                <span>{t('orderBessSelectKw')}</span>
                <select value={customInv} onChange={e => setCustomInv(e.target.value)}>
                  {Object.entries(INVERTERS).map(([art, meta]) => (
                    <option key={art} value={art}>
                      {meta.kw} кВт ({meta.voltage.toUpperCase()}) — {art}
                    </option>
                  ))}
                </select>
              </label>
              <label className="order-bess-field">
                <span>{t('orderBessSelectBattery')}</span>
                <select value={customBat} onChange={e => setCustomBat(e.target.value)}>
                  {batteryChoices.map(b => (
                    <option key={b.article} value={b.article}>
                      {b.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="order-bess-range-hint">
                {t('orderBessAllowedKwh')}: <strong>{kwhRangeLabel(kwhOptions)}</strong>
                {voltageClass === 'hv' ? (
                  <span className="order-bess-range-hint__note"> {t('orderBessHvVoltageNote')}</span>
                ) : null}
              </div>
              <label className="order-bess-field">
                <span>{t('orderBessSelectKwh')}</span>
                <select
                  value={String(customKwh)}
                  onChange={e => setCustomKwh(Number(e.target.value))}
                >
                  {kwhOptions.map(o => (
                    <option key={`${o.kwh}-${o.modules}`} value={o.kwh}>
                      {o.kwh} кВт·год
                      {o.voltageV != null
                        ? ` (${o.strings}×${o.modulesPerString} @ ${o.voltageV} V)`
                        : ` (${o.modules} шт.)`}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}
        </section>

        <section className="order-bess-card" aria-labelledby="order-bess-bom">
          <div className="order-bess-card__head">
            <h2 id="order-bess-bom" className="order-bess-card__title">
              {offerTitle}
            </h2>
            <button type="button" className="order-bess-refresh" onClick={() => void loadPrices(true)} disabled={loading}>
              {t('orderBessRefreshPrices')}
            </button>
          </div>
          {loading && !priceList ? <p className="order-bess-muted">{t('orderBessLoading')}</p> : null}
          {loadError ? <p className="order-bess-error">{loadError}</p> : null}

          <div className="order-bess-table-wrap">
            <table className="order-bess-table">
              <thead>
                <tr>
                  <th>{t('orderBessColItem')}</th>
                  <th>{t('orderBessColArticle')}</th>
                  <th>{t('orderBessColQty')}</th>
                  <th>{priceColLabel}</th>
                  <th>{t('orderBessColSum')}</th>
                  <th>{t('orderBessColAvail')}</th>
                </tr>
              </thead>
              <tbody>
                {pricedLines.map(l => (
                  <tr key={`${l.article}-${l.qty}-${l.note}`}>
                    <td>
                      <div className="order-bess-item-name">{l.name}</div>
                      {l.note ? <div className="order-bess-item-note">{l.note}</div> : null}
                      {biomSavings &&
                      biomSavings.savingsUsd > 0 &&
                      normArticle(l.article) === normArticle(customBat) ? (
                        <div className="order-bess-biom-cheaper">
                          {t('orderBessBiomCheaper', {
                            usd: fmtUsd(biomSavings.savingsUsd),
                            model: biomSavings.biomArticle,
                          })}
                        </div>
                      ) : null}
                    </td>
                    <td className="order-bess-mono">{l.article}</td>
                    <td className="order-bess-num">{l.qty}</td>
                    <td className="order-bess-num">
                      {l.unit == null ? '—' : `$${fmtUsd(l.unit)}`}
                    </td>
                    <td className="order-bess-num">
                      {l.lineTotal == null ? '—' : `$${fmtUsd(l.lineTotal)}`}
                    </td>
                    <td>
                      {l.availability ? (
                        <span
                          className={
                            /в\s*наявност/i.test(l.availability)
                              ? 'order-bess-avail order-bess-avail--in-stock'
                              : 'order-bess-avail'
                          }
                        >
                          {l.availability}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4}>
                    <strong>{t('orderBessTotal')}</strong>
                    <span className="order-bess-muted"> · {priceColLabel}</span>
                  </td>
                  <td className="order-bess-num">
                    <strong>{totalUsd == null ? '—' : `$${fmtUsd(totalUsd)}`}</strong>
                  </td>
                  <td />
                </tr>
                <tr>
                  <td colSpan={4}>{t('orderBessTotalUah', { rate: fx })}</td>
                  <td className="order-bess-num">{totalUah == null ? '—' : `${fmtUah(totalUah)} грн`}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="order-bess-kwh">
            {t('orderBessCapacity')}: <strong>{activeBom.kwh} кВт·год</strong> · {activeBom.kw} кВт
          </p>
        </section>

        <section className="order-bess-card" aria-labelledby="order-bess-summary">
          <div className="order-bess-card__head">
            <h2 id="order-bess-summary" className="order-bess-card__title">
              {t('orderBessSummary')}
            </h2>
            <div className="order-bess-summary-actions">
              <button
                type="button"
                className="order-bess-primary"
                disabled={pdfBusy || totalUsd == null}
                onClick={() => void downloadPng()}
              >
                {pdfBusy ? t('orderBessPngBusy') : t('orderBessDownloadPng')}
              </button>
            </div>
          </div>
          <ul className="order-bess-summary-list">
            <li>
              {t('orderBessSummaryKit')}: {activeBom.kw} кВт + {activeBom.kwh} кВт·год
            </li>
            <li>
              {t('orderBessSummaryTotal')}: {totalUsd == null ? '—' : `$${fmtUsd(totalUsd)}`} ({priceColLabel})
            </li>
            <li>
              {t('orderBessSummaryItems')}: {pricedLines.length}
            </li>
          </ul>

          <div className="order-bess-contact">
            <p className="order-bess-contact__label">{t('orderBessWantOffer')}</p>
            <div className="order-bess-contact-fields">
              <label className="order-bess-field order-bess-field--grow">
                <span>{t('orderBessContactName')}</span>
                <input
                  type="text"
                  autoComplete="name"
                  value={contactName}
                  onChange={e => {
                    setContactName(e.target.value);
                    if (contactFormError) setContactFormError('');
                  }}
                  placeholder={t('orderBessContactNamePh')}
                />
              </label>
              <label className="order-bess-field order-bess-field--grow">
                <span>{t('orderBessContactPhone')}</span>
                <input
                  type="tel"
                  autoComplete="tel"
                  value={contactPhone}
                  onChange={e => {
                    setContactPhone(e.target.value);
                    if (contactFormError) setContactFormError('');
                  }}
                  placeholder={t('orderBessContactPhonePh')}
                />
              </label>
            </div>
            {contactFormError ? <p className="order-bess-error">{contactFormError}</p> : null}
            <div className="order-bess-contact__btns">
              <button
                type="button"
                className="order-bess-msg-btn order-bess-msg-btn--telegram"
                disabled={!!contactBusy}
                onClick={() => void openContact('telegram', 'offer')}
              >
                {contactBusy === 'offer:telegram' ? t('orderBessContactBusy') : t('orderBessContactTelegram')}
              </button>
              <button
                type="button"
                className="order-bess-msg-btn order-bess-msg-btn--whatsapp"
                disabled={!!contactBusy}
                onClick={() => void openContact('whatsapp', 'offer')}
              >
                {contactBusy === 'offer:whatsapp' ? t('orderBessContactBusy') : t('orderBessContactWhatsApp')}
              </button>
            </div>
          </div>
        </section>

        <section className="order-bess-card" aria-labelledby="order-bess-discount">
          <h2 id="order-bess-discount" className="order-bess-card__title">
            {t('orderBessDiscountTitle')}
          </h2>
          <p className="order-bess-muted">{t('orderBessDiscountHint')}</p>
          <div className="order-bess-discount">
            <label className="order-bess-field">
              <span>{t('orderBessDiscountUnits')}</span>
              <select value={discountUnits} onChange={e => setDiscountUnits(Number(e.target.value))}>
                {DISCOUNT_UNITS.map(u => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </label>
            <label className="order-bess-field order-bess-field--grow">
              <span>{t('orderBessContactName')}</span>
              <input
                type="text"
                autoComplete="name"
                value={contactName}
                onChange={e => {
                  setContactName(e.target.value);
                  if (contactFormError) setContactFormError('');
                }}
                placeholder={t('orderBessContactNamePh')}
              />
            </label>
            <label className="order-bess-field order-bess-field--grow">
              <span>{t('orderBessContactPhone')}</span>
              <input
                type="tel"
                autoComplete="tel"
                value={contactPhone}
                onChange={e => {
                  setContactPhone(e.target.value);
                  if (contactFormError) setContactFormError('');
                }}
                placeholder={t('orderBessContactPhonePh')}
              />
            </label>
            <button
              type="button"
              className="order-bess-primary"
              disabled={discountBusy || totalUsd == null}
              onClick={() => void submitDiscount()}
            >
              {t('orderBessDiscountSubmit')}
            </button>
          </div>
          {contactFormError ? <p className="order-bess-error">{contactFormError}</p> : null}
          <div className="order-bess-contact order-bess-contact--inline">
            <p className="order-bess-contact__label">{t('orderBessWantDiscount')}</p>
            <div className="order-bess-contact__btns">
              <button
                type="button"
                className="order-bess-msg-btn order-bess-msg-btn--telegram"
                disabled={!!contactBusy}
                onClick={() => void openContact('telegram', 'discount')}
              >
                {contactBusy === 'discount:telegram' ? t('orderBessContactBusy') : t('orderBessContactTelegram')}
              </button>
              <button
                type="button"
                className="order-bess-msg-btn order-bess-msg-btn--whatsapp"
                disabled={!!contactBusy}
                onClick={() => void openContact('whatsapp', 'discount')}
              >
                {contactBusy === 'discount:whatsapp' ? t('orderBessContactBusy') : t('orderBessContactWhatsApp')}
              </button>
            </div>
          </div>
          {discountStatus === 'ok' ? <p className="order-bess-ok">{t('orderBessDiscountOk')}</p> : null}
          {discountStatus === 'err' ? <p className="order-bess-error">{t('orderBessDiscountErr')}</p> : null}
        </section>

        <section className="order-bess-card order-bess-share-card" aria-labelledby="order-bess-share">
          <h2 id="order-bess-share" className="order-bess-card__title">
            {t('orderBessShareTitle')}
          </h2>
          <p className="order-bess-muted">{t('orderBessShareHint')}</p>
          <button
            type="button"
            className="order-bess-share-btn"
            onClick={() => void handleShare()}
            aria-label={t('orderBessShareBtn')}
          >
            <ShareIcon className="order-bess-share-btn__icon" />
            <span>{t('orderBessShareBtn')}</span>
          </button>
        </section>
      </div>

      <SharePageModal
        open={shareModalOpen}
        url={shareModalUrl}
        copied={shareModalCopied}
        copyFailed={shareModalCopyFailed}
        onClose={() => setShareModalOpen(false)}
        t={t}
      />
    </div>
  );
}
