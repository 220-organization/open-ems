import { useCallback, useEffect, useRef, useState } from 'react';
import './server-metrics.css';

const METRICS_POLL_MS = 10_000;
const LOGS_POLL_MS = 5_000;
const LOGS_LIMIT = 50;

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
  const [logsOpen, setLogsOpen] = useState(false);
  const [logLines, setLogLines] = useState([]);
  const [logsStale, setLogsStale] = useState(false);
  const mounted = useRef(true);
  const logsPreRef = useRef(null);

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

  const fetchLogs = useCallback(async () => {
    try {
      const q = new URLSearchParams({ limit: String(LOGS_LIMIT) });
      const r = await fetch(`${apiUrl('/api/server-logs')}?${q}`, { cache: 'no-store' });
      if (!r.ok) throw new Error(String(r.status));
      const j = await r.json();
      if (!mounted.current) return;
      setLogLines(Array.isArray(j.lines) ? j.lines : []);
      setLogsStale(false);
    } catch {
      if (!mounted.current) return;
      setLogsStale(true);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void fetchMetrics();
    const id = window.setInterval(() => void fetchMetrics(), METRICS_POLL_MS);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
    };
  }, [fetchMetrics]);

  useEffect(() => {
    if (!logsOpen) return undefined;
    void fetchLogs();
    const id = window.setInterval(() => void fetchLogs(), LOGS_POLL_MS);
    return () => window.clearInterval(id);
  }, [logsOpen, fetchLogs]);

  useEffect(() => {
    if (!logsOpen || !logsPreRef.current) return;
    logsPreRef.current.scrollTop = logsPreRef.current.scrollHeight;
  }, [logsOpen, logLines]);

  const label =
    data == null
      ? 'Server metrics: loading'
      : `CPU ${data.cpu}%, memory ${formatGbFromMb(data.memUsed)} of ${formatGbFromMb(data.memTotal)} GB, database ${data.db != null ? `${formatGbFromMb(data.db)} GB` : 'n/a'}`;

  return (
    <div className="pf-server-metrics-wrap">
      {logsOpen ? (
        <div className="pf-server-logs" role="region" aria-label="Recent server logs">
          <div className="pf-server-logs-header">
            <span>Logs (last {LOGS_LIMIT})</span>
            <button type="button" className="pf-server-logs-close" onClick={() => setLogsOpen(false)}>
              ×
            </button>
          </div>
          <pre
            ref={logsPreRef}
            className={`pf-server-logs-pre${logsStale ? ' pf-server-logs-pre--stale' : ''}`}
          >
            {logLines.length > 0 ? logLines.join('\n') : logsStale ? 'Could not load logs.' : 'Loading…'}
          </pre>
        </div>
      ) : null}
      <button
        type="button"
        className={`pf-server-metrics${stale ? ' pf-server-metrics--stale' : ''}${logsOpen ? ' pf-server-metrics--open' : ''}`}
        aria-label={label}
        aria-expanded={logsOpen}
        title={`${label} — click for logs`}
        onClick={() => setLogsOpen(open => !open)}
      >
        {data == null ? (
          <span className="pf-server-metrics-inner">CPU: … · RAM: … · DB: …</span>
        ) : (
          <span className="pf-server-metrics-inner">
            CPU: {data.cpu}% · RAM: {formatGbFromMb(data.memUsed)}/{formatGbFromMb(data.memTotal)} GB · DB:{' '}
            {data.db != null ? `${formatGbFromMb(data.db)} GB` : '—'}
            <span className="pf-server-metrics-logs-hint"> · Logs</span>
          </span>
        )}
      </button>
    </div>
  );
}
