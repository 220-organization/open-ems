import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import PortStickerQrImage from './PortStickerQrImage';
import RoundedQrImage from './RoundedQrImage';
import { buildTelegramShareUrl, buildWhatsAppShareUrl } from './messengerContactUrls';

export default function SharePageModal({
  open,
  url,
  copied,
  copyFailed,
  onClose,
  t,
  qrSize = 256,
  qrVariant = 'rounded',
  showCopyStatus = true,
  shareText = '',
}) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !url) return null;

  const text = shareText || t('sharePageMessengerText') || '';
  const telegramHref = buildTelegramShareUrl(url, text);
  const whatsappHref = buildWhatsAppShareUrl(url, text);

  return createPortal(
    <div className="pf-messenger-scrim" role="presentation" onClick={onClose}>
      <div
        className="pf-messenger-dialog pf-share-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pf-share-page-title"
        onClick={e => e.stopPropagation()}
      >
        <div className="pf-messenger-panel pf-share-modal-panel">
          <h2 id="pf-share-page-title" className="pf-messenger-title">
            {t('sharePageModalTitle')}
          </h2>
          {showCopyStatus && copied ? <p className="pf-share-modal-status">{t('sharePageCopied')}</p> : null}
          {showCopyStatus && copyFailed ? (
            <p className="pf-share-modal-status pf-share-modal-status--error">{t('sharePageFailed')}</p>
          ) : null}
          {qrVariant === 'portSticker' ? (
            <div className="pf-share-modal-qr pf-share-modal-qr--port-sticker">
              <PortStickerQrImage url={url} size={qrSize} alt={t('sharePageQrAlt')} />
            </div>
          ) : (
            <RoundedQrImage
              className="pf-share-modal-qr"
              url={url}
              size={qrSize}
              alt={t('sharePageQrAlt')}
            />
          )}
          <p className="pf-share-modal-url">{url}</p>
          <div className="pf-share-modal-messengers" role="group" aria-label={t('sharePageMessengersAria')}>
            <a
              className="pf-share-modal-msg-btn pf-share-modal-msg-btn--telegram"
              href={telegramHref}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t('sharePageTelegram')}
            </a>
            <a
              className="pf-share-modal-msg-btn pf-share-modal-msg-btn--whatsapp"
              href={whatsappHref}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t('sharePageWhatsApp')}
            </a>
          </div>
          <div className="pf-roi-modal-actions pf-share-modal-actions">
            <button type="button" className="pf-roi-modal-btn pf-roi-modal-btn--primary" onClick={onClose}>
              {t('sharePageModalClose')}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
