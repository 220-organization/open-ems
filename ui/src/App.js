import DamChartPage from './DamChartPage';
import PowerFlowPage from './PowerFlowPage';
import ServerMetricsBar from './ServerMetricsBar';
import { useI18n } from './useI18n';
import { useTheme } from './useTheme';

function currentSpaPage() {
  try {
    const p = (window.location.pathname || '/').replace(/\/$/, '') || '/';
    if (p === '/dam-chart') return 'dam';
    return 'power';
  } catch {
    return 'power';
  }
}

export default function App() {
  const i18n = useI18n();
  // Initialize theme — applies data-theme to <html> and tracks system preference.
  useTheme();
  return (
    <div className="app-root-layout">
      <div className="app-root-layout__main">
        {currentSpaPage() === 'dam' ? <DamChartPage {...i18n} /> : <PowerFlowPage {...i18n} />}
      </div>
      <footer className="app-shell-footer">
        <ServerMetricsBar />
      </footer>
    </div>
  );
}
