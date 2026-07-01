import { useCallback, useEffect, useState } from 'react';

const REFRESH_MS = 30 * 60 * 1000;

function apiUrl(path) {
  const base = (process.env.REACT_APP_API_BASE_URL || '').replace(/\/$/, '');
  if (!base) return path;
  return `${base}${path}`;
}

export function useSolarInsolationHourly(deviceSn) {
  const [todayHourlyInsolation, setTodayHourlyInsolation] = useState(null);
  const [tomorrowHourlyInsolation, setTomorrowHourlyInsolation] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    const sn = String(deviceSn || '').trim();
    if (!sn) {
      setTodayHourlyInsolation(null);
      setTomorrowHourlyInsolation(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const q = new URLSearchParams({ deviceSn: sn });
      const r = await fetch(`${apiUrl('/api/deye/solar-insolation-hourly')}?${q}`, { cache: 'no-store' });
      if (!r.ok) {
        setTodayHourlyInsolation(null);
        setTomorrowHourlyInsolation(null);
        return;
      }
      const data = await r.json();
      if (!data?.ok) {
        setTodayHourlyInsolation(null);
        setTomorrowHourlyInsolation(null);
        return;
      }
      setTodayHourlyInsolation(data.today ?? null);
      setTomorrowHourlyInsolation(data.tomorrow ?? null);
    } catch {
      setTodayHourlyInsolation(null);
      setTomorrowHourlyInsolation(null);
    } finally {
      setLoading(false);
    }
  }, [deviceSn]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const sn = String(deviceSn || '').trim();
      if (!sn) {
        if (!cancelled) {
          setTodayHourlyInsolation(null);
          setTomorrowHourlyInsolation(null);
          setLoading(false);
        }
        return;
      }
      if (!cancelled) setLoading(true);
      try {
        const q = new URLSearchParams({ deviceSn: sn });
        const r = await fetch(`${apiUrl('/api/deye/solar-insolation-hourly')}?${q}`, { cache: 'no-store' });
        if (cancelled) return;
        if (!r.ok) {
          setTodayHourlyInsolation(null);
          setTomorrowHourlyInsolation(null);
          return;
        }
        const data = await r.json();
        if (!data?.ok) {
          setTodayHourlyInsolation(null);
          setTomorrowHourlyInsolation(null);
          return;
        }
        setTodayHourlyInsolation(data.today ?? null);
        setTomorrowHourlyInsolation(data.tomorrow ?? null);
      } catch {
        if (!cancelled) {
          setTodayHourlyInsolation(null);
          setTomorrowHourlyInsolation(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    run();
    const timerId = window.setInterval(run, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timerId);
    };
  }, [deviceSn]);

  return {
    todayHourlyInsolation,
    tomorrowHourlyInsolation,
    loading,
    refresh: load,
  };
}
