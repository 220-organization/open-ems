import './power-flow.css';
import './landing.css';

const OPEN_EMS_GITHUB_URL = 'https://github.com/220-organization/open-ems';

/**
 * Site-wide sticky header (brand, nav, language).
 * @param {'power' | 'landing'} activePage
 */
export default function OpenEmsHeader({ t, locale, SUPPORTED, LOCALE_NAMES, onLangSelectChange, activePage }) {
  const logoSrc = `${process.env.PUBLIC_URL || ''}/static/open-ems-220-logo.svg`;

  const navLinkClass = page => `landing-nav__link${activePage === page ? ' landing-nav__link--active' : ''}`;

  return (
    <header className="landing-header open-ems-header">
      <a className="landing-header__brand" href="/">
        <img className="landing-header__logo" src={logoSrc} alt="" width={36} height={36} decoding="async" />
        <span className="landing-header__name">Open EMS</span>
      </a>
      <nav className="landing-nav" aria-label={t('landingNavAria')}>
        <a className={navLinkClass('power')} href="/">
          {t('landingNavDemo')}
        </a>
        <a className={navLinkClass('landing')} href="/about">
          {t('landingNavHome')}
        </a>
        <a className="landing-nav__link" href={OPEN_EMS_GITHUB_URL} target="_blank" rel="noopener noreferrer">
          {t('landingNavGithub')}
        </a>
      </nav>
      <div className="landing-header__actions">
        <select
          className="pf-lang-select"
          aria-label={t('langSelectAria')}
          value={locale}
          onChange={onLangSelectChange}
        >
          {SUPPORTED.map(code => (
            <option key={code} value={code}>
              {LOCALE_NAMES[code] || code}
            </option>
          ))}
        </select>
      </div>
    </header>
  );
}
