import { useOpenEmsSeo } from './useOpenEmsSeo';
import RdnConsultationCallback from './RdnConsultationCallback';
import './dam-chart.css';

export default function RdnConsultationPage({ t, locale, getBcp47Locale }) {
  useOpenEmsSeo(t('rdnCallbackPageLead').replace(/\.$/, ''), locale, t, {
    variant: 'landing',
    canonicalPath: '/rdn-consultation',
  });

  return (
    <div className="rdn-consult-page">
      <div className="rdn-consult-page__inner">
        <RdnConsultationCallback
          t={t}
          htmlIdPrefix="page-"
          rootClassName="rdn-consult-page__card"
          payOnly
          getBcp47Locale={getBcp47Locale}
        />
      </div>
    </div>
  );
}
