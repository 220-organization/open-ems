import { useEffect, useRef, useState } from 'react';
import { buildB2bTelegramUrl, buildB2bWhatsAppUrl } from './messengerContactUrls';
import './dam-chart.css';

const RDN_CONTACT_HASHTAG = '#ЗамовитиКонсультаціюПоРДН';
const RDN_PAY_HASHTAG = '#ОплатаКонсультаціїПоРДН';
const PAY_AMOUNTS_UAH = [2200, 4400, 8800];
const DRAFT_STORAGE_KEY = 'rdnConsultPayDraft';
const PAYMENT_QUERY_KEY = 'rdnConsultPayment';

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  if (!base) return path;
  return `${base}${path}`;
}

function formatPaymentTime(date = new Date()) {
  try {
    return new Intl.DateTimeFormat('uk-UA', {
      timeZone: 'Europe/Kyiv',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(date);
  } catch {
    return date.toISOString();
  }
}

function readDraft() {
  try {
    const raw = sessionStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeDraft(draft) {
  try {
    sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
  } catch {
    /* ignore quota / private mode */
  }
}

function clearDraft() {
  try {
    sessionStorage.removeItem(DRAFT_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

function takePaymentIdFromUrl() {
  if (typeof window === 'undefined') return null;
  const url = new URL(window.location.href);
  const paymentId = (url.searchParams.get(PAYMENT_QUERY_KEY) || '').trim();
  if (!paymentId) return null;
  url.searchParams.delete(PAYMENT_QUERY_KEY);
  const next = `${url.pathname}${url.search}${url.hash}`;
  window.history.replaceState({}, '', next);
  return paymentId;
}

function buildRedirectUrl() {
  const url = new URL(window.location.href);
  url.searchParams.delete(PAYMENT_QUERY_KEY);
  return url.toString();
}

function isLocalhostDev() {
  if (typeof window === 'undefined') return false;
  const { hostname } = window.location;
  return hostname === 'localhost' || hostname === '127.0.0.1';
}

export default function RdnConsultationCallback({ t, htmlIdPrefix = '', rootClassName = '' }) {
  const [mode, setMode] = useState('callback'); // 'callback' | 'pay'
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [amountUah, setAmountUah] = useState(PAY_AMOUNTS_UAH[0]);
  const [paidAmountUah, setPaidAmountUah] = useState(null);
  const [paymentTime, setPaymentTime] = useState('');
  const [payBusy, setPayBusy] = useState(false);
  const [payError, setPayError] = useState('');
  const [statusNote, setStatusNote] = useState('');
  const autoOpenedRef = useRef(false);

  const nameId = `${htmlIdPrefix}rdn-callback-name`;
  const phoneId = `${htmlIdPrefix}rdn-callback-phone`;
  const amountGroupId = `${htmlIdPrefix}rdn-callback-amount`;
  const rootClass = ['rdn-callback-card', rootClassName].filter(Boolean).join(' ');

  const trimmedName = name.trim();
  const trimmedPhone = phone.trim();
  const canSend = trimmedName.length >= 1 && trimmedPhone.length >= 5;
  const isPaid = paidAmountUah != null && paymentTime;

  const buildMessage = () => {
    if (isPaid) {
      const body = t('rdnCallbackPaidMessageBody', {
        name: trimmedName,
        phone: trimmedPhone,
        amount: paidAmountUah,
        paymentTime,
      });
      return `${body}\n\n${RDN_PAY_HASHTAG}`;
    }
    const body = t('rdnCallbackMessageBody', { name: trimmedName, phone: trimmedPhone });
    return `${body}\n\n${RDN_CONTACT_HASHTAG}`;
  };

  const openMessenger = (channel) => {
    if (!canSend) return;
    if (mode === 'pay' && !isPaid) return;
    const msg = buildMessage();
    const url =
      channel === 'telegram' ? buildB2bTelegramUrl(msg) : buildB2bWhatsAppUrl(msg);
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  useEffect(() => {
    const paymentId = takePaymentIdFromUrl();
    if (!paymentId) return undefined;

    const draft = readDraft();
    if (draft?.name) setName(String(draft.name));
    if (draft?.phone) setPhone(String(draft.phone));
    if (draft?.amountUah && PAY_AMOUNTS_UAH.includes(Number(draft.amountUah))) {
      setAmountUah(Number(draft.amountUah));
    }
    setMode('pay');
    setStatusNote(t('rdnCallbackPayChecking'));
    setPayError('');

    let cancelled = false;
    let attempts = 0;

    const finishSuccess = (amount, nameValue, phoneValue) => {
      const paidAt = formatPaymentTime();
      setPaidAmountUah(amount);
      setPaymentTime(paidAt);
      if (nameValue) setName(nameValue);
      if (phoneValue) setPhone(phoneValue);
      setStatusNote(t('rdnCallbackPaySuccess'));
      clearDraft();
      if (!autoOpenedRef.current) {
        autoOpenedRef.current = true;
        const msg = `${t('rdnCallbackPaidMessageBody', {
          name: (nameValue || draft?.name || '').trim(),
          phone: (phoneValue || draft?.phone || '').trim(),
          amount,
          paymentTime: paidAt,
        })}\n\n${RDN_PAY_HASHTAG}`;
        window.open(buildB2bTelegramUrl(msg), '_blank', 'noopener,noreferrer');
      }
    };

    const poll = async () => {
      attempts += 1;
      try {
        let data = null;
        const res = await fetch(apiUrl(`/api/rdn-consultation/payments/${encodeURIComponent(paymentId)}`), {
          cache: 'no-store',
        });
        if (res.ok) {
          data = await res.json();
        } else if (draft?.invoiceId && draft?.amountUah) {
          const fallback = await fetch(apiUrl('/api/rdn-consultation/invoice-status'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              invoice_id: draft.invoiceId,
              amount_uah: Number(draft.amountUah),
              name: draft.name || null,
              phone: draft.phone || null,
            }),
          });
          if (!fallback.ok) throw new Error(`status ${fallback.status}`);
          data = await fallback.json();
        } else {
          throw new Error(`status ${res.status}`);
        }
        if (cancelled) return;
        const status = String(data.status || '').toUpperCase();
        if (status === 'SUCCESS') {
          finishSuccess(
            Number(data.amount_uah) || Number(draft?.amountUah) || amountUah,
            data.name || draft?.name,
            data.phone || draft?.phone,
          );
          return;
        }
        if (['FAILURE', 'EXPIRED', 'REVERSED'].includes(status)) {
          setPayError(t('rdnCallbackPayFailed'));
          setStatusNote('');
          return;
        }
      } catch {
        if (cancelled) return;
        if (attempts >= 8) {
          setPayError(t('rdnCallbackPayFailed'));
          setStatusNote('');
          return;
        }
      }
      if (!cancelled && attempts < 12) {
        window.setTimeout(poll, 2000);
      } else if (!cancelled) {
        setPayError(t('rdnCallbackPayProcessing'));
        setStatusNote('');
      }
    };

    poll();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount for redirect return
  }, []);

  const applyPaidSuccess = (amount, nameValue, phoneValue) => {
    const paidAt = formatPaymentTime();
    const finalName = (nameValue || trimmedName || '').trim();
    const finalPhone = (phoneValue || trimmedPhone || '').trim();
    setPaidAmountUah(amount);
    setPaymentTime(paidAt);
    if (finalName) setName(finalName);
    if (finalPhone) setPhone(finalPhone);
    setStatusNote(t('rdnCallbackPaySuccess'));
    clearDraft();
    if (!autoOpenedRef.current) {
      autoOpenedRef.current = true;
      const msg = `${t('rdnCallbackPaidMessageBody', {
        name: finalName,
        phone: finalPhone,
        amount,
        paymentTime: paidAt,
      })}\n\n${RDN_PAY_HASHTAG}`;
      window.open(buildB2bTelegramUrl(msg), '_blank', 'noopener,noreferrer');
    }
  };

  const startPayment = async () => {
    if (!canSend || payBusy) return;
    setPayBusy(true);
    setPayError('');
    setStatusNote('');
    writeDraft({ name: trimmedName, phone: trimmedPhone, amountUah });
    try {
      const res = await fetch(apiUrl('/api/rdn-consultation/pay'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount_uah: amountUah,
          redirect_url: buildRedirectUrl(),
          name: trimmedName,
          phone: trimmedPhone,
        }),
      });
      if (!res.ok) {
        throw new Error(`pay ${res.status}`);
      }
      const data = await res.json();
      if (!data?.page_url) {
        throw new Error('missing page_url');
      }
      writeDraft({
        name: trimmedName,
        phone: trimmedPhone,
        amountUah,
        paymentId: data.payment_id,
        invoiceId: data.invoice_id,
      });
      window.location.assign(data.page_url);
    } catch {
      setPayError(t('rdnCallbackPayFailed'));
      setPayBusy(false);
    }
  };

  const skipPaymentTest = async () => {
    if (!canSend || payBusy || !isLocalhostDev()) return;
    setPayBusy(true);
    setPayError('');
    setStatusNote(t('rdnCallbackPayChecking'));
    try {
      const res = await fetch(apiUrl('/api/rdn-consultation/pay-test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount_uah: amountUah,
          name: trimmedName,
          phone: trimmedPhone,
        }),
      });
      if (!res.ok) {
        throw new Error(`pay-test ${res.status}`);
      }
      const data = await res.json();
      if (String(data.status || '').toUpperCase() !== 'SUCCESS') {
        throw new Error('pay-test not success');
      }
      applyPaidSuccess(
        Number(data.amount_uah) || amountUah,
        data.name || trimmedName,
        data.phone || trimmedPhone,
      );
    } catch {
      setPayError(t('rdnCallbackPayFailed'));
      setStatusNote('');
    } finally {
      setPayBusy(false);
    }
  };

  const messengerEnabled = canSend && (mode === 'callback' || isPaid);
  const showLocalTestSkip = isLocalhostDev() && mode === 'pay' && !isPaid;

  return (
    <div className={rootClass}>
      <h3 className="rdn-callback-card__title">{t('rdnCallbackFormTitle')}</h3>

      <div className="rdn-callback-card__mode" role="group" aria-label={t('rdnCallbackModeAria')}>
        <button
          type="button"
          className={`rdn-callback-card__mode-btn${mode === 'callback' ? ' is-active' : ''}`}
          aria-pressed={mode === 'callback'}
          onClick={() => {
            setMode('callback');
            setPayError('');
            setStatusNote('');
          }}
        >
          {t('rdnCallbackModeCallback')}
        </button>
        <button
          type="button"
          className={`rdn-callback-card__mode-btn${mode === 'pay' ? ' is-active' : ''}`}
          aria-pressed={mode === 'pay'}
          onClick={() => {
            setMode('pay');
            setPayError('');
          }}
        >
          {t('rdnCallbackModePay')}
        </button>
      </div>

      <div className="rdn-callback-card__fields">
        <label className="rdn-callback-card__label" htmlFor={nameId}>
          {t('rdnCallbackNameLabel')}
          <input
            id={nameId}
            className="rdn-callback-card__input"
            type="text"
            name="name"
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('rdnCallbackNamePlaceholder')}
          />
        </label>
        <label className="rdn-callback-card__label" htmlFor={phoneId}>
          {t('rdnCallbackPhoneLabel')}
          <input
            id={phoneId}
            className="rdn-callback-card__input"
            type="tel"
            name="phone"
            autoComplete="tel"
            inputMode="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder={t('rdnCallbackPhonePlaceholder')}
          />
        </label>

        {mode === 'pay' && !isPaid ? (
          <fieldset className="rdn-callback-card__amounts" id={amountGroupId}>
            <legend className="rdn-callback-card__amounts-legend">{t('rdnCallbackAmountLabel')}</legend>
            <div className="rdn-callback-card__amount-options">
              {PAY_AMOUNTS_UAH.map((uah) => {
                const id = `${htmlIdPrefix}rdn-amount-${uah}`;
                return (
                  <label key={uah} className="rdn-callback-card__amount-option" htmlFor={id}>
                    <input
                      id={id}
                      type="radio"
                      name={`${htmlIdPrefix}rdn-consult-amount`}
                      value={uah}
                      checked={amountUah === uah}
                      onChange={() => setAmountUah(uah)}
                    />
                    <span>{t('rdnCallbackAmountOption', { amount: uah })}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        ) : null}

        {isPaid ? (
          <p className="rdn-callback-card__paid-summary" role="status">
            {t('rdnCallbackPaidSummary', { amount: paidAmountUah, paymentTime })}
          </p>
        ) : null}
      </div>

      {mode === 'callback' ? (
        <p className="rdn-callback-card__hint">{t('rdnCallbackMessengerHint')}</p>
      ) : isPaid ? (
        <p className="rdn-callback-card__hint">{t('rdnCallbackPayMessengerHint')}</p>
      ) : (
        <p className="rdn-callback-card__hint">{t('rdnCallbackPayHint')}</p>
      )}

      {statusNote ? (
        <p className="rdn-callback-card__status" role="status">
          {statusNote}
        </p>
      ) : null}
      {payError ? (
        <p className="rdn-callback-card__error" role="alert">
          {payError}
        </p>
      ) : null}

      {mode === 'pay' && !isPaid ? (
        <div className="rdn-callback-card__actions rdn-callback-card__actions--pay">
          <button
            type="button"
            className="rdn-callback-card__btn rdn-callback-card__btn--pay"
            disabled={!canSend || payBusy}
            aria-label={t('rdnCallbackPayAria', { amount: amountUah })}
            onClick={startPayment}
          >
            {payBusy
              ? t('rdnCallbackPayBusy')
              : t('rdnCallbackPayBtn', { amount: amountUah })}
          </button>
          {showLocalTestSkip ? (
            <button
              type="button"
              className="rdn-callback-card__btn rdn-callback-card__btn--pay-test"
              disabled={!canSend || payBusy}
              onClick={skipPaymentTest}
            >
              {t('rdnCallbackPayTestSkip')}
            </button>
          ) : null}
        </div>
      ) : (
        <div className="rdn-callback-card__actions">
          <button
            type="button"
            className="rdn-callback-card__btn rdn-callback-card__btn--telegram"
            disabled={!messengerEnabled}
            aria-label={t('rdnCallbackTelegramAria')}
            onClick={() => openMessenger('telegram')}
          >
            {t('rdnCallbackTelegramBtn')}
          </button>
          <button
            type="button"
            className="rdn-callback-card__btn rdn-callback-card__btn--whatsapp"
            disabled={!messengerEnabled}
            aria-label={t('rdnCallbackWhatsAppAria')}
            onClick={() => openMessenger('whatsapp')}
          >
            {t('rdnCallbackWhatsAppBtn')}
          </button>
        </div>
      )}
    </div>
  );
}
