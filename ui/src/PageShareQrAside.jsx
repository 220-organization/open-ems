import RoundedQrImage from './RoundedQrImage';

/** Inline QR linking to the current page (station, language, inverter in URL). */
export default function PageShareQrAside({ url, t, className = '', compact = false, showCaption = true }) {
  if (!url) return null;

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
        <RoundedQrImage url={url} size={qrSize} color="#dad1e6" alt={t('pageShareQrAlt')} />
      </a>
    );
  }

  const rootClass = ['pf-qr-aside', 'pf-page-share-qr', className].filter(Boolean).join(' ');

  return (
    <aside className={rootClass} aria-label={t('pageShareQrAsideAria')}>
      <a className="pf-qr-aside-link" href={url} aria-label={t('pageShareQrAsideAria')}>
        <RoundedQrImage
          className="pf-qr-aside-img"
          url={url}
          size={qrSize}
          color="#dad1e6"
          alt={t('pageShareQrAlt')}
        />
        {showCaption ? <span className="pf-qr-aside-caption">{t('pageShareQrCaption')}</span> : null}
      </a>
    </aside>
  );
}
