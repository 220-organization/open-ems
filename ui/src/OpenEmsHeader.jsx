import { useCallback, useEffect, useRef, useState } from 'react';
import SharePageModal from './SharePageModal';
import './power-flow.css';
import './landing.css';

const OPEN_EMS_GITHUB_URL = 'https://github.com/220-organization/open-ems';

function themeToggleLabels(theme) {
  if (theme === 'dark') {
    return {
      aria: 'Switch to system theme',
      title: 'Dark theme (click for system)',
    };
  }
  if (theme === 'light') {
    return {
      aria: 'Switch to dark theme',
      title: 'Light theme (click for dark)',
    };
  }
  return {
    aria: 'Switch to light theme',
    title: 'System theme (click for light)',
  };
}

function ThemeToggleIcon({ theme }) {
  if (theme === 'dark') {
    return (
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z" />
      </svg>
    );
  }
  if (theme === 'light') {
    return (
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="5" />
        <line x1="12" y1="1" x2="12" y2="3" />
        <line x1="12" y1="21" x2="12" y2="23" />
        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
        <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
        <line x1="1" y1="12" x2="3" y2="12" />
        <line x1="21" y1="12" x2="23" y2="12" />
        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
        <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
      </svg>
    );
  }
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

/**
 * Site-wide sticky header (brand, nav, language).
 * @param {'power' | 'landing' | 'evTv'} activePage
 */
export default function OpenEmsHeader({
  t,
  locale,
  SUPPORTED,
  LOCALE_NAMES,
  onLangSelectChange,
  activePage,
  theme,
  cycleTheme,
  chromeHidden = false,
}) {
  const logoSrc = `${process.env.PUBLIC_URL || ''}/static/open-ems-220-logo.svg`;
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareModalUrl, setShareModalUrl] = useState('');
  const [shareModalCopied, setShareModalCopied] = useState(false);
  const [shareModalCopyFailed, setShareModalCopyFailed] = useState(false);

  const navLinkClass = page => `landing-nav__link${activePage === page ? ' landing-nav__link--active' : ''}`;
  const themeLabels = themeToggleLabels(theme);

  const handleSharePage = useCallback(async () => {
    let url = '';
    try {
      url = window.location.href.split('#')[0];
    } catch {
      url = '';
    }
    if (!url) return;

    let copied = false;
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        copied = true;
      }
    } catch {
      copied = false;
    }

    setShareModalUrl(url);
    setShareModalCopied(copied);
    setShareModalCopyFailed(!copied);
    setShareModalOpen(true);
  }, []);

  const closeShareModal = useCallback(() => {
    setShareModalOpen(false);
  }, []);

  const shellRef = useRef(null);

  useEffect(() => {
    const el = shellRef.current;
    if (!el) return undefined;

    const syncHeaderOffset = () => {
      const headerInner = el.querySelector('.landing-header');
      const naturalH = headerInner ? Math.ceil(headerInner.getBoundingClientRect().height) : 0;
      document.documentElement.style.setProperty('--open-ems-site-header-h', chromeHidden ? '0px' : `${naturalH}px`);
    };

    const headerInner = el.querySelector('.landing-header');

    syncHeaderOffset();
    const ro = new ResizeObserver(syncHeaderOffset);
    ro.observe(el);
    if (headerInner) ro.observe(headerInner);
    window.addEventListener('resize', syncHeaderOffset);

    return () => {
      ro.disconnect();
      window.removeEventListener('resize', syncHeaderOffset);
      document.documentElement.style.removeProperty('--open-ems-site-header-h');
    };
  }, [locale, activePage, chromeHidden]);

  return (
    <>
      <div ref={shellRef} className="open-ems-header-shell">
        <header className="landing-header open-ems-header">
        <a className="landing-header__brand" href="/">
          <img className="landing-header__logo" src={logoSrc} alt="" width={36} height={36} decoding="async" />
          <span className="landing-header__name">{t('appBrandName')}</span>
        </a>
        <nav className="landing-nav" aria-label={t('landingNavAria')}>
          <a className={navLinkClass('power')} href="/">
            {t('landingNavDemo')}
          </a>
          <a className={navLinkClass('landing')} href="/about">
            {t('landingNavHome')}
          </a>
          <a className={navLinkClass('evTv')} href="/ev-tv">
            {t('evTvNavLabel')}
          </a>
          <a className="landing-nav__link" href={OPEN_EMS_GITHUB_URL} target="_blank" rel="noopener noreferrer">
            {t('landingNavGithub')}
          </a>
        </nav>
        <div className="landing-header__actions">
          <button
            type="button"
            className="pf-share-btn"
            onClick={() => void handleSharePage()}
            aria-label={t('sharePageAria')}
            title={t('sharePageAria')}
          >
            <svg
              className="pf-share-btn__icon"
              viewBox="0 0 24 24"
              width="18"
              height="18"
              aria-hidden="true"
              focusable="false"
            >
              <path
                fill="currentColor"
                d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"
              />
            </svg>
          </button>
          <button
            type="button"
            className="pf-theme-btn"
            onClick={cycleTheme}
            aria-label={themeLabels.aria}
            title={themeLabels.title}
          >
            <ThemeToggleIcon theme={theme} />
          </button>
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
      </div>
      <SharePageModal
        open={shareModalOpen}
        url={shareModalUrl}
        copied={shareModalCopied}
        copyFailed={shareModalCopyFailed}
        onClose={closeShareModal}
        t={t}
      />
    </>
  );
}
