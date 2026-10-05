import { useEffect, useState } from 'react';
import { isSlowConnection, readConnection } from './slowNetNotice';
import './slow-net-notice.css';

function linkIsSlow() {
  return isSlowConnection(readConnection(navigator), navigator.onLine);
}

function readSlow() {
  if (linkIsSlow()) return true;
  return window.__OPEN_EMS_SLOW_NET === true;
}

export default function SlowInternetNotice({ t }) {
  const [slow, setSlow] = useState(readSlow);

  useEffect(() => {
    const update = () => {
      const conn = readConnection(navigator);
      if (isSlowConnection(conn, navigator.onLine)) {
        window.__OPEN_EMS_SLOW_NET = true;
        setSlow(true);
        return;
      }
      if (navigator.onLine && conn) {
        window.__OPEN_EMS_SLOW_NET = false;
        setSlow(false);
        return;
      }
      setSlow(window.__OPEN_EMS_SLOW_NET === true || navigator.onLine === false);
    };

    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    const conn = readConnection(navigator);
    conn?.addEventListener?.('change', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
      conn?.removeEventListener?.('change', update);
    };
  }, []);

  if (!slow) return null;

  return (
    <div className="slow-net-banner" role="status" aria-live="polite">
      <p className="slow-net-banner__text">{t('slowInternetMessage')}</p>
      <button type="button" className="slow-net-banner__retry" onClick={() => window.location.reload()}>
        {t('slowInternetReconnect')}
      </button>
    </div>
  );
}
