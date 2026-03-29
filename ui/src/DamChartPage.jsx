import { useEffect } from 'react';
import './power-flow.css';
import './dam-chart.css';
import DamChartPanel from './DamChartPanel';

export default function DamChartPage({
  t,
  getBcp47Locale,
  locale,
  SUPPORTED,
  LOCALE_NAMES,
  onLangSelectChange,
}) {
  useEffect(() => {
    document.title = t('damPageTitle');
    document.documentElement.lang = locale === 'uk' ? 'uk' : locale;
  }, [t, locale]);

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
      </div>
    </div>
  );
}
