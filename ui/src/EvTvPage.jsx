import './landing.css';
import { useOpenEmsSeo } from './useOpenEmsSeo';
import { useTheme } from './useTheme';

const EV_TV_APK_PATH = '/download/ev-ua-android-tv-1.5.0-98.apk';
const EV_TV_PDF_PATH = '/download/ev-ua-tv.pdf';

const SECTION_KEYS = [
  { title: 'evTvProblemTitle', text: 'evTvProblemText' },
  { title: 'evTvSolutionTitle', text: 'evTvSolutionText' },
  { title: 'evTvSetupTitle', text: 'evTvSetupText', list: ['evTvSetupStep1', 'evTvSetupStep2', 'evTvSetupStep3'] },
  { title: 'evTvDataTitle', text: 'evTvDataText' },
  { title: 'evTvCostTitle', text: 'evTvCostText', list: ['evTvCostItem1', 'evTvCostItem2', 'evTvCostItem3'] },
];

export default function EvTvPage({ t, locale }) {
  useTheme();
  useOpenEmsSeo(t('evTvPageTitle'), locale, t, { variant: 'landing', canonicalPath: '/ev-tv' });

  return (
    <div className="landing-page">
      <main className="landing-main">
        <section className="landing-hero" aria-labelledby="ev-tv-hero-title">
          <h1 id="ev-tv-hero-title" className="landing-hero__title">
            {t('evTvHeroTitle')}
          </h1>
          <p className="landing-hero__subtitle">{t('evTvHeroSubtitle')}</p>
          <div className="landing-hero__cta ev-tv-downloads">
            <a className="landing-btn landing-btn--primary" href={EV_TV_APK_PATH} download>
              {t('evTvDownloadApk')}
            </a>
            <a className="landing-btn landing-btn--secondary" href={EV_TV_PDF_PATH} target="_blank" rel="noopener noreferrer">
              {t('evTvDownloadPdf')}
            </a>
          </div>
          <p className="ev-tv-downloads__meta">{t('evTvDownloadApkVersion')}</p>
        </section>

        {SECTION_KEYS.map(section => (
          <section key={section.title} className="landing-section" aria-labelledby={section.title}>
            <h2 id={section.title} className="landing-section__title">
              {t(section.title)}
            </h2>
            <p className="landing-section__lead">{t(section.text)}</p>
            {section.list ? (
              <ul className="landing-module__list ev-tv-section-list">
                {section.list.map(itemKey => (
                  <li key={itemKey}>{t(itemKey)}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ))}

        <section className="landing-section" aria-labelledby="evTvContactTitle">
          <h2 id="evTvContactTitle" className="landing-section__title">
            {t('evTvContactTitle')}
          </h2>
          <p className="landing-section__lead">{t('evTvCostNote')}</p>
          <p className="landing-section__lead">
            {t('evTvContactName')}
            <br />
            <a href="mailto:bodnya.aleksey@gmail.com">bodnya.aleksey@gmail.com</a>
          </p>
        </section>
      </main>
    </div>
  );
}
