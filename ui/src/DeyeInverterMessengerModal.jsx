import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { buildB2bTelegramUrl, buildB2bWhatsAppUrl } from './messengerContactUrls';

function TelegramIcon() {
  return (
    <svg width={32} height={32} viewBox="0 0 24 24" aria-hidden focusable="false">
      <path
        fill="currentColor"
        d="M21.95 2.05c-.27-.9-1.1-1.15-1.95-1L2.4 10.35c-.85.33-.8 1.08.05 1.38l5.15 1.7 1.95 6.35c.18.58.76.92 1.35.75.24-.07.45-.2.6-.38l2.75-2.25 4.75 3.5c.65.48 1.55.12 1.75-.7l3.05-14.5zM11.4 14.5l-.2 3.85-1.1-3.6-4.5-1.5 12.75-6.85L11.4 14.5z"
      />
    </svg>
  );
}

function WhatsAppIcon() {
  return (
    <svg width={32} height={32} viewBox="0 0 24 24" aria-hidden focusable="false">
      <path
        fill="currentColor"
        d="M17.5 14.4c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.65.07-.3-.15-1.26-.46-2.4-1.47-.89-.79-1.49-1.76-1.66-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.02-.52-.07-.15-.67-1.61-.92-2.2-.24-.58-.49-.5-.67-.51l-.57-.01c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48 0 1.46 1.06 2.88 1.21 3.08.15.2 2.1 3.2 5.08 4.49.71.31 1.26.49 1.69.62.71.23 1.36.2 1.87.12.57-.08 1.76-.72 2-1.41.25-.7.25-1.29.18-1.41-.07-.12-.27-.2-.57-.35zM12.04 2C6.58 2 2.2 6.38 2.2 11.84c0 1.9.5 3.75 1.45 5.38L2 22l4.67-1.22a9.86 9.86 0 005.37 1.58h.01c5.46 0 9.84-4.38 9.84-9.84C21.88 6.38 17.5 2 12.04 2zm0 17.67h-.01a7.82 7.82 0 01-3.98-1.1l-.29-.17-2.95.77.79-2.88-.18-.29a7.8 7.8 0 01-1.19-4.16c0-4.32 3.51-7.83 7.83-7.83s7.83 3.51 7.83 7.83-3.51 7.83-7.83 7.83z"
      />
    </svg>
  );
}

/**
 * Same pattern as 220-km.com/b2b messenger modal: Telegram / WhatsApp choice.
 */
export default function DeyeInverterMessengerModal({ open, onClose, t }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || typeof document === 'undefined') return null;

  const message = t('addDeyeMessengerPrefill');

  const openMessenger = (channel) => {
    const url =
      channel === 'telegram' ? buildB2bTelegramUrl(message) : buildB2bWhatsAppUrl(message);
    window.open(url, '_blank');
    onClose();
  };

  const node = (
    <div className="pf-messenger-scrim" role="presentation" onClick={onClose}>
      <div
        className="pf-messenger-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pf-add-deye-messenger-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pf-messenger-panel">
          <p id="pf-add-deye-messenger-title" className="pf-messenger-title">
            {t('addDeyeMessengerTitle')}
          </p>
          <div className="pf-messenger-actions">
            <button
              type="button"
              className="pf-messenger-icon-btn pf-messenger-icon-btn--telegram"
              aria-label={t('addDeyeMessengerTelegramAria')}
              onClick={() => openMessenger('telegram')}
            >
              <TelegramIcon />
            </button>
            <button
              type="button"
              className="pf-messenger-icon-btn pf-messenger-icon-btn--whatsapp"
              aria-label={t('addDeyeMessengerWhatsAppAria')}
              onClick={() => openMessenger('whatsapp')}
            >
              <WhatsAppIcon />
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(node, document.body);
}
