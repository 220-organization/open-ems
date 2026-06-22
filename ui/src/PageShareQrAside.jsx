import { useMemo } from 'react';
import { qrImageUrl } from './sharePageQr';

/** Inline QR linking to the current page (station, language, inverter in URL). */
export default function PageShareQrAside({ url, t, className = '', compact = false, showCaption = true }) {
  const qrSrc = useMemo(
    () => (url ? qrImageUrl(url, compact ? 128 : 180, compact ? 1 : 8, compact ? '00000000' : 'ffffff') : ''),
    [url, compact],
  );
  if (!url || !qrSrc) return null;

  const inlineOnly = compact && !showCaption;
  const qrSize = compact ? 52 : 120;

  if (inlineOnly) {
    return (
      <a
        className="pf-node pf-node--page-qr"
        data-pos="bottom-center"
        href={url}
        aria-label={t('pageShareQrAsideAria')}
      >
        <img src={qrSrc} width={qrSize} height={qrSize} alt={t('pageShareQrAlt')} decoding="async" loading="lazy" />
      </a>
    );
  }

  const rootClass = ['pf-qr-aside', 'pf-page-share-qr', className].filter(Boolean).join(' ');

  return (
    <aside className={rootClass} aria-label={t('pageShareQrAsideAria')}>
      <a className="pf-qr-aside-link" href={url} aria-label={t('pageShareQrAsideAria')}>
        <img
          className="pf-qr-aside-img"
          src={qrSrc}
          width={qrSize}
          height={qrSize}
          alt={t('pageShareQrAlt')}
          decoding="async"
          loading="lazy"
        />
        {showCaption ? <span className="pf-qr-aside-caption">{t('pageShareQrCaption')}</span> : null}
      </a>
    </aside>
  );
}
