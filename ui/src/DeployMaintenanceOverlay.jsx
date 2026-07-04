import { useCallback, useEffect, useState } from 'react';
import './deploy-maintenance.css';

const POLL_MS = 3000;

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  if (!base) return path;
  return `${base}${path}`;
}

export default function DeployMaintenanceOverlay({ t }) {
  const [active, setActive] = useState(false);

  const check = useCallback(async () => {
    try {
      const r = await fetch(apiUrl('/api/health'), { cache: 'no-store' });
      setActive(!r.ok);
    } catch {
      setActive(true);
    }
  }, []);

  useEffect(() => {
    void check();
    const id = window.setInterval(() => void check(), POLL_MS);
    return () => window.clearInterval(id);
  }, [check]);

  if (!active) return null;

  return (
    <div className="deploy-maintenance-overlay" role="status" aria-live="polite">
      <p className="deploy-maintenance-overlay__text">{t('deployMaintenanceMessage')}</p>
    </div>
  );
}
