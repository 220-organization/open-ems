import { useEffect, useRef, useState } from 'react';
import { OPEN_EMS_ROUTES } from './openEmsRoutes';
import './dam-chart.css';

const MIN_AMOUNT_UAH = 200;
const MAX_AMOUNT_UAH = 20_000;
const AMOUNT_STEP_UAH = 100;
const DEFAULT_AMOUNT_UAH = 2200;
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
  const url = new URL(OPEN_EMS_ROUTES.rdnConsultation, window.location.origin);
  return url.toString();
}

function isLocalhostDev() {
  if (typeof window === 'undefined') return false;
  const { hostname } = window.location;
  return hostname === 'localhost' || hostname === '127.0.0.1';
}

function parseAmountUah(raw) {
  const n = Number.parseInt(String(raw ?? '').trim(), 10);
  if (!Number.isFinite(n)) return null;
  return n;
}

function snapAmountUah(amount) {
  if (!Number.isFinite(amount)) return null;
  const snapped = Math.round(amount / AMOUNT_STEP_UAH) * AMOUNT_STEP_UAH;
  return Math.min(MAX_AMOUNT_UAH, Math.max(MIN_AMOUNT_UAH, snapped));
}

function isValidAmountUah(amount) {
  return (
    Number.isFinite(amount) &&
    amount >= MIN_AMOUNT_UAH &&
    amount <= MAX_AMOUNT_UAH &&
    amount % AMOUNT_STEP_UAH === 0
  );
}

