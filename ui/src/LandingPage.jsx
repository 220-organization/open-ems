import { useEffect, useState } from 'react';
import './landing.css';
import { useOpenEmsSeo } from './useOpenEmsSeo';
import { useTheme } from './useTheme';
import RdnConsultationCallback from './RdnConsultationCallback';

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  return `${base}${path}`;
}

const OPEN_EMS_GITHUB_URL = 'https://github.com/220-organization/open-ems';
const SITE_220KM = 'https://220-km.com';

const MODULE_KEYS = [
  {
    tier: 'landingModuleSolarTier',
    title: 'landingModuleSolarTitle',
    desc: 'landingModuleSolarDesc',
    features: ['landingModuleSolarF1', 'landingModuleSolarF2', 'landingModuleSolarF3', 'landingModuleSolarF4'],
  },
  {
    tier: 'landingModuleActiveGridTier',
    title: 'landingModuleActiveGridTitle',
    desc: 'landingModuleActiveGridDesc',
    features: ['landingModuleActiveGridF1', 'landingModuleActiveGridF2', 'landingModuleActiveGridF3', 'landingModuleActiveGridF4'],
  },
  {
    tier: 'landingModuleArbitrageTier',
    title: 'landingModuleArbitrageTitle',
    desc: 'landingModuleArbitrageDesc',
    features: ['landingModuleArbitrageF1', 'landingModuleArbitrageF2', 'landingModuleArbitrageF3', 'landingModuleArbitrageF4'],
  },
  {
    tier: 'landingModuleMicroGridTier',
    title: 'landingModuleMicroGridTitle',
    desc: 'landingModuleMicroGridDesc',
    features: ['landingModuleMicroGridF1', 'landingModuleMicroGridF2', 'landingModuleMicroGridF3', 'landingModuleMicroGridF4'],
  },
];

const SCENARIO_KEYS = [
  { title: 'landingScenario1Title', text: 'landingScenario1Text' },
  { title: 'landingScenario2Title', text: 'landingScenario2Text' },
  { title: 'landingScenario3Title', text: 'landingScenario3Text' },
  { title: 'landingScenario4Title', text: 'landingScenario4Text' },
];

const AUDIENCE_KEYS = [
  {
    title: 'landingAudience1Title',
    subtitle: 'landingAudience1Subtitle',
    text: 'landingAudience1Text',
    bullets: ['landingAudience1B1', 'landingAudience1B2', 'landingAudience1B3'],
  },
  {
    title: 'landingAudience2Title',
    subtitle: 'landingAudience2Subtitle',
    text: 'landingAudience2Text',
    bullets: ['landingAudience2B1', 'landingAudience2B2', 'landingAudience2B3'],
  },
  {
    title: 'landingAudience3Title',
    subtitle: 'landingAudience3Subtitle',
    text: 'landingAudience3Text',
    bullets: ['landingAudience3B1', 'landingAudience3B2', 'landingAudience3B3'],
  },
];

const BENEFIT_KEYS = [
  { title: 'landingBenefit1Title', text: 'landingBenefit1Text' },
  { title: 'landingBenefit2Title', text: 'landingBenefit2Text' },
  { title: 'landingBenefit3Title', text: 'landingBenefit3Text' },
  { title: 'landingBenefit4Title', text: 'landingBenefit4Text' },
  { title: 'landingBenefit5Title', text: 'landingBenefit5Text' },
];

const STEP_KEYS = [
  { title: 'landingStep1Title', text: 'landingStep1Text' },
  { title: 'landingStep2Title', text: 'landingStep2Text' },
  { title: 'landingStep3Title', text: 'landingStep3Text', protocols: true },
  { title: 'landingStep4Title', text: 'landingStep4Text' },
];

