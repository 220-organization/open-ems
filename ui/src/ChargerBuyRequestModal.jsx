import { useEffect, useRef, useState } from 'react';

const MIN_PHONE_LEN = 5;

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  return base ? `${base}${path}` : path;
}

/**
 * Buy request modal: the phone number is mandatory, support calls the client back.
 * `product` carries the selected charger (catalog, title, sku, price, links).
 */
export default function ChargerBuyRequestModal({ t, product, onClose }) {
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  const [showPhoneHint, setShowPhoneHint] = useState(false);
  const phoneInputRef = useRef(null);

  useEffect(() => {
    phoneInputRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = event => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  if (!product) return null;

  const trimmedPhone = phone.trim();
  const phoneOk = trimmedPhone.length >= MIN_PHONE_LEN;

  const submit = async event => {
    event.preventDefault();
    if (busy || sent) return;
    if (!phoneOk) {
      setShowPhoneHint(true);
      phoneInputRef.current?.focus();
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await fetch(apiUrl('/api/charger-buy-request'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          catalog: product.catalog,
          phone: trimmedPhone,
          name: name.trim() || null,
          title: product.title || null,
          sku: product.sku || null,
          price: product.price || null,
          page_url: product.pageUrl || null,
          product_url: product.productUrl || null,
        }),
      });
      if (!res.ok) throw new Error(`buy request ${res.status}`);
      setSent(true);
    } catch {
      setError(t('chargerBuyRequestFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="charger-buy-backdrop"
      role="presentation"
      onClick={event => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="charger-buy-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t('chargerBuyRequestTitle')}
      >
        <button
          type="button"
          className="charger-buy-modal__close"
          onClick={onClose}
          aria-label={t('chargerBuyRequestClose')}
        >
          ×
        </button>

        <h2 className="charger-buy-modal__title">{t('chargerBuyRequestTitle')}</h2>
        <p className="charger-buy-modal__product">{product.title}</p>
        {product.price ? <p className="charger-buy-modal__price">{product.price}</p> : null}

        {sent ? (
          <p className="charger-buy-modal__success" role="status">
            {t('chargerBuyRequestSuccess')}
          </p>
        ) : (
          <form className="charger-buy-modal__form" onSubmit={submit}>
            <label className="charger-buy-modal__label" htmlFor="charger-buy-phone">
              {t('chargerBuyRequestPhoneLabel')}
              <input
                ref={phoneInputRef}
                id="charger-buy-phone"
                className={`charger-buy-modal__input${
                  showPhoneHint && !phoneOk ? ' charger-buy-modal__input--invalid' : ''
                }`}
                type="tel"
                name="phone"
                inputMode="tel"
                autoComplete="tel"
                required
                value={phone}
                onChange={event => {
                  setPhone(event.target.value);
                  if (showPhoneHint) setShowPhoneHint(false);
                }}
                placeholder={t('chargerBuyRequestPhonePlaceholder')}
                aria-invalid={showPhoneHint && !phoneOk}
              />
            </label>

            <label className="charger-buy-modal__label" htmlFor="charger-buy-name">
              {t('chargerBuyRequestNameLabel')}
              <input
                id="charger-buy-name"
                className="charger-buy-modal__input"
                type="text"
                name="name"
                autoComplete="name"
                value={name}
                onChange={event => setName(event.target.value)}
                placeholder={t('chargerBuyRequestNamePlaceholder')}
              />
            </label>

            {showPhoneHint && !phoneOk ? (
              <p className="charger-buy-modal__hint" role="alert">
                {t('chargerBuyRequestPhoneRequired')}
              </p>
            ) : null}
            {error ? (
              <p className="charger-buy-modal__error" role="alert">
                {error}
              </p>
            ) : null}

            <button type="submit" className="charger-buy-modal__submit" disabled={busy}>
              {busy ? t('chargerBuyRequestBusy') : t('chargerBuyRequestSubmit')}
            </button>
            <p className="charger-buy-modal__note">{t('chargerBuyRequestNote')}</p>
          </form>
        )}
      </div>
    </div>
  );
}