export default function RdnConsultationCallback({
  t,
  htmlIdPrefix = '',
  rootClassName = '',
  payOnly = false,
}) {
  const [mode, setMode] = useState('pay'); // 'callback' | 'pay'
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [amountText, setAmountText] = useState(String(DEFAULT_AMOUNT_UAH));
  const [paidAmountUah, setPaidAmountUah] = useState(null);
  const [paymentTime, setPaymentTime] = useState('');
  const [payBusy, setPayBusy] = useState(false);
  const [payError, setPayError] = useState('');
  const [formHint, setFormHint] = useState('');
  const [statusNote, setStatusNote] = useState('');
  const [highlightContact, setHighlightContact] = useState(false);
  const [callbackSent, setCallbackSent] = useState(false);
  const [callbackBusy, setCallbackBusy] = useState(false);
  const nameInputRef = useRef(null);
  const phoneInputRef = useRef(null);
  const amountInputRef = useRef(null);

  const nameId = `${htmlIdPrefix}rdn-callback-name`;
  const phoneId = `${htmlIdPrefix}rdn-callback-phone`;
  const amountId = `${htmlIdPrefix}rdn-callback-amount`;
  const rootClass = ['rdn-callback-card', rootClassName].filter(Boolean).join(' ');
  const effectiveMode = payOnly ? 'pay' : mode;

  const trimmedName = name.trim();
  const trimmedPhone = phone.trim();
  const nameOk = trimmedName.length >= 1;
  const phoneOk = trimmedPhone.length >= 5;
  const canSend = nameOk && phoneOk;
  const isPaid = paidAmountUah != null && paymentTime;
  const amountUah = parseAmountUah(amountText);
  const amountOk = isValidAmountUah(amountUah);
  const sliderValue = snapAmountUah(amountUah) ?? DEFAULT_AMOUNT_UAH;

  const setAmountFromUi = (raw) => {
    const parsed = parseAmountUah(raw);
    if (parsed == null) {
      setAmountText(typeof raw === 'string' ? raw : '');
      return;
    }
    const snapped = snapAmountUah(parsed);
    setAmountText(String(snapped));
  };

  const focusFieldsToFill = () => {
    setHighlightContact(true);
    setFormHint(t('rdnCallbackFillNamePhoneHint'));
    setPayError('');
    window.requestAnimationFrame(() => {
      if (!nameOk) {
        nameInputRef.current?.focus();
        return;
      }
      if (!phoneOk) {
        phoneInputRef.current?.focus();
      }
    });
  };

  const submitCallback = async () => {
    if (callbackBusy || callbackSent) return;
    if (!canSend) {
      focusFieldsToFill();
      return;
    }
    setFormHint('');
    setHighlightContact(false);
    setPayError('');
    setCallbackBusy(true);
    try {
      const res = await fetch(apiUrl('/api/rdn-consultation/callback'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmedName, phone: trimmedPhone }),
      });
      if (!res.ok) {
        throw new Error(`callback ${res.status}`);
      }
      setCallbackSent(true);
    } catch {
      setPayError(t('rdnCallbackSubmitFailed'));
    } finally {
      setCallbackBusy(false);
    }
  };

  useEffect(() => {
    const paymentId = takePaymentIdFromUrl();
    if (!paymentId) return undefined;

    const draft = readDraft();
    if (draft?.name) setName(String(draft.name));
    if (draft?.phone) setPhone(String(draft.phone));
    if (draft?.amountUah != null && isValidAmountUah(Number(draft.amountUah))) {
      setAmountText(String(Number(draft.amountUah)));
    }
    setMode('pay');
    setStatusNote(t('rdnCallbackPayChecking'));
    setPayError('');
    setFormHint('');

    let cancelled = false;
    let attempts = 0;

    const finishSuccess = (amount, nameValue, phoneValue) => {
      const paidAt = formatPaymentTime();
      setPaidAmountUah(amount);
      setPaymentTime(paidAt);
      if (nameValue) setName(nameValue);
      if (phoneValue) setPhone(phoneValue);
      setStatusNote('');
      clearDraft();
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
    setStatusNote('');
    clearDraft();
  };

  const startPayment = async () => {
    if (payBusy) return;
    if (!canSend) {
      focusFieldsToFill();
      return;
    }
    if (!amountOk) {
      setHighlightContact(false);
      setFormHint(t('rdnCallbackAmountInvalidHint', { min: MIN_AMOUNT_UAH, max: MAX_AMOUNT_UAH }));
      setPayError('');
      window.requestAnimationFrame(() => amountInputRef.current?.focus());
      return;
    }
    setFormHint('');
    setHighlightContact(false);
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
    if (payBusy || !isLocalhostDev()) return;
    if (!canSend) {
      focusFieldsToFill();
      return;
    }
    if (!amountOk) {
      setHighlightContact(false);
      setFormHint(t('rdnCallbackAmountInvalidHint', { min: MIN_AMOUNT_UAH, max: MAX_AMOUNT_UAH }));
      window.requestAnimationFrame(() => amountInputRef.current?.focus());
      return;
    }
    setFormHint('');
    setHighlightContact(false);
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

  const showLocalTestSkip = isLocalhostDev() && effectiveMode === 'pay' && !isPaid;

  return (
    <div className={rootClass}>
      <h3 className="rdn-callback-card__title">
        {payOnly ? t('rdnCallbackPageLead').replace(/\.$/, '') : t('rdnCallbackFormTitle')}
      </h3>

      {payOnly ? null : (
        <div className="rdn-callback-card__mode" role="group" aria-label={t('rdnCallbackModeAria')}>
          <button
            type="button"
            className={`rdn-callback-card__mode-btn${mode === 'callback' ? ' is-active' : ''}`}
            aria-pressed={mode === 'callback'}
            onClick={() => {
              setMode('callback');
              setPayError('');
              setStatusNote('');
              setFormHint('');
              setHighlightContact(false);
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
              setFormHint('');
              setHighlightContact(false);
            }}
          >
            {t('rdnCallbackModePay')}
          </button>
        </div>
      )}

      <div className="rdn-callback-card__fields">
        <label className="rdn-callback-card__label" htmlFor={nameId}>
          {t('rdnCallbackNameLabel')}
          <input
            ref={nameInputRef}
            id={nameId}
            className={`rdn-callback-card__input${
              highlightContact && !nameOk ? ' rdn-callback-card__input--needs-fill' : ''
            }`}
            type="text"
            name="name"
            autoComplete="name"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (formHint) setFormHint('');
              if (highlightContact && e.target.value.trim().length >= 1 && phoneOk) {
                setHighlightContact(false);
              }
            }}
            placeholder={t('rdnCallbackNamePlaceholder')}
            aria-invalid={highlightContact && !nameOk}
          />
        </label>
        <label className="rdn-callback-card__label" htmlFor={phoneId}>
          {t('rdnCallbackPhoneLabel')}
          <input
            ref={phoneInputRef}
            id={phoneId}
            className={`rdn-callback-card__input${
              highlightContact && !phoneOk ? ' rdn-callback-card__input--needs-fill' : ''
            }`}
            type="tel"
            name="phone"
            autoComplete="tel"
            inputMode="tel"
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value);
              if (formHint) setFormHint('');
              if (highlightContact && nameOk && e.target.value.trim().length >= 5) {
                setHighlightContact(false);
              }
            }}
            placeholder={t('rdnCallbackPhonePlaceholder')}
            aria-invalid={highlightContact && !phoneOk}
          />
        </label>

        {effectiveMode === 'pay' && !isPaid ? (
          <div className="rdn-callback-card__amount-block">
            <label className="rdn-callback-card__label" htmlFor={amountId}>
              {t('rdnCallbackCustomAmountLabel')}
              <input
                ref={amountInputRef}
                id={amountId}
                className={`rdn-callback-card__input${
                  formHint && !amountOk && !highlightContact ? ' rdn-callback-card__input--needs-fill' : ''
                }`}
                type="number"
                name="amountUah"
                inputMode="numeric"
                min={MIN_AMOUNT_UAH}
                max={MAX_AMOUNT_UAH}
                step={AMOUNT_STEP_UAH}
                value={amountText}
                onChange={(e) => {
                  setAmountText(e.target.value);
                  if (formHint) setFormHint('');
                }}
                onBlur={() => {
                  if (amountText.trim() === '') return;
                  const snapped = snapAmountUah(parseAmountUah(amountText));
                  if (snapped != null) setAmountText(String(snapped));
                }}
                placeholder={t('rdnCallbackCustomAmountPlaceholder')}
                aria-invalid={Boolean(formHint) && !amountOk && !highlightContact}
              />
            </label>
            <label className="rdn-callback-card__amount-slider-label" htmlFor={`${amountId}-slider`}>
              <span className="rdn-callback-card__amount-slider-range" aria-hidden="true">
                <span>{MIN_AMOUNT_UAH}</span>
                <span>{MAX_AMOUNT_UAH}</span>
              </span>
              <input
                id={`${amountId}-slider`}
                className="rdn-callback-card__amount-slider"
                type="range"
                min={MIN_AMOUNT_UAH}
                max={MAX_AMOUNT_UAH}
                step={AMOUNT_STEP_UAH}
                value={sliderValue}
                aria-valuemin={MIN_AMOUNT_UAH}
                aria-valuemax={MAX_AMOUNT_UAH}
                aria-valuenow={sliderValue}
                aria-label={t('rdnCallbackAmountSliderAria', {
                  amount: sliderValue,
                  min: MIN_AMOUNT_UAH,
                  max: MAX_AMOUNT_UAH,
                })}
                onChange={(e) => {
                  setAmountFromUi(e.target.value);
                  if (formHint) setFormHint('');
                }}
              />
            </label>
          </div>
        ) : null}

        {isPaid ? (
          <p className="rdn-callback-card__paid-summary" role="status">
            {t('rdnCallbackPaidSummary')}
          </p>
        ) : null}
        {callbackSent && effectiveMode === 'callback' && !isPaid ? (
          <p className="rdn-callback-card__paid-summary" role="status">
            {t('rdnCallbackSubmitSuccess')}
          </p>
        ) : null}
      </div>

      {isPaid ? null : effectiveMode === 'callback' ? (
        callbackSent ? null : (
          <p className="rdn-callback-card__hint">{t('rdnCallbackSubmitHint')}</p>
        )
      ) : (
        <p className="rdn-callback-card__hint">{t('rdnCallbackPayHint')}</p>
      )}

      {formHint ? (
        <p className="rdn-callback-card__form-hint" role="alert">
          {formHint}
        </p>
      ) : null}
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

      {isPaid ? null : effectiveMode === 'pay' ? (
        <div className="rdn-callback-card__actions rdn-callback-card__actions--pay">
          <button
            type="button"
            className="rdn-callback-card__btn rdn-callback-card__btn--pay"
            disabled={payBusy}
            aria-label={
              amountOk
                ? t('rdnCallbackPayAria', { amount: amountUah })
                : t('rdnCallbackModePay')
            }
            onClick={startPayment}
          >
            {payBusy
              ? t('rdnCallbackPayBusy')
              : amountOk
                ? t('rdnCallbackPayBtn', { amount: amountUah })
                : t('rdnCallbackPayBtnEmpty')}
          </button>
          {showLocalTestSkip ? (
            <button
              type="button"
              className="rdn-callback-card__btn rdn-callback-card__btn--pay-test"
              disabled={payBusy}
              onClick={skipPaymentTest}
            >
              {t('rdnCallbackPayTestSkip')}
            </button>
          ) : null}
        </div>
      ) : effectiveMode === 'callback' && !callbackSent ? (
        <div className="rdn-callback-card__actions rdn-callback-card__actions--pay">
          <button
            type="button"
            className="rdn-callback-card__btn rdn-callback-card__btn--pay"
            disabled={callbackBusy}
            aria-label={t('rdnCallbackSubmitAria')}
            onClick={submitCallback}
          >
            {callbackBusy ? t('rdnCallbackSubmitBusy') : t('rdnCallbackSubmitBtn')}
          </button>
        </div>
      ) : null}
    </div>
  );
}