export default function LandingPage({ t, locale }) {
  useTheme();
  useOpenEmsSeo(t('landingPageTitle'), locale, t, { variant: 'landing', canonicalPath: '/about' });
  const [batteryCapacityMwh, setBatteryCapacityMwh] = useState(null);
  const [batteryCapacityLoading, setBatteryCapacityLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(apiUrl('/api/power-flow/fleet-battery-capacity'), { cache: 'no-store' });
        if (!r.ok) return;
        const data = await r.json();
        if (cancelled || !data?.ok) return;
        const mwh = data.totalCapacityMwh;
        if (typeof mwh === 'number' && Number.isFinite(mwh) && mwh > 0) {
          setBatteryCapacityMwh(mwh);
        }
      } catch {
        /* landing stat is optional */
      } finally {
        if (!cancelled) setBatteryCapacityLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="landing-page">
      <main className="landing-main">
        <section className="landing-hero" aria-labelledby="landing-hero-title">
          <h1 id="landing-hero-title" className="landing-hero__title">
            {t('landingHeroTitle')}
          </h1>
          <div className="landing-hero__highlights">
            <article className="landing-hero__highlight">
              <h2 className="landing-hero__highlight-title">{t('landingHeroOpenTitle')}</h2>
              <p className="landing-hero__highlight-text">{t('landingHeroOpenText')}</p>
            </article>
            <article className="landing-hero__highlight">
              <h2 className="landing-hero__highlight-title">{t('landingHeroSecureTitle')}</h2>
              <p className="landing-hero__highlight-text">{t('landingHeroSecureText')}</p>
            </article>
          </div>
          {batteryCapacityLoading ? (
            <p className="landing-hero__capacity landing-hero__capacity--loading">{t('landingBatteryCapacityLoading')}</p>
          ) : batteryCapacityMwh != null ? (
            <p className="landing-hero__capacity">
              {t('landingBatteryCapacity', { value: batteryCapacityMwh.toFixed(2) })}
            </p>
          ) : null}
          <div className="landing-hero__cta">
            <a className="landing-btn landing-btn--primary" href="/">
              {t('landingCtaDemo')}
            </a>
            <a className="landing-btn landing-btn--secondary" href="#landing-contact">
              {t('landingCtaCallback')}
            </a>
          </div>
        </section>

        <section className="landing-section" aria-labelledby="landing-how-title">
          <h2 id="landing-how-title" className="landing-section__title">
            {t('landingHowTitle')}
          </h2>
          <p className="landing-section__lead">{t('landingHowLead')}</p>
          <figure className="landing-integration">
            <div className="landing-integration__visual">
              <img
                className="landing-integration__image"
                src={`${process.env.PUBLIC_URL || ''}/static/bess-integration-car-analogy.png`}
                alt={t('landingIntegrationImageAlt')}
                width={800}
                height={450}
                loading="lazy"
              />
              <div className="landing-integration__badge landing-integration__badge--modbus" aria-hidden="true">
                <span className="landing-integration__badge-title">{t('landingIntegrationModbusTitle')}</span>
                <span className="landing-integration__badge-caption">{t('landingIntegrationImageModbusCaption')}</span>
              </div>
              <div className="landing-integration__badge landing-integration__badge--rest" aria-hidden="true">
                <span className="landing-integration__badge-title">{t('landingIntegrationRestTitle')}</span>
                <span className="landing-integration__badge-caption">{t('landingIntegrationImageRestCaption')}</span>
              </div>
            </div>
            <div className="landing-integration__compare">
              <article className="landing-integration__option landing-integration__option--rest">
                <h3 className="landing-integration__option-title">{t('landingIntegrationRestTitle')}</h3>
                <p className="landing-integration__option-text">{t('landingIntegrationRestText')}</p>
              </article>
              <article className="landing-integration__option landing-integration__option--modbus">
                <h3 className="landing-integration__option-title">{t('landingIntegrationModbusTitle')}</h3>
                <p className="landing-integration__option-text">{t('landingIntegrationModbusText')}</p>
              </article>
            </div>
          </figure>
          <div className="landing-diagram" aria-hidden="true">
            <span className="landing-diagram__node">{t('landingDiagramSolar')}</span>
            <span className="landing-diagram__arrow">→</span>
            <span className="landing-diagram__node">{t('landingDiagramBess')}</span>
            <span className="landing-diagram__arrow">→</span>
            <span className="landing-diagram__node">{t('landingDiagramGrid')}</span>
            <span className="landing-diagram__arrow">→</span>
            <span className="landing-diagram__node">{t('landingDiagramEv')}</span>
          </div>
          <p className="landing-section__lead">{t('landingHowExample')}</p>
          <div className="landing-scenarios">
            {SCENARIO_KEYS.map((s, i) => (
              <article key={s.title} className="landing-scenario">
                <span className="landing-scenario__num">{i + 1}</span>
                <h3 className="landing-scenario__title">{t(s.title)}</h3>
                <p className="landing-scenario__text">{t(s.text)}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="landing-section" aria-labelledby="landing-modules-title">
          <h2 id="landing-modules-title" className="landing-section__title">
            {t('landingModulesTitle')}
          </h2>
          <p className="landing-section__lead">{t('landingModulesLead')}</p>
          <div className="landing-modules">
            {MODULE_KEYS.map(mod => (
              <article key={mod.title} className="landing-module">
                <span className="landing-module__tier">{t(mod.tier)}</span>
                <h3 className="landing-module__title">{t(mod.title)}</h3>
                <p className="landing-module__desc">{t(mod.desc)}</p>
                <ul className="landing-module__list">
                  {mod.features.map(fk => (
                    <li key={fk}>{t(fk)}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section className="landing-section" aria-labelledby="landing-audience-title">
          <h2 id="landing-audience-title" className="landing-section__title">
            {t('landingAudienceTitle')}
          </h2>
          <div className="landing-audience">
            {AUDIENCE_KEYS.map(a => (
              <article key={a.title} className="landing-audience-card">
                <h3 className="landing-audience-card__title">{t(a.title)}</h3>
                <p className="landing-audience-card__subtitle">{t(a.subtitle)}</p>
                <p className="landing-audience-card__text">{t(a.text)}</p>
                <ul className="landing-module__list">
                  {a.bullets.map(bk => (
                    <li key={bk}>{t(bk)}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section className="landing-section" aria-labelledby="landing-connect-title">
          <h2 id="landing-connect-title" className="landing-section__title">
            {t('landingConnectTitle')}
          </h2>
          <p className="landing-section__lead">{t('landingConnectLead')}</p>
          <div className="landing-steps">
            {STEP_KEYS.map((step, i) => (
              <article key={step.title} className="landing-step">
                <span className="landing-step__num">{String(i + 1).padStart(2, '0')}</span>
                <h3 className="landing-step__title">{t(step.title)}</h3>
                <p className="landing-step__text">{t(step.text)}</p>
                {step.protocols ? (
                  <div className="landing-protocols">
                    <span className="landing-protocols__tag">Modbus</span>
                    <span className="landing-protocols__tag">MQTT</span>
                    <span className="landing-protocols__tag">OPC UA</span>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </section>

        <section className="landing-section" aria-labelledby="landing-benefits-title">
          <h2 id="landing-benefits-title" className="landing-section__title">
            {t('landingBenefitsTitle')}
          </h2>
          <p className="landing-section__lead">{t('landingBenefitsLead')}</p>
          <div className="landing-benefits">
            {BENEFIT_KEYS.map(b => (
              <article key={b.title} className="landing-benefit">
                <h3 className="landing-benefit__title">{t(b.title)}</h3>
                <p className="landing-benefit__text">{t(b.text)}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="landing-contact" className="landing-section" aria-labelledby="landing-contact-title">
          <h2 id="landing-contact-title" className="landing-section__title">
            {t('landingContactTitle')}
          </h2>
          <p className="landing-section__lead">{t('landingContactLead')}</p>
          <div className="landing-contact">
            <RdnConsultationCallback t={t} htmlIdPrefix="landing-" rootClassName="landing-contact__form" />
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer__links">
          <a href="/">{t('landingNavDemo')}</a>
          <a href={OPEN_EMS_GITHUB_URL} target="_blank" rel="noopener noreferrer">
            GitHub
          </a>
          <a href={SITE_220KM} target="_blank" rel="noopener noreferrer">
            220-km.com
          </a>
        </div>
        <p>{t('landingFooterCopy')}</p>
      </footer>
    </div>
  );
}
