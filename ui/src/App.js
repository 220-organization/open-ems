import { useEffect, useState } from 'react';
import LandingPage from './LandingPage';
import EvTvPage from './EvTvPage';
import OpenEmsHeader from './OpenEmsHeader';
import PowerFlowPage from './PowerFlowPage';
import ServerMetricsBar from './ServerMetricsBar';
import AndroidInstallBanner from './AndroidInstallBanner';
import { redirectLegacyDamChartPath, resolveOpenEmsPage } from './openEmsRoutes';
import { useAutoHideChrome } from './useAutoHideChrome';
import { useI18n } from './useI18n';
import { useTheme } from './useTheme';

function readCurrentPage() {
  redirectLegacyDamChartPath();
  return resolveOpenEmsPage(window.location.pathname);
}

export default function App() {
  const i18n = useI18n();
  const { theme, isDark, cycleTheme } = useTheme();
  const [page, setPage] = useState(readCurrentPage);
  const chromeHidden = useAutoHideChrome();

  useEffect(() => {
    document.documentElement.classList.toggle('open-ems-chrome-hidden', chromeHidden);
    return () => document.documentElement.classList.remove('open-ems-chrome-hidden');
  }, [chromeHidden]);

  useEffect(() => {
    const syncPage = () => {
      redirectLegacyDamChartPath();
      setPage(readCurrentPage());
    };
    window.addEventListener('popstate', syncPage);
    return () => window.removeEventListener('popstate', syncPage);
  }, []);

  return (
    <div className="app-root-layout">
      <AndroidInstallBanner t={i18n.t} />
      <OpenEmsHeader
        {...i18n}
        activePage={page}
        theme={theme}
        cycleTheme={cycleTheme}
        chromeHidden={chromeHidden}
      />
      <div className="app-root-layout__main">
        {page === 'landing' ? (
          <LandingPage {...i18n} />
        ) : page === 'evTv' ? (
          <EvTvPage {...i18n} />
        ) : (
          <PowerFlowPage {...i18n} isDark={isDark} />
        )}
      </div>
      <footer className="app-shell-footer">
        <ServerMetricsBar />
      </footer>
    </div>
  );
}
