import { useState } from 'react';
import { buildB2bTelegramUrl, buildB2bWhatsAppUrl } from './messengerContactUrls';

const RDN_CONTACT_HASHTAG = '#ЗамовитиКонсультаціюПоРДН';

export default function RdnConsultationCallback({ t, htmlIdPrefix = '', rootClassName = '' }) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const nameId = `${htmlIdPrefix}rdn-callback-name`;
  const phoneId = `${htmlIdPrefix}rdn-callback-phone`;
  const rootClass = ['rdn-callback-card', rootClassName].filter(Boolean).join(' ');

  const trimmedName = name.trim();
  const trimmedPhone = phone.trim();
  const canSend = trimmedName.length >= 1 && trimmedPhone.length >= 5;

  const buildMessage = () => {
    const body = t('rdnCallbackMessageBody', { name: trimmedName, phone: trimmedPhone });
    return `${body}\n\n${RDN_CONTACT_HASHTAG}`;
  };

  const openMessenger = (channel) => {
    if (!canSend) return;
    const msg = buildMessage();
    const url =
      channel === 'telegram' ? buildB2bTelegramUrl(msg) : buildB2bWhatsAppUrl(msg);
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className={rootClass}>
      <h3 className="rdn-callback-card__title">{t('rdnCallbackFormTitle')}</h3>
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
      </div>
      <p className="rdn-callback-card__hint">{t('rdnCallbackMessengerHint')}</p>
      <div className="rdn-callback-card__actions">
        <button
          type="button"
          className="rdn-callback-card__btn rdn-callback-card__btn--telegram"
          disabled={!canSend}
          aria-label={t('rdnCallbackTelegramAria')}
          onClick={() => openMessenger('telegram')}
        >
          {t('rdnCallbackTelegramBtn')}
        </button>
        <button
          type="button"
          className="rdn-callback-card__btn rdn-callback-card__btn--whatsapp"
          disabled={!canSend}
          aria-label={t('rdnCallbackWhatsAppAria')}
          onClick={() => openMessenger('whatsapp')}
        >
          {t('rdnCallbackWhatsAppBtn')}
        </button>
      </div>
    </div>
  );
}
