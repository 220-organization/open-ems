import { useEffect, useMemo, useState } from 'react';
import { useOpenEmsSeo } from './useOpenEmsSeo';
import './buy-home-charger.css';

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  return base ? `${base}${path}` : path;
}

function fmtMoney(amount, currency, locale) {
  if (amount == null || Number.isNaN(amount)) return '—';
  const loc = locale === 'uk' ? 'uk-UA' : locale === 'es' ? 'es-ES' : 'en-US';
  try {
    return new Intl.NumberFormat(loc, {
      style: 'currency',
      currency: currency || 'UAH',
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${Math.round(amount)} ${currency || 'UAH'}`;
  }
}

function powerBucketLabel(bucket, t) {
  if (bucket === 'upto4') return t('homeChargerPowerUpto4');
  if (bucket === '7to8') return t('homeChargerPower7to8');
  if (bucket === '11') return t('homeChargerPower11');
  if (bucket === '22plus') return t('homeChargerPower22');
  return bucket;
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
 * Buy Home charger — Sparks catalog with simple EV-driver filters.
 */
export default function BuyHomeChargerPage({ t, locale }) {
  useOpenEmsSeo(t('homeChargerPageTitle'), locale, t, {
    variant: 'landing',
    canonicalPath: '/buy-home-charger',
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [products, setProducts] = useState([]);
  const [facets, setFacets] = useState(null);

  const [power, setPower] = useState('');
  const [connector, setConnector] = useState('');
  const [phases, setPhases] = useState('');
  const [brand, setBrand] = useState('');
  const [sort, setSort] = useState('price-asc');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const res = await fetch(apiUrl('/api/home-chargers'), { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (cancelled) return;
        setProducts(Array.isArray(data.products) ? data.products : []);
        setFacets(data.facets || null);
      } catch (e) {
        if (!cancelled) setError(t('homeChargerLoadError'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const filtered = useMemo(() => {
    let list = products.slice();
    if (power) list = list.filter(p => p.power_bucket === power);
    if (connector) list = list.filter(p => (p.connectors || []).includes(connector));
    if (phases) list = list.filter(p => String(p.phases) === String(phases));
    if (brand) list = list.filter(p => p.brand === brand);

    list.sort((a, b) => {
      const pa = a.price == null ? Number.POSITIVE_INFINITY : a.price;
      const pb = b.price == null ? Number.POSITIVE_INFINITY : b.price;
      if (sort === 'price-desc') return pb - pa;
      if (sort === 'power-desc') return (b.power_kw || 0) - (a.power_kw || 0);
      return pa - pb;
    });
    return list;
  }, [products, power, connector, phases, brand, sort]);

  const clearFilters = () => {
    setPower('');
    setConnector('');
    setPhases('');
    setBrand('');
  };

  const hasFilters = Boolean(power || connector || phases || brand);

  return (
    <div className="home-charger-page">
      <div className="home-charger-page__inner">
        <header className="home-charger-hero">
          <h1 className="home-charger-hero__title">{t('homeChargerPageTitle')}</h1>
          <p className="home-charger-hero__sub">{t('homeChargerPageSubtitle')}</p>
        </header>

        <section className="home-charger-filters" aria-label={t('homeChargerFiltersAria')}>
          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">{t('homeChargerFilterPower')}</span>
            <div className="home-charger-chips">
              <Chip active={!power} onClick={() => setPower('')}>
                {t('homeChargerFilterAny')}
              </Chip>
              {(facets?.power_buckets || ['upto4', '7to8', '11', '22plus']).map(b => (
                <Chip key={b} active={power === b} onClick={() => setPower(power === b ? '' : b)}>
                  {powerBucketLabel(b, t)}
                </Chip>
              ))}
            </div>
          </div>

          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">{t('homeChargerFilterConnector')}</span>
            <div className="home-charger-chips">
              <Chip active={!connector} onClick={() => setConnector('')}>
                {t('homeChargerFilterAny')}
              </Chip>
              {(facets?.connectors || []).map(c => (
                <Chip
                  key={c}
                  active={connector === c}
                  onClick={() => setConnector(connector === c ? '' : c)}
                >
                  {c}
                </Chip>
              ))}
            </div>
          </div>

          <div className="home-charger-filters__row">
            <span className="home-charger-filters__label">{t('homeChargerFilterPhases')}</span>
            <div className="home-charger-chips">
              <Chip active={!phases} onClick={() => setPhases('')}>
                {t('homeChargerFilterAny')}
              </Chip>
              {(facets?.phases || [1, 3]).map(ph => (
                <Chip
                  key={ph}
                  active={String(phases) === String(ph)}
                  onClick={() => setPhases(String(phases) === String(ph) ? '' : String(ph))}
                >
                  {ph === 1 ? t('homeChargerPhase1') : t('homeChargerPhase3')}
                </Chip>
              ))}
            </div>
          </div>

          {(facets?.brands || []).length > 0 ? (
            <div className="home-charger-filters__row">
              <span className="home-charger-filters__label">{t('homeChargerFilterBrand')}</span>
              <div className="home-charger-chips">
                <Chip active={!brand} onClick={() => setBrand('')}>
                  {t('homeChargerFilterAny')}
                </Chip>
                {facets.brands.map(b => (
                  <Chip key={b} active={brand === b} onClick={() => setBrand(brand === b ? '' : b)}>
                    {b}
                  </Chip>
                ))}
              </div>
            </div>
          ) : null}

          <div className="home-charger-filters__toolbar">
            <label className="home-charger-sort">
              <span>{t('homeChargerSort')}</span>
              <select value={sort} onChange={e => setSort(e.target.value)}>
                <option value="price-asc">{t('homeChargerSortPriceAsc')}</option>
                <option value="price-desc">{t('homeChargerSortPriceDesc')}</option>
                <option value="power-desc">{t('homeChargerSortPowerDesc')}</option>
              </select>
            </label>
            {hasFilters ? (
              <button type="button" className="home-charger-clear" onClick={clearFilters}>
                {t('homeChargerClearFilters')}
              </button>
            ) : null}
            <p className="home-charger-count">
              {t('homeChargerResultCount', { count: filtered.length })}
            </p>
          </div>
        </section>

        {loading ? <p className="home-charger-muted">{t('homeChargerLoading')}</p> : null}
        {error ? <p className="home-charger-error">{error}</p> : null}

        {!loading && !error && filtered.length === 0 ? (
          <p className="home-charger-muted">{t('homeChargerEmpty')}</p>
        ) : null}

        <div className="home-charger-grid">
          {filtered.map(p => (
            <article key={p.id} className="home-charger-card">
              <a
                className="home-charger-card__media"
                href={p.link}
                target="_blank"
                rel="noopener noreferrer"
              >
                {p.image ? (
                  <img src={p.image} alt="" loading="lazy" decoding="async" />
                ) : (
                  <div className="home-charger-card__placeholder" aria-hidden />
                )}
              </a>
              <div className="home-charger-card__body">
                <h2 className="home-charger-card__title">
                  <a href={p.link} target="_blank" rel="noopener noreferrer">
                    {p.title}
                  </a>
                </h2>
                <ul className="home-charger-card__meta">
                  {p.power_kw != null ? (
                    <li>
                      {t('homeChargerMetaPower')}: <strong>{p.power_kw} kW</strong>
                    </li>
                  ) : null}
                  {p.connectors?.length ? (
                    <li>
                      {t('homeChargerMetaConnector')}: <strong>{p.connectors.join(' / ')}</strong>
                    </li>
                  ) : null}
                  {p.phases != null ? (
                    <li>
                      {t('homeChargerMetaPhases')}:{' '}
                      <strong>
                        {p.phases === 1 ? t('homeChargerPhase1') : t('homeChargerPhase3')}
                      </strong>
                    </li>
                  ) : null}
                  {p.brand ? (
                    <li>
                      {t('homeChargerMetaBrand')}: <strong>{p.brand}</strong>
                    </li>
                  ) : null}
                </ul>
                <div className="home-charger-card__footer">
                  <p className="home-charger-card__price">{fmtMoney(p.price, p.currency, locale)}</p>
                  <a
                    className="home-charger-card__buy"
                    href={p.link}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t('homeChargerBuy')}
                  </a>
                </div>
              </div>
            </article>
          ))}
        </div>

        <p className="home-charger-partner">
          {t('homeChargerPartnerNote')}{' '}
          <a href="https://sparkschargers.com.ua/" target="_blank" rel="noopener noreferrer">
            sparkschargers.com.ua
          </a>
        </p>
      </div>
    </div>
  );
}
