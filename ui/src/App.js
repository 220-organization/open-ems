import DamChartPage from './DamChartPage';
import PowerFlowPage from './PowerFlowPage';
import { useI18n } from './useI18n';

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
  return currentSpaPage() === 'dam' ? <DamChartPage {...i18n} /> : <PowerFlowPage {...i18n} />;
}
