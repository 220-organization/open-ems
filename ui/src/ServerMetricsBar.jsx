import { useCallback, useEffect, useRef, useState } from 'react';
import './server-metrics.css';

const POLL_MS = 10_000;

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  if (!base) return path;
  return `${base}${path}`;
}

/** Format megabytes as binary GB (GiB) for display. */
function formatGbFromMb(megabytes) {
  if (megabytes == null || !Number.isFinite(megabytes)) return '—';
  const gib = megabytes / 1024;
  const rounded = gib >= 10 ? gib.toFixed(1) : gib.toFixed(2);
  return String(Number.parseFloat(rounded));
}

export default function ServerMetricsBar() {
  const [data, setData] = useState(null);
  const [stale, setStale] = useState(false);
  const mounted = useRef(true);

  const fetchMetrics = useCallback(async () => {
    try {
      const r = await fetch(apiUrl('/api/server-metrics'), { cache: 'no-store' });
      if (!r.ok) throw new Error(String(r.status));
      const j = await r.json();
      if (!mounted.current) return;
      setData({
        cpu: j.cpu_percent,
        memUsed: j.memory_used_mb,
        memTotal: j.memory_total_mb,
        db: j.db_size_mb,
      });
      setStale(false);
    } catch {
      if (!mounted.current) return;
      setStale(true);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void fetchMetrics();
    const id = window.setInterval(() => void fetchMetrics(), POLL_MS);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
    };
  }, [fetchMetrics]);

  const label =
    data == null
      ? 'Server metrics: loading'
      : `CPU ${data.cpu}%, memory ${formatGbFromMb(data.memUsed)} of ${formatGbFromMb(data.memTotal)} GB, database ${data.db != null ? `${formatGbFromMb(data.db)} GB` : 'n/a'}`;

  return (
    <div
      className={`pf-server-metrics${stale ? ' pf-server-metrics--stale' : ''}`}
      role="status"
      aria-live="polite"
      aria-label={label}
      title={label}
    >
      {data == null ? (
        <span className="pf-server-metrics-inner">CPU: … · RAM: … · DB: …</span>
      ) : (
        <span className="pf-server-metrics-inner">
          CPU: {data.cpu}% · RAM: {formatGbFromMb(data.memUsed)}/{formatGbFromMb(data.memTotal)} GB · DB:{' '}
          {data.db != null ? `${formatGbFromMb(data.db)} GB` : '—'}
        </span>
      )}
    </div>
  );
}
