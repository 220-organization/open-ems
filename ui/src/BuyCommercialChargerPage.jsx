import { useEffect, useMemo, useRef, useState } from 'react';
import ChargerBuyRequestModal from './ChargerBuyRequestModal';
import { notifyOpenEmsSearchChange } from './sharePageQr';
import { useOpenEmsSeo } from './useOpenEmsSeo';
import './buy-home-charger.css';

const EUR_UAH_FALLBACK = 47;
const USD_UAH_FALLBACK = 42;
const CURRENCY_STORAGE_KEY = 'commercial-charger-currency';
const DEFAULT_SORT = 'price-asc';
const CATALOG_PATH = '/buy-commercial-charger';
const PORT_IDS = ['2dc', '2dc_ac', '2dc_2ac', '3dc', '4dc'];
const WARRANTY_YEARS = ['1', '2', '3'];
const DOWNTIME_IDS = ['48h', '5d', '10d'];
const MANAGER_IDS = ['yes', 'no'];

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  return base ? `${base}${path}` : path;
}

function todayKyivIso() {
  try {
    return new Date().toLocaleDateString('en-CA', { timeZone: 'Europe/Kyiv' });
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function readStoredCurrency() {
  try {
    const raw = localStorage.getItem(CURRENCY_STORAGE_KEY);
    if (raw === 'UAH' || raw === 'USD' || raw === 'EUR') return raw;
  } catch {
    /* ignore */
  }
  return 'EUR';
}

function writeStoredCurrency(currency) {
  try {
    localStorage.setItem(CURRENCY_STORAGE_KEY, currency);
  } catch {
    /* ignore */
  }
}

function fmtMoney(amount, currency, locale) {
  if (amount == null || Number.isNaN(amount)) return '—';
  const code = currency || 'EUR';
  const loc = code === 'USD' ? 'en-US' : locale === 'uk' ? 'uk-UA' : locale === 'es' ? 'es-ES' : 'en-US';
  try {
    return new Intl.NumberFormat(loc, {
      style: 'currency',
      currency: code,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${Math.round(amount)} ${code}`;
  }
}

function toDisplayAmount(price, srcCurrency, displayCurrency, eurUah, usdUah) {
  if (price == null || Number.isNaN(Number(price))) return null;
  const src = (srcCurrency || 'EUR').toUpperCase();
  const dest = (displayCurrency || 'EUR').toUpperCase();
  const amount = Number(price);
  if (src === dest) return amount;
  if (!(eurUah > 0)) return amount;
  if (src === 'EUR' && dest === 'UAH') return amount * eurUah;
  if (src === 'EUR' && dest === 'USD') {
    if (!(usdUah > 0)) return amount;
    return (amount * eurUah) / usdUah;
  }
  return amount;
}

function powerBucketLabel(bucket, t) {
  if (bucket === 'upto160') return t('commercialChargerPowerUpto160');
  if (bucket === '200to320') return t('commercialChargerPower200to320');
  if (bucket === '360to480') return t('commercialChargerPower360to480');
  if (bucket === '720plus') return t('commercialChargerPower720');
  return bucket;
}

function seriesLabel(series, t) {
  if (series === 'SPLIT') return t('commercialChargerSeriesSplit');
  if (series === 'DISPENSER') return t('commercialChargerSeriesDispenser');
  return series;
}

function portsLabel(ports, t) {
  if (ports === '2dc') return t('commercialChargerPorts2dc');
  if (ports === '2dc_ac') return t('commercialChargerPorts2dcAc');
  if (ports === '2dc_2ac') return t('commercialChargerPorts2dc2ac');
  if (ports === '3dc') return t('commercialChargerPorts3dc');
  if (ports === '4dc') return t('commercialChargerPorts4dc');
  return ports;
}

function coolingLabel(cooling, t) {
  if (cooling === 'air') return t('commercialChargerCoolingAir');
  if (cooling === 'liquid') return t('commercialChargerCoolingLiquid');
  return cooling;
}

function warrantyYearsLabel(years, t) {
  if (years === '1' || years === 1) return t('commercialChargerWarranty1');
  if (years === '2' || years === 2) return t('commercialChargerWarranty2');
  if (years === '3' || years === 3) return t('commercialChargerWarranty3');
  return String(years);
}

function downtimeLabel(id, t) {
  if (id === '48h') return t('commercialChargerDowntime48h');
  if (id === '5d') return t('commercialChargerDowntime5d');
  if (id === '10d') return t('commercialChargerDowntime10d');
  return id;
}

function leadTimeLabel(id, t) {
  // Catalog is built to order; fall back to the EDS default when the feed omits it.
  if (!id || id === '2to3m') return t('commercialChargerLeadTime2to3m');
  return id;
}

function managerLabel(id, t) {
  if (id === 'yes') return t('commercialChargerManagerYes');
  if (id === 'no') return t('commercialChargerManagerNo');
  return id;
}

function managerFilterValue(item) {
  if (item?.dedicated_manager === true) return 'yes';
  if (item?.dedicated_manager === false) return 'no';
  return '';
}

function readCatalogFromUrl() {
  if (typeof window === 'undefined') return {};
  try {
    const u = new URLSearchParams(window.location.search);
    const out = {};
    const sku = (u.get('sku') || '').trim();
    if (sku) out.sku = sku;
    const power = (u.get('power') || '').trim();
    if (power) out.power = power;
    const ports = (u.get('ports') || '').trim();
    if (PORT_IDS.includes(ports)) out.ports = ports;
    const cooling = (u.get('cooling') || '').trim();
    if (cooling) out.cooling = cooling;
    const warranty = (u.get('warranty') || '').trim();
    if (WARRANTY_YEARS.includes(warranty)) out.warranty = warranty;
    const downtime = (u.get('downtime') || '').trim();
    if (DOWNTIME_IDS.includes(downtime)) out.downtime = downtime;
    const manager = (u.get('manager') || '').trim();
    if (MANAGER_IDS.includes(manager)) out.manager = manager;
    const sort = (u.get('sort') || '').trim();
    if (sort === 'price-asc' || sort === 'price-desc' || sort === 'power-desc') out.sort = sort;
    return out;
  } catch {
    return {};
  }
}

function writeCatalogToUrl(state) {
  if (typeof window === 'undefined') return;
  try {
    const u = new URL(window.location.href);
    const setOrDel = (key, val) => {
      if (val) u.searchParams.set(key, val);
      else u.searchParams.delete(key);
    };
    setOrDel('sku', state.sku);
    u.searchParams.delete('series');
    setOrDel('power', state.power);
    setOrDel('ports', state.ports);
    u.searchParams.delete('connector');
    setOrDel('cooling', state.cooling);
    setOrDel('warranty', state.warranty);
    setOrDel('downtime', state.downtime);
    setOrDel('manager', state.manager);
    if (state.sort && state.sort !== DEFAULT_SORT) u.searchParams.set('sort', state.sort);
    else u.searchParams.delete('sort');
    const next = `${u.pathname}${u.search}${u.hash}`;
    const cur = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next === cur) return;
    window.history.replaceState({}, '', next);
    notifyOpenEmsSearchChange();
  } catch {
    /* ignore */
  }
}

function productQuotePageUrl(p) {
  if (typeof window === 'undefined') return CATALOG_PATH;
  const u = new URL(CATALOG_PATH, window.location.origin);
  const lang = new URLSearchParams(window.location.search).get('lang');
  if (lang) u.searchParams.set('lang', lang);
  if (p.sku) u.searchParams.set('sku', p.sku);
  if (p.power_bucket) u.searchParams.set('power', p.power_bucket);
  if (p.ports) u.searchParams.set('ports', p.ports);
  if (p.cooling) u.searchParams.set('cooling', p.cooling);
  if (p.warranty_years) u.searchParams.set('warranty', String(p.warranty_years));
  if (p.warranty_downtime) u.searchParams.set('downtime', p.warranty_downtime);
  const manager = managerFilterValue(p);
  if (manager) u.searchParams.set('manager', manager);
  return u.toString();
}

function findSkuCard(sku) {
  if (!sku || typeof document === 'undefined') return null;
  const nodes = document.querySelectorAll('[data-charger-sku]');
  for (let i = 0; i < nodes.length; i += 1) {
    if (nodes[i].getAttribute('data-charger-sku') === sku) return nodes[i];
  }
  return null;
}

function Chip({ active, onClick, children }) {
  return (
    <button
      type="button"
      className={`home-charger-chip${active ? ' home-charger-chip--active' : ''}`}
      onClick={onClick}
      aria-pressed={active}
    >
      {children}
    </button>
  );
}

/**
 * Buy commercial EV charger — EDS Chargers retail catalog with DC-hub filters.
 */
export default function BuyCommercialChargerPage({ t, locale }) {
  useOpenEmsSeo(t('commercialChargerPageTitle'), locale, t, {
    variant: 'landing',
    canonicalPath: '/buy-commercial-charger',
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [products, setProducts] = useState([]);
  const [facets, setFacets] = useState(null);
  const [notes, setNotes] = useState([]);

  const initialUrl = useMemo(() => readCatalogFromUrl(), []);
  const [sku, setSku] = useState(initialUrl.sku || '');
  const [power, setPower] = useState(initialUrl.power || '');
  const [ports, setPorts] = useState(initialUrl.ports || '');
  const [cooling, setCooling] = useState(initialUrl.cooling || '');
  const [warranty, setWarranty] = useState(initialUrl.warranty || '');
  const [downtime, setDowntime] = useState(initialUrl.downtime || '');
  const [manager, setManager] = useState(initialUrl.manager || '');
  const [sort, setSort] = useState(initialUrl.sort || DEFAULT_SORT);
  const skuHydrated = useRef(false);
  const [displayCurrency, setDisplayCurrency] = useState(readStoredCurrency);
  const [eurUah, setEurUah] = useState(EUR_UAH_FALLBACK);
  const [usdUah, setUsdUah] = useState(USD_UAH_FALLBACK);
  const [fxMeta, setFxMeta] = useState(null);
  const [buyRequest, setBuyRequest] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const res = await fetch(apiUrl('/api/commercial-chargers'), { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (cancelled) return;
        setProducts(Array.isArray(data.products) ? data.products : []);
        setFacets(data.facets || null);
        setNotes(Array.isArray(data.notes) ? data.notes : []);
      } catch (e) {
        if (!cancelled) setError(t('commercialChargerLoadError'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const day = todayKyivIso();
      try {
        const [eurRes, usdRes] = await Promise.all([
          fetch(apiUrl(`/api/fx/eur-uah?date=${encodeURIComponent(day)}`), { cache: 'no-store' }),
          fetch(apiUrl(`/api/fx/usd-uah?date=${encodeURIComponent(day)}`), { cache: 'no-store' }),
        ]);
        const [eurData, usdData] = await Promise.all([eurRes.json(), usdRes.json()]);
        if (cancelled) return;
        const eurRate = eurData?.ok ? Number(eurData.rate) : NaN;
        const usdRate = usdData?.ok ? Number(usdData.rate) : NaN;
        if (Number.isFinite(eurRate) && eurRate > 0) setEurUah(eurRate);
        if (Number.isFinite(usdRate) && usdRate > 0) setUsdUah(usdRate);
        setFxMeta({
          date: eurData?.exchangedate || usdData?.exchangedate || day,
        });
      } catch {
        /* keep fallback rates */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setCurrency = next => {
    setDisplayCurrency(next);
    writeStoredCurrency(next);
  };

  useEffect(() => {
    writeCatalogToUrl({ sku, power, ports, cooling, warranty, downtime, manager, sort });
  }, [sku, power, ports, cooling, warranty, downtime, manager, sort]);

  useEffect(() => {
    if (skuHydrated.current || !sku || !products.length) return;
    const p = products.find(x => x.sku === sku);
    if (!p) return;
    skuHydrated.current = true;
    if (!power && p.power_bucket) setPower(p.power_bucket);
    if (!ports && p.ports) setPorts(p.ports);
    if (!cooling && p.cooling) setCooling(p.cooling);
    if (!warranty && p.warranty_years) setWarranty(String(p.warranty_years));
    if (!downtime && p.warranty_downtime) setDowntime(p.warranty_downtime);
    if (!manager && managerFilterValue(p)) setManager(managerFilterValue(p));
  }, [products, sku, power, ports, cooling, warranty, downtime, manager]);

  useEffect(() => {
    if (!sku || !products.length) return;
    const p = products.find(x => x.sku === sku);
    if (!p) {
      setSku('');
      return;
    }
    if (power && p.power_bucket !== power) setSku('');
    else if (cooling && p.cooling !== cooling) setSku('');
    else if (ports && p.ports !== ports) setSku('');
    else if (warranty && String(p.warranty_years) !== warranty) setSku('');
    else if (downtime && p.warranty_downtime !== downtime) setSku('');
    else if (manager && managerFilterValue(p) !== manager) setSku('');
  }, [sku, power, ports, cooling, warranty, downtime, manager, products]);

  const filtered = useMemo(() => {
    let list = products.slice();
    if (power) list = list.filter(p => p.power_bucket === power);
    if (ports) list = list.filter(p => p.ports === ports);
    if (cooling) list = list.filter(p => p.cooling === cooling);
    if (warranty) list = list.filter(p => String(p.warranty_years) === warranty);
    if (downtime) list = list.filter(p => p.warranty_downtime === downtime);
    if (manager) list = list.filter(p => managerFilterValue(p) === manager);

    list.sort((a, b) => {
      if (sku) {
        if (a.sku === sku && b.sku !== sku) return -1;
        if (b.sku === sku && a.sku !== sku) return 1;
      }
      const pa = toDisplayAmount(a.price, a.currency, displayCurrency, eurUah, usdUah);
      const pb = toDisplayAmount(b.price, b.currency, displayCurrency, eurUah, usdUah);
      const na = pa == null ? Number.POSITIVE_INFINITY : pa;
      const nb = pb == null ? Number.POSITIVE_INFINITY : pb;
      if (sort === 'price-desc') return nb - na;
      if (sort === 'power-desc') return (b.power_kw || 0) - (a.power_kw || 0);
      return na - nb;
    });
    return list;
  }, [products, power, ports, cooling, warranty, downtime, manager, sort, sku, displayCurrency, eurUah, usdUah]);

  useEffect(() => {
    if (!sku || loading) return;
    const el = findSkuCard(sku);
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [sku, loading, filtered.length]);

  const clearFilters = () => {
    setSku('');
    setPower('');
    setPorts('');
    setCooling('');
    setWarranty('');
    setDowntime('');
    setManager('');
  };

  const hasFilters = Boolean(sku || power || ports || cooling || warranty || downtime || manager);

  const openBuyRequest = p => {
    setSku(p.sku);
    setBuyRequest({
      catalog: 'commercial',
      title: p.title,
      sku: p.sku,
      price: fmtMoney(p.price, 'EUR', locale),
      pageUrl: productQuotePageUrl(p),
      productUrl: p.link,
    });
  };

  return (
    <div className="home-charger-page">
      <div className="home-charger-page__inner">
        <header className="home-charger-hero">
          <h1 className="home-charger-hero__title">{t('commercialChargerPageTitle')}</h1>
          <p className="home-charger-hero__sub">{t('commercialChargerPageSubtitle')}</p>
        </header>

        <section className="home-charger-filters" aria-label={t('commercialChargerFiltersAria')}>
          <div className="home-charger-filters__top">
            <button
              type="button"
              className="home-charger-clear home-charger-clear--top"
              onClick={clearFilters}
              disabled={!hasFilters}
            >
              {t('commercialChargerClearFilters')}
            </button>
          </div>
          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">{t('commercialChargerFilterPower')}</span>
            <div className="home-charger-chips">
              <Chip active={!power} onClick={() => setPower('')}>
                {t('commercialChargerFilterAny')}
              </Chip>
              {(facets?.power_buckets || ['upto160', '200to320', '360to480', '720plus']).map(
                b => (
                  <Chip key={b} active={power === b} onClick={() => setPower(power === b ? '' : b)}>
                    {powerBucketLabel(b, t)}
                  </Chip>
                )
              )}
            </div>
          </div>

          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">{t('commercialChargerFilterPorts')}</span>
            <div className="home-charger-chips">
              <Chip active={!ports} onClick={() => setPorts('')}>
                {t('commercialChargerFilterAny')}
              </Chip>
              {(facets?.ports || PORT_IDS).map(c => (
                <Chip
                  key={c}
                  active={ports === c}
                  onClick={() => setPorts(ports === c ? '' : c)}
                >
                  {portsLabel(c, t)}
                </Chip>
              ))}
            </div>
          </div>

          {(facets?.cooling || []).length > 0 ? (
            <div className="home-charger-filters__row">
              <span className="home-charger-filters__label">{t('commercialChargerFilterCooling')}</span>
              <div className="home-charger-chips">
                <Chip active={!cooling} onClick={() => setCooling('')}>
                  {t('commercialChargerFilterAny')}
                </Chip>
                {facets.cooling.map(c => (
                  <Chip
                    key={c}
                    active={cooling === c}
                    onClick={() => setCooling(cooling === c ? '' : c)}
                  >
                    {coolingLabel(c, t)}
                  </Chip>
                ))}
              </div>
            </div>
          ) : null}

          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">{t('commercialChargerFilterWarranty')}</span>
            <div className="home-charger-chips">
              <Chip active={!warranty} onClick={() => setWarranty('')}>
                {t('commercialChargerFilterAny')}
              </Chip>
              {WARRANTY_YEARS.map(y => (
                <Chip
                  key={y}
                  active={warranty === y}
                  onClick={() => setWarranty(warranty === y ? '' : y)}
                >
                  {warrantyYearsLabel(y, t)}
                </Chip>
              ))}
            </div>
          </div>

          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">{t('commercialChargerFilterDowntime')}</span>
            <p className="home-charger-filters__hint">{t('commercialChargerDowntimeHint')}</p>
            <div className="home-charger-chips">
              <Chip active={!downtime} onClick={() => setDowntime('')}>
                {t('commercialChargerFilterAny')}
              </Chip>
              {DOWNTIME_IDS.map(d => (
                <Chip
                  key={d}
                  active={downtime === d}
                  onClick={() => setDowntime(downtime === d ? '' : d)}
                >
                  {downtimeLabel(d, t)}
                </Chip>
              ))}
            </div>
          </div>

          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">{t('commercialChargerFilterManager')}</span>
            <div className="home-charger-chips">
              <Chip active={!manager} onClick={() => setManager('')}>
                {t('commercialChargerFilterAny')}
              </Chip>
              {MANAGER_IDS.map(m => (
                <Chip
                  key={m}
                  active={manager === m}
                  onClick={() => setManager(manager === m ? '' : m)}
                >
                  {managerLabel(m, t)}
                </Chip>
              ))}
            </div>
          </div>

          <div className="home-charger-filters__toolbar">
            <label className="home-charger-sort">
              <span>{t('commercialChargerSort')}</span>
              <select value={sort} onChange={e => setSort(e.target.value)}>
                <option value="price-asc">{t('commercialChargerSortPriceAsc')}</option>
                <option value="price-desc">{t('commercialChargerSortPriceDesc')}</option>
                <option value="power-desc">{t('commercialChargerSortPowerDesc')}</option>
              </select>
            </label>
            <div className="home-charger-currency" role="group" aria-label={t('commercialChargerCurrency')}>
              <Chip active={displayCurrency === 'EUR'} onClick={() => setCurrency('EUR')}>
                EUR
              </Chip>
              <Chip active={displayCurrency === 'USD'} onClick={() => setCurrency('USD')}>
                USD
              </Chip>
              <Chip active={displayCurrency === 'UAH'} onClick={() => setCurrency('UAH')}>
                UAH
              </Chip>
            </div>
            <p className="home-charger-count">
              {t('commercialChargerResultCount', { count: filtered.length })}
            </p>
          </div>
        </section>

        {loading ? <p className="home-charger-muted">{t('commercialChargerLoading')}</p> : null}
        {error ? <p className="home-charger-error">{error}</p> : null}

        {!loading && !error && filtered.length === 0 ? (
          <p className="home-charger-muted">{t('commercialChargerEmpty')}</p>
        ) : null}

        <div className="home-charger-grid">
          {filtered.map(p => (
            <article
              key={p.id}
              data-charger-sku={p.sku}
              className={`home-charger-card${p.sku === sku ? ' home-charger-card--selected' : ''}`}
            >
              <div
                className={`home-charger-card__media${
                  p.form === 'split' || p.form === 'dispenser' ? ' home-charger-card__media--scene' : ''
                }`}
              >
                {p.image ? (
                  <img src={p.image} alt="" loading="lazy" decoding="async" />
                ) : (
                  <div className="home-charger-card__placeholder" aria-hidden />
                )}
              </div>
              <div className="home-charger-card__body">
                <h2 className="home-charger-card__title">{p.title}</h2>
                <ul className="home-charger-card__meta">
                  {p.power_kw != null ? (
                    <li>
                      {t('commercialChargerMetaPower')}: <strong>{p.power_kw} kW</strong>
                    </li>
                  ) : null}
                  {p.series ? (
                    <li>
                      {t('commercialChargerMetaSeries')}: <strong>{seriesLabel(p.series, t)}</strong>
                    </li>
                  ) : null}
                  {p.ports ? (
                    <li>
                      {t('commercialChargerMetaPorts')}: <strong>{portsLabel(p.ports, t)}</strong>
                    </li>
                  ) : p.config ? (
                    <li>
                      {t('commercialChargerMetaConfig')}: <strong>{p.config}</strong>
                    </li>
                  ) : null}
                  {p.connectors?.length ? (
                    <li>
                      {t('commercialChargerMetaConnector')}:{' '}
                      <strong>{p.connectors.join(' / ')}</strong>
                    </li>
                  ) : null}
                  {p.cooling ? (
                    <li>
                      {t('commercialChargerMetaCooling')}:{' '}
                      <strong>{coolingLabel(p.cooling, t)}</strong>
                    </li>
                  ) : null}
                  {p.warranty_years ? (
                    <li>
                      {t('commercialChargerMetaWarranty')}:{' '}
                      <strong>{warrantyYearsLabel(p.warranty_years, t)}</strong>
                    </li>
                  ) : null}
                  {p.warranty_downtime ? (
                    <li title={t('commercialChargerDowntimeHint')}>
                      {t('commercialChargerMetaDowntime')}:{' '}
                      <strong>{downtimeLabel(p.warranty_downtime, t)}</strong>
                    </li>
                  ) : null}
                  {p.dedicated_manager != null ? (
                    <li>
                      {t('commercialChargerMetaManager')}:{' '}
                      <strong>{managerLabel(managerFilterValue(p), t)}</strong>
                    </li>
                  ) : null}
                  <li>
                    {t('commercialChargerMetaLeadTime')}:{' '}
                    <strong>{leadTimeLabel(p.lead_time, t)}</strong>
                  </li>
                </ul>
                <div className="home-charger-card__footer">
                  <p className="home-charger-card__price">
                    {fmtMoney(
                      toDisplayAmount(p.price, p.currency, displayCurrency, eurUah, usdUah),
                      displayCurrency,
                      locale
                    )}
                  </p>
                  <button
                    type="button"
                    className="home-charger-card__buy"
                    onClick={() => openBuyRequest(p)}
                  >
                    {t('commercialChargerBuy')}
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>

        {displayCurrency !== 'EUR' ? (
          <p className="home-charger-fx">
            {t('commercialChargerFxNote', {
              eur: new Intl.NumberFormat(locale === 'uk' ? 'uk-UA' : 'en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              }).format(eurUah),
              usd: new Intl.NumberFormat(locale === 'uk' ? 'uk-UA' : 'en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              }).format(usdUah),
              date: fxMeta?.date || todayKyivIso(),
            })}
          </p>
        ) : null}
        {notes.length ? (
          <ul className="home-charger-notes">
            {notes.map(n => (
              <li key={n}>{n.replace(/^\*+/, '').trim()}</li>
            ))}
          </ul>
        ) : (
          <p className="home-charger-fx">{t('commercialChargerVatNote')}</p>
        )}
      </div>

      {buyRequest ? (
        <ChargerBuyRequestModal t={t} product={buyRequest} onClose={() => setBuyRequest(null)} />
      ) : null}
    </div>
  );
}
