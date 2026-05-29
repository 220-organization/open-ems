import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';

function qrImageUrl(url) {
  const data = encodeURIComponent(String(url || '').trim());
  if (!data) return '';
  return `https://api.qrserver.com/v1/create-qr-code/?size=256x256&margin=10&data=${data}`;
}

export default function SharePageModal({ open, url, copied, copyFailed, onClose, t }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const qrSrc = useMemo(() => (open && url ? qrImageUrl(url) : ''), [open, url]);

  if (!open || !url) return null;

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
          {copied ? <p className="pf-share-modal-status">{t('sharePageCopied')}</p> : null}
          {copyFailed ? <p className="pf-share-modal-status pf-share-modal-status--error">{t('sharePageFailed')}</p> : null}
          {qrSrc ? (
            <img className="pf-share-modal-qr" src={qrSrc} width={256} height={256} alt={t('sharePageQrAlt')} />
          ) : null}
          <p className="pf-share-modal-url">{url}</p>
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
