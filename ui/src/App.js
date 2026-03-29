import PowerFlowPage from './PowerFlowPage';
import { useI18n } from './useI18n';

export default function App() {
  const i18n = useI18n();
  return <PowerFlowPage {...i18n} />;
}
