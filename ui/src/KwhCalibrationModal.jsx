import { useEffect } from 'react';
import { createPortal } from 'react-dom';

export default function KwhCalibrationModal({ open, onConfirm, onDecline, t }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') onDecline();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onDecline]);

  if (!open) return null;

  return createPortal(
    <div className="pf-messenger-scrim" role="presentation" onClick={onDecline}>
      <div
        className="pf-messenger-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pf-kwh-calibration-title"
        onClick={e => e.stopPropagation()}
      >
        <div className="pf-messenger-panel">
          <h2 id="pf-kwh-calibration-title" className="pf-messenger-title">
            {t('kwhCalibrationTitle')}
          </h2>
          <p className="pf-kwh-calibration-message">{t('kwhCalibrationMessage')}</p>
          <div className="pf-roi-modal-actions">
            <button type="button" className="pf-roi-modal-btn pf-roi-modal-btn--primary" onClick={onConfirm}>
              {t('kwhCalibrationConfirm')}
            </button>
            <button type="button" className="pf-roi-modal-btn" onClick={onDecline}>
              {t('kwhCalibrationDecline')}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
