import './power-flow.css';
import './dam-chart.css';
import DamChartPanel from './DamChartPanel';
import RdnConsultationCallback from './RdnConsultationCallback';
import { useOpenEmsSeo } from './useOpenEmsSeo';

export default function DamChartPage({
  t,
  getBcp47Locale,
  locale,
  SUPPORTED,
  LOCALE_NAMES,
  onLangSelectChange,
}) {
  useOpenEmsSeo(t('damPageTitle'), locale, t);

  return (
    <div className="pf-body dam-page">
      <div className="pf-root dam-root">
        <DamChartPanel
          variant="fullpage"
          t={t}
          getBcp47Locale={getBcp47Locale}
          locale={locale}
          SUPPORTED={SUPPORTED}
          LOCALE_NAMES={LOCALE_NAMES}
          onLangSelectChange={onLangSelectChange}
        />
        <section className="pf-rdn-callback-section pf-rdn-callback-section--page-end" aria-label={t('rdnCallbackSectionAria')}>
          <RdnConsultationCallback t={t} />
        </section>
      </div>
    </div>
  );
}
