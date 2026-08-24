import { useOpenEmsSeo } from './useOpenEmsSeo';
import RdnConsultationCallback from './RdnConsultationCallback';
import './dam-chart.css';

export default function RdnConsultationPage({ t, locale }) {
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
        />
      </div>
    </div>
  );
}
