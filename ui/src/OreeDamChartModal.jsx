import { useEffect } from 'react';
import { createPortal } from 'react-dom';

/** Public OREE page with day-ahead market results (same path as 220-km b2b OREE widget). */
export const OREE_DAM_CHART_URL =
  'https://www.oree.com.ua/index.php/control/results_mo/DAM';

/**
 * Full-screen style dialog embedding the official OREE DAM chart page.
 */
export default function OreeDamChartModal({ open, onClose, t }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    <div className="dam-oree-modal-scrim" role="presentation" onClick={onClose}>
      <div
        className="dam-oree-modal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dam-oree-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dam-oree-modal-header">
          <h2 id="dam-oree-modal-title" className="dam-oree-modal-title">
            {t('damOreeChartModalTitle')}
          </h2>
          <button
            type="button"
            className="dam-oree-modal-close"
            onClick={onClose}
            aria-label={t('damOreeChartModalClose')}
          >
            ×
          </button>
        </div>
        <div className="dam-oree-modal-frame-wrap">
          <iframe
            title={t('damOreeChartIframeTitle')}
            src={OREE_DAM_CHART_URL}
            className="dam-oree-modal-iframe"
            referrerPolicy="no-referrer-when-downgrade"
          />
        </div>
        <p className="dam-oree-modal-footer">
          <a
            href={OREE_DAM_CHART_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="dam-oree-modal-external"
          >
            {t('damOreeChartOpenNewTab')}
          </a>
        </p>
      </div>
    </div>,
    document.body
  );
}
