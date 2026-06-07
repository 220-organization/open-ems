import { useEffect, useState } from 'react';
import LandingPage from './LandingPage';
import OpenEmsHeader from './OpenEmsHeader';
import PowerFlowPage from './PowerFlowPage';
import ServerMetricsBar from './ServerMetricsBar';
import AndroidInstallBanner from './AndroidInstallBanner';
import { redirectLegacyDamChartPath, resolveOpenEmsPage } from './openEmsRoutes';
import { useI18n } from './useI18n';
import { useTheme } from './useTheme';

function readCurrentPage() {
  redirectLegacyDamChartPath();
  return resolveOpenEmsPage(window.location.pathname);
}

export default function App() {
  const i18n = useI18n();
  useTheme();
  const [page, setPage] = useState(readCurrentPage);

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
      <OpenEmsHeader {...i18n} activePage={page} />
      <div className="app-root-layout__main">
        {page === 'landing' ? <LandingPage {...i18n} /> : <PowerFlowPage {...i18n} />}
      </div>
      <footer className="app-shell-footer">
        <ServerMetricsBar />
      </footer>
    </div>
  );
}
